"""
Technical indicators used by the strategy:
- Heiken Ashi candles
- Parabolic SAR (0.02 start, 0.02 step, 0.2 max — matches the TradingView
  settings shown in the strategy screenshots: "SAR 0.02 0.02 0.2")
- RSI(14) on real close price, Wilder's smoothing (TradingView default RSI)

All functions take/return pandas Series/DataFrames indexed by candle
timestamp (3-minute bars) and are pure functions with no side effects,
so they're easy to unit test independently of the live data feed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def heiken_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert a regular OHLC dataframe (columns: open, high, low, close) into
    Heiken Ashi OHLC.

    ha_close = (O + H + L + C) / 4
    ha_open  = (prev ha_open + prev ha_close) / 2   (first bar: (O+C)/2)
    ha_high  = max(H, ha_open, ha_close)
    ha_low   = min(L, ha_open, ha_close)
    """
    ha = pd.DataFrame(index=df.index)
    ha["ha_close"] = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0

    ha_open = np.empty(len(df))
    ha_open[:] = np.nan
    if len(df) > 0:
        ha_open[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2.0
        ha_close_vals = ha["ha_close"].values
        for i in range(1, len(df)):
            ha_open[i] = (ha_open[i - 1] + ha_close_vals[i - 1]) / 2.0
    ha["ha_open"] = ha_open

    ha["ha_high"] = pd.concat(
        [df["high"], ha["ha_open"], ha["ha_close"]], axis=1
    ).max(axis=1)
    ha["ha_low"] = pd.concat(
        [df["low"], ha["ha_open"], ha["ha_close"]], axis=1
    ).min(axis=1)

    return ha


def ha_candle_color(ha: pd.DataFrame, eps: float = 1e-6) -> pd.Series:
    """
    Classify each Heiken Ashi candle per the strategy's exact definition:

      - "bullish" : no lower body  -> ha_low  == ha_open  (no lower wick)
      - "bearish" : no upper body  -> ha_high == ha_open  (no upper wick)
      - "neutral" : neither (a candle with wicks on both sides)

    This matches the article's wording literally rather than the looser
    ha_close > ha_open definition, since the strategy screenshots
    specifically call out the *no-wick* candle as the trigger.
    """
    bullish = (ha["ha_open"] - ha["ha_low"]).abs() <= eps
    bearish = (ha["ha_high"] - ha["ha_open"]).abs() <= eps

    color = pd.Series("neutral", index=ha.index)
    color[bullish] = "bullish"
    # a candle can't satisfy both unless it's a doji with zero range;
    # bearish check only applied where not already bullish
    color[bearish & ~bullish] = "bearish"
    return color


def parabolic_sar(
    df: pd.DataFrame,
    af_start: float = 0.02,
    af_step: float = 0.02,
    af_max: float = 0.2,
) -> pd.DataFrame:
    """
    Standard Wilder Parabolic SAR, computed off High/Low.

    Returns a DataFrame with columns:
      - sar   : the SAR value for that bar
      - trend : 1 for uptrend, -1 for downtrend
    """
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    sar = np.zeros(n)
    trend = np.zeros(n, dtype=int)
    ep = np.zeros(n)
    af = np.zeros(n)

    if n == 0:
        return pd.DataFrame({"sar": [], "trend": []}, index=df.index)

    # Seed the first bar assuming an uptrend start (arbitrary but standard;
    # it self-corrects within a few bars, and we always fetch plenty of
    # warm-up history before "today" so this doesn't affect live signals).
    trend[0] = 1
    sar[0] = low[0]
    ep[0] = high[0]
    af[0] = af_start

    for i in range(1, n):
        prev_sar = sar[i - 1]
        prev_ep = ep[i - 1]
        prev_af = af[i - 1]
        prev_trend = trend[i - 1]

        if prev_trend == 1:
            candidate = prev_sar + prev_af * (prev_ep - prev_sar)
            bound = low[i - 1] if i < 2 else min(low[i - 1], low[i - 2])
            candidate = min(candidate, bound)

            if low[i] < candidate:
                # flip to downtrend
                trend[i] = -1
                sar[i] = prev_ep
                ep[i] = low[i]
                af[i] = af_start
            else:
                trend[i] = 1
                sar[i] = candidate
                if high[i] > prev_ep:
                    ep[i] = high[i]
                    af[i] = min(prev_af + af_step, af_max)
                else:
                    ep[i] = prev_ep
                    af[i] = prev_af
        else:
            candidate = prev_sar + prev_af * (prev_ep - prev_sar)
            bound = high[i - 1] if i < 2 else max(high[i - 1], high[i - 2])
            candidate = max(candidate, bound)

            if high[i] > candidate:
                # flip to uptrend
                trend[i] = 1
                sar[i] = prev_ep
                ep[i] = high[i]
                af[i] = af_start
            else:
                trend[i] = -1
                sar[i] = candidate
                if low[i] < prev_ep:
                    ep[i] = low[i]
                    af[i] = min(prev_af + af_step, af_max)
                else:
                    ep[i] = prev_ep
                    af[i] = prev_af

    return pd.DataFrame({"sar": sar, "trend": trend}, index=df.index)


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """
    Wilder's RSI (matches TradingView's default RSI(14, close)).
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    # where avg_loss is 0 and avg_gain > 0, RSI is 100
    out[(avg_loss == 0) & (avg_gain > 0)] = 100.0
    # where both are 0 (flat price), RSI is undefined -> treat as neutral 50
    out[(avg_loss == 0) & (avg_gain == 0)] = 50.0
    return out


def build_indicator_frame(
    df: pd.DataFrame,
    af_start: float = 0.02,
    af_step: float = 0.02,
    af_max: float = 0.2,
    rsi_length: int = 14,
) -> pd.DataFrame:
    """
    Convenience: given raw 3-min OHLC (open, high, low, close), return one
    combined dataframe with HA candle color, PSAR, PSAR trend and RSI,
    aligned on the same index — everything the strategy needs per bar.
    """
    ha = heiken_ashi(df)
    color = ha_candle_color(ha)
    sar_df = parabolic_sar(df, af_start=af_start, af_step=af_step, af_max=af_max)
    rsi_series = rsi(df["close"], length=rsi_length)

    out = df.copy()
    out["ha_open"] = ha["ha_open"]
    out["ha_high"] = ha["ha_high"]
    out["ha_low"] = ha["ha_low"]
    out["ha_close"] = ha["ha_close"]
    out["ha_color"] = color
    out["sar"] = sar_df["sar"]
    out["sar_trend"] = sar_df["trend"]
    out["rsi"] = rsi_series
    return out


# ---------------------------------------------------------------------------
# Strategy 2: RSI Divergence + Bollinger Bands
# ---------------------------------------------------------------------------


def bollinger_bands(close: pd.Series, length: int = 20, mult: float = 2.0) -> pd.DataFrame:
    """
    Standard Bollinger Bands (matches the "BB 20 close 2 0" settings shown
    in the strategy screenshots: length=20, source=close, mult=2, offset=0).
    Uses population std-dev (ddof=0), the common convention for BB.
    """
    basis = close.rolling(length).mean()
    dev = close.rolling(length).std(ddof=0)
    upper = basis + mult * dev
    lower = basis - mult * dev
    return pd.DataFrame({"bb_basis": basis, "bb_upper": upper, "bb_lower": lower})


def find_pivots(df: pd.DataFrame, left: int = 3, right: int = 3) -> pd.DataFrame:
    """
    Confirmed swing-point (pivot) detection, the same idea as TradingView's
    Pivot High/Low: a bar is a pivot low if its `low` is the strict minimum
    within a window of `left` bars before it and `right` bars after it (and
    a pivot high is the mirror on `high`). A pivot at bar i can only be
    confirmed once `right` further bars exist, so — same as on a live chart
    — there's an inherent few-bar confirmation lag; this is expected and
    standard for real-time divergence detection.

    Returns a DataFrame of booleans (pivot_low, pivot_high) aligned to df.
    """
    low = df["low"]
    high = df["high"]
    n = len(df)

    pivot_low = pd.Series(False, index=df.index)
    pivot_high = pd.Series(False, index=df.index)

    for i in range(left, n - right):
        lo_window = low.iloc[i - left : i + right + 1]
        if low.iloc[i] == lo_window.min() and (lo_window == low.iloc[i]).sum() == 1:
            pivot_low.iloc[i] = True

        hi_window = high.iloc[i - left : i + right + 1]
        if high.iloc[i] == hi_window.max() and (hi_window == high.iloc[i]).sum() == 1:
            pivot_high.iloc[i] = True

    return pd.DataFrame({"pivot_low": pivot_low, "pivot_high": pivot_high})


def build_indicator_frame_bb(
    df: pd.DataFrame,
    bb_length: int = 20,
    bb_mult: float = 2.0,
    rsi_length: int = 14,
    pivot_left: int = 3,
    pivot_right: int = 3,
) -> pd.DataFrame:
    """
    Combined indicator frame for the RSI Divergence + Bollinger Bands
    strategy: BB(20,2), RSI(14) and confirmed swing pivots, all aligned to
    the same (1-minute, per the strategy) bar index.
    """
    bb = bollinger_bands(df["close"], length=bb_length, mult=bb_mult)
    rsi_series = rsi(df["close"], length=rsi_length)
    pivots = find_pivots(df, left=pivot_left, right=pivot_right)

    out = df.copy()
    out["bb_basis"] = bb["bb_basis"]
    out["bb_upper"] = bb["bb_upper"]
    out["bb_lower"] = bb["bb_lower"]
    out["rsi"] = rsi_series
    out["pivot_low"] = pivots["pivot_low"]
    out["pivot_high"] = pivots["pivot_high"]
    return out


# ---------------------------------------------------------------------------
# Strategy 3: RSI + VWAP Scalping
# ---------------------------------------------------------------------------


def session_vwap(
    df: pd.DataFrame, band_mults: tuple = (1, 2, 3)
) -> pd.DataFrame:
    """
    Session (intraday) VWAP with standard-deviation bands, matching the
    "VWAP Session hlc3 0 1 2 3" settings in the strategy screenshots:
    source=hlc3, offset=0, bands at 1/2/3 standard deviations. Resets at
    the start of each trading day (grouped by the bar index's calendar
    date — df.index must already be tz-aware in the exchange's timezone,
    which data_feed.py guarantees).

    Caveat: true VWAP needs real traded volume. Index tickers (e.g.
    ^NSEI) often report zero volume on free data feeds — if a session's
    total volume is 0, this falls back to an equal-weighted running
    average of hlc3 for that session (still a sensible support/resistance
    reference line, just not volume-weighted). `used_volume_fallback`
    flags which bars fell back, so the caller can log a one-time warning.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    volume = df["volume"].fillna(0.0) if "volume" in df.columns else pd.Series(0.0, index=df.index)

    session = pd.Series(df.index.date, index=df.index)
    session_vol_total = volume.groupby(session).transform("sum")
    fallback = session_vol_total <= 0
    weight = volume.where(~fallback, 1.0)

    cum_w = weight.groupby(session).cumsum()
    cum_wp = (weight * typical_price).groupby(session).cumsum()
    vwap = cum_wp / cum_w

    cum_wp2 = (weight * typical_price**2).groupby(session).cumsum()
    variance = (cum_wp2 / cum_w - vwap**2).clip(lower=0.0)
    std = np.sqrt(variance)

    out = pd.DataFrame({"vwap": vwap, "vwap_std": std}, index=df.index)
    for m in band_mults:
        out[f"vwap_upper{m}"] = vwap + m * std
        out[f"vwap_lower{m}"] = vwap - m * std
    out["used_volume_fallback"] = fallback
    return out


def build_indicator_frame_vwap(
    df: pd.DataFrame,
    rsi_length: int = 14,
    band_mults: tuple = (1, 2, 3),
    recent_window: int = 10,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 70.0,
) -> pd.DataFrame:
    """
    Combined indicator frame for the RSI + VWAP scalping strategy: session
    VWAP with bands, RSI(14), and rolling flags for "RSI was oversold/
    overbought within the last `recent_window` bars" (so a VWAP touch a
    few bars after the RSI extreme still counts, matching how this is
    read on a real chart rather than requiring the exact same candle).
    """
    vwap_df = session_vwap(df, band_mults=band_mults)
    rsi_series = rsi(df["close"], length=rsi_length)

    out = df.copy()
    for col in vwap_df.columns:
        out[col] = vwap_df[col]
    out["rsi"] = rsi_series
    out["recent_oversold"] = rsi_series.rolling(recent_window, min_periods=1).min() < rsi_oversold
    out["recent_overbought"] = rsi_series.rolling(recent_window, min_periods=1).max() > rsi_overbought
    return out


# ---------------------------------------------------------------------------
# Strategy 4: 1-Minute Consolidation Breakout Scalping
# ---------------------------------------------------------------------------


def ema(close: pd.Series, length: int) -> pd.Series:
    return close.ewm(span=length, adjust=False).mean()


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Wilder's Average True Range."""
    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1.0 / length, adjust=False).mean()


