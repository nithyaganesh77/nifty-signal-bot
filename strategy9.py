"""
Mechanical implementation of the 2.3 "Analyzing Pivot Points Using VWAP
and Standard Deviations" strategy (5-minute chart).

Rules (from "THE STRATEGY" / "TAKE THE FOLLOWING STEPS" pages):

  TO BUY:
    1. 5-minute chart. Apply session VWAP (hlc3), keep only the upper and
       lower band #2 (2 standard deviations) enabled.
    2. Price closing below the lower band = the oversold zone; price
       pivots back from there.
    3. Wait for a bullish (green) reversal candle to form at/through the
       lower band. BUY above the HIGH of that green candle (breakout).
    4. STOPLOSS below the low of the green candle.
    5. TARGET 1 at the VWAP line, TARGET 2 at the upper band — the same
       partial-booking, two-target shape as strategy 1 (book half at
       target 1, move stop to breakeven, ride the rest to target 2).
       Preferred minimum Risk:Reward is 1:2.

  TO SELL: exact mirror — price closes above the upper band (overbought),
  a bearish reversal candle forms, SELL below its low, STOPLOSS above its
  high, TARGET 1 at VWAP, TARGET 2 at the lower band.

VWAP/band values drift every bar, so target1/target2 are frozen at the
values current when the trade actually enters (not the signal candle),
same convention as strategy3.py freezing the VWAP band at the signal.

Two-phase idle -> setup -> in_trade, target1/target2 partial-exit
mechanics identical in shape to strategy.py (strategy 1). Not day-scoped.
"""

from __future__ import annotations

import pandas as pd

TRAIL_SL_TO_ENTRY_AFTER_PARTIAL = True


def fresh_state() -> dict:
    return {"last_sent_ts": None}


def simulate(df: pd.DataFrame) -> list[dict]:
    """
    Pure function: replay the whole strategy from an idle state across
    every row of df (must have columns from
    indicators.build_indicator_frame_vwap_std) and return every event, in
    chronological order. Each event dict has a 'ts' key.
    """
    events: list[dict] = []
    phase = "idle"
    setup = None
    trade = None

    for i in range(len(df)):
        row = df.iloc[i]
        ts = df.index[i]

        if phase == "idle":
            if pd.isna(row.get("vwap")) or pd.isna(row.get("vwap_upper")) or pd.isna(row.get("vwap_lower")):
                continue

            is_bullish = row["close"] > row["open"]
            is_bearish = row["close"] < row["open"]

            if row["low"] <= row["vwap_lower"] and row["close"] > row["vwap_lower"] and is_bullish:
                setup = {
                    "direction": "long",
                    "signal_ts": ts.isoformat(),
                    "trigger": float(row["high"]),
                    "sl": float(row["low"]),
                }
                events.append({"type": "setup", "ts": ts, **setup})
                phase = "setup"
                continue

            if row["high"] >= row["vwap_upper"] and row["close"] < row["vwap_upper"] and is_bearish:
                setup = {
                    "direction": "short",
                    "signal_ts": ts.isoformat(),
                    "trigger": float(row["low"]),
                    "sl": float(row["high"]),
                }
                events.append({"type": "setup", "ts": ts, **setup})
                phase = "setup"
                continue

        elif phase == "setup":
            direction = setup["direction"]
            if direction == "long":
                if row["low"] <= setup["sl"]:
                    events.append({"type": "setup_invalidated", "ts": ts, **setup})
                    phase, setup = "idle", None
                elif row["high"] >= setup["trigger"]:
                    entry, sl = setup["trigger"], setup["sl"]
                    if sl < entry and row["vwap"] > entry:
                        trade = {
                            "direction": "long", "entry": float(entry), "sl": float(sl),
                            "target1": float(row["vwap"]), "target2": float(row["vwap_upper"]),
                            "partial_booked": False,
                            "entry_ts": ts.isoformat(), "signal_ts": setup["signal_ts"],
                        }
                        events.append({"type": "entry", "ts": ts, **trade})
                        phase, setup = "in_trade", None
                    else:
                        phase, setup = "idle", None
            else:
                if row["high"] >= setup["sl"]:
                    events.append({"type": "setup_invalidated", "ts": ts, **setup})
                    phase, setup = "idle", None
                elif row["low"] <= setup["trigger"]:
                    entry, sl = setup["trigger"], setup["sl"]
                    if sl > entry and row["vwap"] < entry:
                        trade = {
                            "direction": "short", "entry": float(entry), "sl": float(sl),
                            "target1": float(row["vwap"]), "target2": float(row["vwap_lower"]),
                            "partial_booked": False,
                            "entry_ts": ts.isoformat(), "signal_ts": setup["signal_ts"],
                        }
                        events.append({"type": "entry", "ts": ts, **trade})
                        phase, setup = "in_trade", None
                    else:
                        phase, setup = "idle", None

        elif phase == "in_trade":
            direction = trade["direction"]
            if direction == "long":
                hit_sl = row["low"] <= trade["sl"]
                hit_t1 = (not trade["partial_booked"]) and row["high"] >= trade["target1"]
                hit_t2 = row["high"] >= trade["target2"]
            else:
                hit_sl = row["high"] >= trade["sl"]
                hit_t1 = (not trade["partial_booked"]) and row["low"] <= trade["target1"]
                hit_t2 = row["low"] <= trade["target2"]

            if hit_sl:
                events.append({"type": "stoploss_hit", "ts": ts, **trade})
                phase, trade = "idle", None
            else:
                if hit_t1:
                    trade["partial_booked"] = True
                    if TRAIL_SL_TO_ENTRY_AFTER_PARTIAL:
                        trade["sl"] = trade["entry"]
                    events.append({"type": "target1_hit", "ts": ts, **trade})
                if hit_t2:
                    events.append({"type": "target2_hit", "ts": ts, **trade})
                    phase, trade = "idle", None

    return events


def run(state: dict, indicator_df: pd.DataFrame) -> tuple[dict, list[dict]]:
    """Full-history replay + dedup — same silent-seed pattern as the other strategies."""
    if indicator_df.empty:
        return state, []

    last_ts = state.get("last_sent_ts")
    if last_ts is None:
        seed_ts = indicator_df.index[-1]
        return {**state, "last_sent_ts": seed_ts.isoformat()}, []

    all_events = simulate(indicator_df)
    cutoff = pd.Timestamp(last_ts)
    new_events = [e for e in all_events if e["ts"] > cutoff]

    if new_events:
        state = {**state, "last_sent_ts": new_events[-1]["ts"].isoformat()}

    return state, new_events
