"""
Mechanical implementation of the 2.4 "Buy/Sell with RSI and Volume
Oscillator" strategy (5-minute chart).

Rules (from "TAKE THE FOLLOWING STEPS" / the TO BUY card):

  1. 5-minute chart. Apply RSI(14) and Volume Oscillator(5, 10).
  2. Watch out for RSI and the Volume Oscillator to be in tandem at the
     dip: BUY entry triggers when the Volume Oscillator is near the -30%
     level AND the RSI is near the 30 level — both in their oversold zone
     together, on the same candle.
  3. STOPLOSS is placed at the swing low.
  4. The strategy's conservative Risk:Reward ratio is 1:2.

  TO SELL: exact mirror — Volume Oscillator near +30%, RSI near 70 (both
  overbought together). STOPLOSS at the swing high. Same 1:2 RR.

Unlike the Fibonacci/Supertrend/VWAP strategies in this chapter, the
write-up doesn't ask for a further breakout above/below the signal
candle — entry is IMMEDIATE on the qualifying candle's close, same shape
as strategies 2/3/10. "Swing low/high" is the most recent confirmed
pivot (indicators.find_pivots), forward-filled — see
indicators.build_indicator_frame_rsi_volosc.

Caveat: the Volume Oscillator needs real traded volume. Index tickers
(e.g. ^NSEI) typically report zero volume on free feeds, in which case
vol_osc is always 0 and this strategy will rarely (if ever) fire on that
symbol — main.py logs a one-time warning, same as strategy3's VWAP
volume fallback.
"""

from __future__ import annotations

import pandas as pd

DEFAULT_TARGET_RR = 2.0
DEFAULT_RSI_OVERSOLD = 30.0
DEFAULT_RSI_OVERBOUGHT = 70.0
DEFAULT_VO_OVERSOLD = -30.0
DEFAULT_VO_OVERBOUGHT = 30.0


def fresh_state() -> dict:
    return {"last_sent_ts": None}


def simulate(
    df: pd.DataFrame,
    target_rr: float = DEFAULT_TARGET_RR,
    rsi_oversold: float = DEFAULT_RSI_OVERSOLD,
    rsi_overbought: float = DEFAULT_RSI_OVERBOUGHT,
    vo_oversold: float = DEFAULT_VO_OVERSOLD,
    vo_overbought: float = DEFAULT_VO_OVERBOUGHT,
) -> list[dict]:
    """
    Pure function: replay the whole strategy from an idle state across
    every row of df (must have columns from
    indicators.build_indicator_frame_rsi_volosc) and return every event,
    in chronological order. idle -> in_trade (immediate entry, no setup
    stage). Each event dict has a 'ts' key.
    """
    events: list[dict] = []
    phase = "idle"
    trade = None

    for i in range(len(df)):
        row = df.iloc[i]
        ts = df.index[i]

        if phase == "idle":
            if pd.isna(row.get("rsi")) or pd.isna(row.get("vol_osc")):
                continue

            if row["rsi"] <= rsi_oversold and row["vol_osc"] <= vo_oversold:
                sl = row.get("swing_low")
                entry = row["close"]
                if sl is not None and not pd.isna(sl) and sl < entry:
                    risk = entry - sl
                    target = entry + target_rr * risk
                    trade = {
                        "direction": "long", "entry": float(entry), "sl": float(sl),
                        "target": float(target), "entry_ts": ts.isoformat(),
                        "rsi": float(row["rsi"]), "vol_osc": float(row["vol_osc"]),
                    }
                    events.append({"type": "entry", "ts": ts, **trade})
                    phase = "in_trade"
                    continue

            if row["rsi"] >= rsi_overbought and row["vol_osc"] >= vo_overbought:
                sl = row.get("swing_high")
                entry = row["close"]
                if sl is not None and not pd.isna(sl) and sl > entry:
                    risk = sl - entry
                    target = entry - target_rr * risk
                    trade = {
                        "direction": "short", "entry": float(entry), "sl": float(sl),
                        "target": float(target), "entry_ts": ts.isoformat(),
                        "rsi": float(row["rsi"]), "vol_osc": float(row["vol_osc"]),
                    }
                    events.append({"type": "entry", "ts": ts, **trade})
                    phase = "in_trade"
                    continue

        elif phase == "in_trade":
            direction = trade["direction"]
            if direction == "long":
                hit_sl = row["low"] <= trade["sl"]
                hit_target = row["high"] >= trade["target"]
            else:
                hit_sl = row["high"] >= trade["sl"]
                hit_target = row["low"] <= trade["target"]

            if hit_sl:
                events.append({"type": "stoploss_hit", "ts": ts, **trade})
                phase, trade = "idle", None
            elif hit_target:
                events.append({"type": "target_hit", "ts": ts, **trade})
                phase, trade = "idle", None

    return events


def run(
    state: dict,
    indicator_df: pd.DataFrame,
    target_rr: float = DEFAULT_TARGET_RR,
    rsi_oversold: float = DEFAULT_RSI_OVERSOLD,
    rsi_overbought: float = DEFAULT_RSI_OVERBOUGHT,
    vo_oversold: float = DEFAULT_VO_OVERSOLD,
    vo_overbought: float = DEFAULT_VO_OVERBOUGHT,
) -> tuple[dict, list[dict]]:
    """Full-history replay + dedup — same silent-seed pattern as the other strategies."""
    if indicator_df.empty:
        return state, []

    last_ts = state.get("last_sent_ts")
    if last_ts is None:
        seed_ts = indicator_df.index[-1]
        return {**state, "last_sent_ts": seed_ts.isoformat()}, []

    all_events = simulate(
        indicator_df, target_rr=target_rr, rsi_oversold=rsi_oversold,
        rsi_overbought=rsi_overbought, vo_oversold=vo_oversold, vo_overbought=vo_overbought,
    )
    cutoff = pd.Timestamp(last_ts)
    new_events = [e for e in all_events if e["ts"] > cutoff]

    if new_events:
        state = {**state, "last_sent_ts": new_events[-1]["ts"].isoformat()}

    return state, new_events