def build_indicator_frame_consolidation(
    df: pd.DataFrame,
    ema_length: int = 9,
    trend_lookback: int = 15,
    range_bars: int = 5,
    atr_length: int = 14,
) -> pd.DataFrame:
    """
    Combined indicator frame for the consolidation-breakout strategy:
      - trend: 'up' / 'down' / 'none', from the slope of EMA(ema_length)
        over the last `trend_lookback` bars (a simple, adaptive stand-in
        for "identify the pre-established trend" — no fixed price
        threshold needed since it's relative to the EMA's own history).
      - range_high / range_low: the high/low of the `range_bars` candles
        immediately BEFORE the current bar (rolling window, shifted by
        one) — this is the "next 4-5 candles form a range" the strategy
        describes; the current (possible breakout) bar is never counted
        as part of its own range.
      - atr: Wilder ATR(atr_length), used by strategy4.py to judge
        whether that range is actually "tight" (a consolidation) rather
        than just a random slice of a trending move.
    """
    ema_series = ema(df["close"], ema_length)
    ema_slope = ema_series.diff(trend_lookback)
    trend = pd.Series("none", index=df.index)
    trend[ema_slope > 0] = "up"
    trend[ema_slope < 0] = "down"

    atr_series = atr(df, length=atr_length)
    range_high = df["high"].rolling(range_bars).max().shift(1)
    range_low = df["low"].rolling(range_bars).min().shift(1)

    out = df.copy()
    out["ema"] = ema_series
    out["trend"] = trend
    out["atr"] = atr_series
    out["range_high"] = range_high
    out["range_low"] = range_low
    return out


