"""
Mechanical implementation of the 2.7 "CPR with Trend Following" strategy
(5-minute chart, Central Pivot Range width regime).

Rules (from the two "IF THE CPR IS WIDE/NARROW" cards):

  IF THE CPR IS WIDE (range-bound regime — the CPR/pivot levels tend to
  hold and the price pivots off them):
    BUY when price takes support at a level (P/R1/R2/S1/S2/CPR).
    STOPLOSS below the buying (reversal) candle.
    TARGET at the next pivot point (trail/book there). Ideal RR 1:2.
    SELL is the exact mirror at resistance.

  IF THE CPR IS NARROW (trending/breakout regime — levels tend to give
  way and the move continues):
    BUY when price breaks any level from below.
    STOPLOSS below the breakout candle.
    TARGET trailed until the market reverses; ideal RR 1:2 used here as
    the mechanical target (see below).
    SELL is the exact mirror on a breakdown below a level.

Both modes use IMMEDIATE entry (the write-up doesn't ask for a further
breakout of the signal candle in either case) — this is really the same
underlying idea as strategy11.py's pivot-pullback (wide/range-fade half)
and strategy4.py's range-breakout (narrow/breakout half), just gated by
the CPR-width regime for the day (indicators.build_indicator_frame_cpr).
"Trail it until market reverses" for the narrow case isn't mechanical, so
a fixed 1:2 Risk:Reward target is used there, same as the wide case's
fallback when no further pivot level exists.
"""

from __future__ import annotations

import pandas as pd

DEFAULT_TARGET_RR = 2.0
_LEVEL_COLS = ("s2", "s1", "p", "r1", "r2", "cpr_bc", "cpr_tc")


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


def _broken_level(prev_close: float, row: pd.Series, levels: list[float]):
    """Return (level, 'up'|'down') if this candle's close crossed a level
    that the previous candle's close was on the other side of."""
    for lvl in levels:
        if prev_close < lvl <= row["close"]:
            return lvl, "up"
        if prev_close > lvl >= row["close"]:
            return lvl, "down"
    return None, None


def simulate(df: pd.DataFrame, target_rr: float = DEFAULT_TARGET_RR, sl_buffer: float = 0.0) -> list[dict]:
    """
    Pure function: replay the whole strategy from an idle state across
    every row of df (must have columns from
    indicators.build_indicator_frame_cpr) and return every event, in
    chronological order. idle -> in_trade (immediate entry, no setup
    stage). Each event dict has a 'ts' key.
    """
    events: list[dict] = []
    phase = "idle"
    trade = None
    prev_close = None

    for i in range(len(df)):
        row = df.iloc[i]
        ts = df.index[i]

        if phase == "idle":
            levels = _levels(row)
            mode = row.get("cpr_mode")
            if len(levels) >= 2 and mode in ("wide", "narrow"):
                is_bullish = row["close"] > row["open"]
                is_bearish = row["close"] < row["open"]

                if mode == "wide":
                    lvl = _touched_level(row, levels)
                    if lvl is not None:
                        if is_bullish and row["close"] > lvl:
                            entry, sl = float(row["close"]), float(row["low"]) - sl_buffer
                            if sl < entry:
                                higher = [l for l in levels if l > entry]
                                target = min(higher) if higher else entry + target_rr * (entry - sl)
                                trade = {
                                    "direction": "long", "entry": entry, "sl": sl, "target": float(target),
                                    "cpr_mode": mode, "level": float(lvl), "entry_ts": ts.isoformat(),
                                }
                                events.append({"type": "entry", "ts": ts, **trade})
                                phase = "in_trade"
                        elif is_bearish and row["close"] < lvl:
                            entry, sl = float(row["close"]), float(row["high"]) + sl_buffer
                            if sl > entry:
                                lower = [l for l in levels if l < entry]
                                target = max(lower) if lower else entry - target_rr * (sl - entry)
                                trade = {
                                    "direction": "short", "entry": entry, "sl": sl, "target": float(target),
                                    "cpr_mode": mode, "level": float(lvl), "entry_ts": ts.isoformat(),
                                }
                                events.append({"type": "entry", "ts": ts, **trade})
                                phase = "in_trade"

                elif mode == "narrow" and prev_close is not None:
                    lvl, direction = _broken_level(prev_close, row, levels)
                    if lvl is not None and direction == "up":
                        entry, sl = float(row["close"]), float(row["low"]) - sl_buffer
                        if sl < entry:
                            target = entry + target_rr * (entry - sl)
                            trade = {
                                "direction": "long", "entry": entry, "sl": sl, "target": float(target),
                                "cpr_mode": mode, "level": float(lvl), "entry_ts": ts.isoformat(),
                            }
                            events.append({"type": "entry", "ts": ts, **trade})
                            phase = "in_trade"
                    elif lvl is not None and direction == "down":
                        entry, sl = float(row["close"]), float(row["high"]) + sl_buffer
                        if sl > entry:
                            target = entry - target_rr * (sl - entry)
                            trade = {
                                "direction": "short", "entry": entry, "sl": sl, "target": float(target),
                                "cpr_mode": mode, "level": float(lvl), "entry_ts": ts.isoformat(),
                            }
                            events.append({"type": "entry", "ts": ts, **trade})
                            phase = "in_trade"

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

        prev_close = float(row["close"])

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
