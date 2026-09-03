"""
Mechanical implementation of the 2.5 "Wait and Trade the Pullback"
strategy (5-minute chart, Standard Pivot Points).

Rules (from "TAKE THE FOLLOWING STEPS" / the TO BUY card):

  1. 5-minute chart. Apply Pivot Points Standard (default settings: P,
     R1, R2, S1, S2).
  2. Wait for price to hover around a pivot level and pull back to it —
     either without breaking it (a reversal off support/resistance) or
     just after breaking it (a trend-continuation retest). Both resolve
     the same mechanical way in the write-up, so both are treated
     uniformly here.
  3. BUY entry triggers when a bullish candle forms and closes back above
     the level after the pullback. STOPLOSS at the low of that candle.
  4. TARGET is the very next pivot level above entry — the write-up notes
     this alone often works out to roughly 1:4, though it's whatever the
     next level actually is, not a fixed ratio. If there's no higher
     level left in the day's pivot ladder, falls back to a fixed
     Risk:Reward (TARGET_RR_11 in config.py).

  TO SELL: exact mirror — a bearish candle closes back below a pivot
  level, STOPLOSS at the high of that candle, TARGET at the next pivot
  level below entry (or the RR fallback).

Entry is IMMEDIATE on the qualifying candle's close — the write-up
doesn't ask for a further breakout of this candle, unlike the
Fibonacci/Supertrend/VWAP strategies elsewhere in this chapter. Not
day-scoped (pivot levels are already fixed per calendar day by
indicators.daily_pivots).
"""

from __future__ import annotations

import pandas as pd

DEFAULT_TARGET_RR = 2.0  # fallback only, when no further pivot level exists
_LEVEL_COLS = ("s2", "s1", "p", "r1", "r2")


def fresh_state() -> dict:
    return {"last_sent_ts": None}


def _levels(row: pd.Series) -> list[float]:
    vals = [row.get(c) for c in _LEVEL_COLS]
    return sorted(v for v in vals if v is not None and not pd.isna(v))


def _touched_level(row: pd.Series, levels: list[float]) -> float | None:
    for lvl in levels:
        if row["low"] <= lvl <= row["high"]:
            return lvl
    return None


def simulate(df: pd.DataFrame, target_rr: float = DEFAULT_TARGET_RR, sl_buffer: float = 0.0) -> list[dict]:
    """
    Pure function: replay the whole strategy from an idle state across
    every row of df (must have columns from
    indicators.build_indicator_frame_pivot_pullback) and return every
    event, in chronological order. idle -> in_trade (immediate entry, no
    setup stage). Each event dict has a 'ts' key.
    """
    events: list[dict] = []
    phase = "idle"
    trade = None

    for i in range(len(df)):
        row = df.iloc[i]
        ts = df.index[i]

        if phase == "idle":
            levels = _levels(row)
            if len(levels) < 2:
                continue
            lvl = _touched_level(row, levels)
            if lvl is None:
                continue

            is_bullish = row["close"] > row["open"]
            is_bearish = row["close"] < row["open"]

            if is_bullish and row["close"] > lvl:
                entry, sl = float(row["close"]), float(row["low"]) - sl_buffer
                if sl < entry:
                    higher = [l for l in levels if l > entry]
                    target = min(higher) if higher else entry + target_rr * (entry - sl)
                    trade = {
                        "direction": "long", "entry": entry, "sl": sl, "target": float(target),
                        "pivot_level": float(lvl), "entry_ts": ts.isoformat(),
                    }
                    events.append({"type": "entry", "ts": ts, **trade})
                    phase = "in_trade"
                    continue

            if is_bearish and row["close"] < lvl:
                entry, sl = float(row["close"]), float(row["high"]) + sl_buffer
                if sl > entry:
                    lower = [l for l in levels if l < entry]
                    target = max(lower) if lower else entry - target_rr * (sl - entry)
                    trade = {
                        "direction": "short", "entry": entry, "sl": sl, "target": float(target),
                        "pivot_level": float(lvl), "entry_ts": ts.isoformat(),
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
    sl_buffer: float = 0.0,
) -> tuple[dict, list[dict]]:
    """Full-history replay + dedup — same silent-seed pattern as the other strategies."""
    if indicator_df.empty:
        return state, []

    last_ts = state.get("last_sent_ts")
    if last_ts is None:
        seed_ts = indicator_df.index[-1]
        return {**state, "last_sent_ts": seed_ts.isoformat()}, []

    all_events = simulate(indicator_df, target_rr=target_rr, sl_buffer=sl_buffer)
    cutoff = pd.Timestamp(last_ts)
    new_events = [e for e in all_events if e["ts"] > cutoff]

    if new_events:
        state = {**state, "last_sent_ts": new_events[-1]["ts"].isoformat()}

    return state, new_events