# ---------------------------------------------------------------------------
# Strategy 5: Moving Average Scalping
# ---------------------------------------------------------------------------


def build_indicator_frame_ma(
    df: pd.DataFrame,
    ema_length: int = 7,
    market_open: str = "09:15",
    first_hour_end: str = "10:15",
) -> pd.DataFrame:
    """
    Combined indicator frame for the Moving Average Scalping strategy:
      - ema: EMA(5 or 7) on close, on 5-minute bars.
      - bar_index_in_day: 0-based candle count since market open each day
        (used to skip the very first candle of the day — "too volatile" per
        the write-up).
      - in_first_hour: True for bars starting in [market_open, first_hour_end)
        — the strategy only takes setups/entries in the first trading hour.
    """
    ema_series = ema(df["close"], ema_length)
    out = df.copy()
    out["ema"] = ema_series

    dates = out.index.normalize()
    out["bar_index_in_day"] = out.groupby(dates).cumcount()

    times = out.index.strftime("%H:%M")
    out["in_first_hour"] = (times >= market_open) & (times < first_hour_end)
    return out


# ---------------------------------------------------------------------------
# Strategy 6: Mean Reversion (EMA 5/14) + Martingale position sizing
# ---------------------------------------------------------------------------


def build_indicator_frame_meanrev(
    df: pd.DataFrame, ema_fast: int = 5, ema_slow: int = 14
) -> pd.DataFrame:
    """
    Combined indicator frame for the mean-reversion strategy: EMA(5) and
    EMA(14) on close (1-min chart), plus a simple trend read from their
    relationship — ema_fast below ema_slow means the market has been
    falling ("down"), ema_fast above ema_slow means it's been rising
    ("up"). This is the "average price" reference the strategy waits for
    price to revert back to.
    """
    ema_fast_series = ema(df["close"], ema_fast)
    ema_slow_series = ema(df["close"], ema_slow)

    trend = pd.Series("none", index=df.index)
    trend[ema_fast_series < ema_slow_series] = "down"
    trend[ema_fast_series > ema_slow_series] = "up"

    out = df.copy()
    out["ema_fast"] = ema_fast_series
    out["ema_slow"] = ema_slow_series
    out["trend"] = trend
    return out


