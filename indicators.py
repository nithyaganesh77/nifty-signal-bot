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
