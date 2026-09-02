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