# ---------------------------------------------------------------------------
# Chapter 2 (Intraday Strategies) shared building blocks
# ---------------------------------------------------------------------------


def sma(close: pd.Series, length: int) -> pd.Series:
    return close.rolling(length).mean()


def supertrend(df: pd.DataFrame, atr_length: int = 7, mult: float = 3.0) -> pd.DataFrame:
    """
    Standard Supertrend indicator (matches "Set the ATR range to 7" in the
    2.2 write-up; multiplier isn't specified there so the usual default of
    3 is kept). Returns columns:
      - supertrend : the line value for that bar
      - trend      : 1 while price is in an uptrend (line sits below
                      price), -1 while in a downtrend (line above price)
    """
    atr_series = atr(df, length=atr_length)
    hl2 = (df["high"] + df["low"]) / 2.0
    basic_upper = hl2 + mult * atr_series
    basic_lower = hl2 - mult * atr_series

    n = len(df)
    final_upper = np.zeros(n)
    final_lower = np.zeros(n)
    st = np.zeros(n)
    trend = np.zeros(n, dtype=int)
    close = df["close"].values
    bu = basic_upper.values
    bl = basic_lower.values

    for i in range(n):
        if i == 0 or np.isnan(bu[i - 1]) or np.isnan(bl[i - 1]):
            final_upper[i] = bu[i]
            final_lower[i] = bl[i]
            trend[i] = 1
            st[i] = final_lower[i] if not np.isnan(final_lower[i]) else np.nan
            continue

        final_upper[i] = bu[i] if (bu[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]) else final_upper[i - 1]
        final_lower[i] = bl[i] if (bl[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]) else final_lower[i - 1]

        if trend[i - 1] == 1:
            trend[i] = -1 if close[i] < final_lower[i] else 1
        else:
            trend[i] = 1 if close[i] > final_upper[i] else -1

        st[i] = final_lower[i] if trend[i] == 1 else final_upper[i]

    return pd.DataFrame({"supertrend": st, "trend": trend}, index=df.index)


def daily_pivots(df: pd.DataFrame) -> pd.DataFrame:
    """
    Classic "Pivot Points Standard" levels computed from the PREVIOUS
    calendar day's High/Low/Close (the usual convention, and what
    TradingView's built-in Pivot Points Standard indicator does on an
    intraday chart) and held constant for every bar of the current day:

      P  = (H + L + C) / 3
      R1 = 2P - L        S1 = 2P - H
      R2 = P + (H - L)   S2 = P - (H - L)
      TC = (P - BC) + P  BC = (H + L) / 2      (Central Pivot Range)

    Returns columns p, r1, r2, s1, s2, cpr_tc, cpr_bc aligned to df's
    index; the first calendar day in df has no prior day and gets NaN.
    """
    dates = df.index.normalize()
    daily = df.groupby(dates).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    daily["p"] = (daily["high"] + daily["low"] + daily["close"]) / 3.0
    daily["r1"] = 2 * daily["p"] - daily["low"]
    daily["s1"] = 2 * daily["p"] - daily["high"]
    daily["r2"] = daily["p"] + (daily["high"] - daily["low"])
    daily["s2"] = daily["p"] - (daily["high"] - daily["low"])
    daily["cpr_bc"] = (daily["high"] + daily["low"]) / 2.0
    daily["cpr_tc"] = 2 * daily["p"] - daily["cpr_bc"]

    prior = daily.shift(1)[["p", "r1", "r2", "s1", "s2", "cpr_tc", "cpr_bc"]]
    prior_by_day = prior.reindex(dates)
    prior_by_day.index = df.index
    return prior_by_day


def volume_oscillator(volume: pd.Series, fast: int = 5, slow: int = 10) -> pd.Series:
    """
    Volume Oscillator: % difference between a fast and slow SMA of
    volume, matching the "Volume Osc 5 10" settings in the 2.4 write-up.
    Oscillates roughly between -30%/+30% per the book's observation.
    """
    fast_sma = volume.rolling(fast).mean()
    slow_sma = volume.rolling(slow).mean()
    return (fast_sma - slow_sma) / slow_sma.replace(0.0, np.nan) * 100.0


def fibonacci_levels(low: float, high: float) -> dict:
    """
    Standard retracement levels between a swing low and swing high
    (0%/23.6%/38.2%/50%/61.8%/78.6%/100%, measured down from the high).
    """
    rng = high - low
    return {
        "0.0": high,
        "0.236": high - 0.236 * rng,
        "0.382": high - 0.382 * rng,
        "0.5": high - 0.5 * rng,
        "0.618": high - 0.618 * rng,
        "0.786": high - 0.786 * rng,
        "1.0": low,
    }


def build_indicator_frame_ma_fib(
    df: pd.DataFrame,
    sma_length: int = 200,
    pivot_left: int = 3,
    pivot_right: int = 3,
    ma_slope_lookback: int = 5,
) -> pd.DataFrame:
    """Combined indicator frame for strategy 7 (2.1 MA + Fibonacci)."""
    sma_series = sma(df["close"], sma_length)
    pivots = find_pivots(df, left=pivot_left, right=pivot_right)
    out = df.copy()
    out["sma200"] = sma_series
    out["sma_slope"] = sma_series.diff(ma_slope_lookback)
    out["pivot_low"] = pivots["pivot_low"]
    out["pivot_high"] = pivots["pivot_high"]
    return out


def build_indicator_frame_supertrend_pivot(
    df: pd.DataFrame, atr_length: int = 7, st_mult: float = 3.0
) -> pd.DataFrame:
    """Combined indicator frame for strategy 8 (2.2 Supertrend + Pivots)."""
    st_df = supertrend(df, atr_length=atr_length, mult=st_mult)
    piv = daily_pivots(df)
    out = df.copy()
    out["supertrend"] = st_df["supertrend"]
    out["st_trend"] = st_df["trend"]
    out["r1"] = piv["r1"]
    out["s1"] = piv["s1"]
    return out


def build_indicator_frame_vwap_std(
    df: pd.DataFrame, band_mult: float = 2.0
) -> pd.DataFrame:
    """
    Combined indicator frame for strategy 9 (2.3 VWAP + Standard
    Deviations): session VWAP with only the 2-std-dev band (per "keep
    only upper band #2 and lower band #2 enabled" in the write-up).
    """
    vwap_df = session_vwap(df, band_mults=(band_mult,))
    out = df.copy()
    out["vwap"] = vwap_df["vwap"]
    m = band_mult
    out["vwap_upper"] = vwap_df[f"vwap_upper{m}"] if f"vwap_upper{m}" in vwap_df else vwap_df["vwap_upper2"]
    out["vwap_lower"] = vwap_df[f"vwap_lower{m}"] if f"vwap_lower{m}" in vwap_df else vwap_df["vwap_lower2"]
    return out


def build_indicator_frame_rsi_volosc(
    df: pd.DataFrame,
    rsi_length: int = 14,
    vo_fast: int = 5,
    vo_slow: int = 10,
    pivot_left: int = 3,
    pivot_right: int = 3,
) -> pd.DataFrame:
    """Combined indicator frame for strategy 10 (2.4 RSI + Volume Oscillator)."""
    rsi_series = rsi(df["close"], length=rsi_length)
    volume = df["volume"].fillna(0.0) if "volume" in df.columns else pd.Series(0.0, index=df.index)
    vo = volume_oscillator(volume, fast=vo_fast, slow=vo_slow)
    pivots = find_pivots(df, left=pivot_left, right=pivot_right)

    out = df.copy()
    out["rsi"] = rsi_series
    out["vol_osc"] = vo
    out["used_volume_fallback"] = bool((volume == 0).all())
    out["pivot_low"] = pivots["pivot_low"]
    out["pivot_high"] = pivots["pivot_high"]
    out["swing_low"] = df["low"].where(pivots["pivot_low"]).ffill()
    out["swing_high"] = df["high"].where(pivots["pivot_high"]).ffill()
    return out


def build_indicator_frame_pivot_pullback(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Combined indicator frame for strategy 11 (2.5 Pullback + Pivot Points)."""
    piv = daily_pivots(df)
    out = df.copy()
    for col in ("p", "r1", "r2", "s1", "s2"):
        out[col] = piv[col]
    return out


def build_indicator_frame_double_rsi(
    df: pd.DataFrame, rsi_length: int = 14
) -> pd.DataFrame:
    """
    Combined indicator frame for strategy 12 (2.6 Double RSI): RSI(14) on
    the chart's own timeframe (5-min) plus RSI(14) computed on 1-hour
    bars resampled from the same data and forward-filled back onto the
    5-min index — "an hourly timeframe RSI on a 5-minute chart", exactly
    as the write-up applies it.
    """
    rsi_fast = rsi(df["close"], length=rsi_length)

    hourly_close = df["close"].resample("1h").last().dropna()
    rsi_hourly = rsi(hourly_close, length=rsi_length)
    rsi_slow = rsi_hourly.reindex(df.index, method="ffill")

    out = df.copy()
    out["rsi_fast"] = rsi_fast
    out["rsi_slow"] = rsi_slow
    return out


def build_indicator_frame_cpr(
    df: pd.DataFrame, atr_length: int = 14, narrow_atr_mult: float = 1.0
) -> pd.DataFrame:
    """
    Combined indicator frame for strategy 13 (2.7 CPR + Trend Following):
    daily pivots/CPR plus an ATR-relative width classification —
    "narrow" (width <= narrow_atr_mult * ATR, favors breakout trades) vs
    "wide" (favors range-fade trades at support/resistance), standing in
    for the book's qualitative narrow/wide read of the CPR.
    """
    piv = daily_pivots(df)
    atr_series = atr(df, length=atr_length)
    width = (piv["cpr_tc"] - piv["cpr_bc"]).abs()

    cpr_mode = pd.Series("wide", index=df.index)
    cpr_mode[width <= narrow_atr_mult * atr_series] = "narrow"

    out = df.copy()
    for col in ("p", "r1", "r2", "s1", "s2", "cpr_tc", "cpr_bc"):
        out[col] = piv[col]
    out["cpr_width"] = width
    out["cpr_mode"] = cpr_mode
    out["atr"] = atr_series
    return out
