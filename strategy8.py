"""
Mechanical implementation of the 2.2 "Ride the Trend with Supertrend"
strategy (5-minute chart, trend-following via Supertrend + Pivot Points).

Rules (from "THE STRATEGY" / "TAKE THE FOLLOWING STEPS" pages):

  TO BUY:
    1. 5-minute chart. Apply Supertrend, ATR range = 7.
    2. Apply Standard Pivot Points with only S1 and R1 enabled.
    3. Wait for price to break above R1 and stay above the Supertrend.
    4. Once both hold, wait for a bullish candle to form (the signal
       candle). BUY above the HIGH of that bullish candle — a breakout
       (stop) order, not an immediate entry.
    5. STOPLOSS may be placed below the Supertrend.
    6. TARGET is at the trader's discretion, OR exit when price closes
       below the Supertrend (the mechanical rule used here, since a
       "trader's discretion" target isn't automatable — see below).

  TO SELL: exact mirror — price breaks below S1, stays below Supertrend,
  a bearish signal candle, SELL below its low, exit on a close back above
  the Supertrend.

Since the Supertrend line itself trails with price, "stoploss below the
Supertrend" and "exit when price closes below the Supertrend" describe
the same mechanism: the trade rides the trend and is closed the moment
Supertrend flips against it (indicators.supertrend's `trend` column).
That single flip is therefore both this strategy's win and loss exit —
classified here by comparing the exit price to entry: profitable exits
are reported as target_hit, unprofitable ones as stoploss_hit, so this
still slots into the bot's usual win/loss accounting.

Two-phase idle -> setup -> in_trade state machine, same shape as
strategy7.py. Not day-scoped (a multi-day trend-following tool).
"""

from __future__ import annotations

import pandas as pd


def fresh_state() -> dict:
    return {"last_sent_ts": None}


def simulate(df: pd.DataFrame, sl_buffer: float = 0.0) -> list[dict]:
    """
    Pure function: replay the whole strategy from an idle state across
    every row of df (must have columns from
    indicators.build_indicator_frame_supertrend_pivot) and return every
    event, in chronological order. Each event dict has a 'ts' key.
    """
    events: list[dict] = []
    phase = "idle"
    setup = None
    trade = None

    for i in range(len(df)):
        row = df.iloc[i]
        ts = df.index[i]

        if phase == "idle":
            if pd.isna(row.get("supertrend")) or pd.isna(row.get("r1")) or pd.isna(row.get("s1")):
                continue

            is_bullish = row["close"] > row["open"]
            is_bearish = row["close"] < row["open"]

            if row["close"] > row["r1"] and row["st_trend"] == 1 and is_bullish:
                setup = {
                    "direction": "long",
                    "signal_ts": ts.isoformat(),
                    "trigger": float(row["high"]),
                    "sl": float(row["supertrend"]) - sl_buffer,
                }
                events.append({"type": "setup", "ts": ts, **setup})
                phase = "setup"
                continue

            if row["close"] < row["s1"] and row["st_trend"] == -1 and is_bearish:
                setup = {
                    "direction": "short",
                    "signal_ts": ts.isoformat(),
                    "trigger": float(row["low"]),
                    "sl": float(row["supertrend"]) + sl_buffer,
                }
                events.append({"type": "setup", "ts": ts, **setup})
                phase = "setup"
                continue

        elif phase == "setup":
            direction = setup["direction"]
            if direction == "long":
                if row["st_trend"] == -1:
                    events.append({"type": "setup_invalidated", "ts": ts, **setup})
                    phase, setup = "idle", None
                elif row["high"] >= setup["trigger"]:
                    entry, sl = setup["trigger"], setup["sl"]
                    if sl < entry:
                        trade = {
                            "direction": "long", "entry": float(entry), "sl": float(sl),
                            "entry_ts": ts.isoformat(), "signal_ts": setup["signal_ts"],
                        }
                        events.append({"type": "entry", "ts": ts, **trade})
                        phase, setup = "in_trade", None
                    else:
                        phase, setup = "idle", None
            else:
                if row["st_trend"] == 1:
                    events.append({"type": "setup_invalidated", "ts": ts, **setup})
                    phase, setup = "idle", None
                elif row["low"] <= setup["trigger"]:
                    entry, sl = setup["trigger"], setup["sl"]
                    if sl > entry:
                        trade = {
                            "direction": "short", "entry": float(entry), "sl": float(sl),
                            "entry_ts": ts.isoformat(), "signal_ts": setup["signal_ts"],
                        }
                        events.append({"type": "entry", "ts": ts, **trade})
                        phase, setup = "in_trade", None
                    else:
                        phase, setup = "idle", None

        elif phase == "in_trade":
            direction = trade["direction"]
            flipped = (direction == "long" and row["st_trend"] == -1) or (
                direction == "short" and row["st_trend"] == 1
            )
            if flipped:
                exit_price = float(row["close"])
                profitable = exit_price > trade["entry"] if direction == "long" else exit_price < trade["entry"]
                etype = "target_hit" if profitable else "stoploss_hit"
                events.append({"type": etype, "ts": ts, "exit_price": exit_price, **trade})
                phase, trade = "idle", None

    return events


def run(state: dict, indicator_df: pd.DataFrame, sl_buffer: float = 0.0) -> tuple[dict, list[dict]]:
    """Full-history replay + dedup — same silent-seed pattern as the other strategies."""
    if indicator_df.empty:
        return state, []

    last_ts = state.get("last_sent_ts")
    if last_ts is None:
        seed_ts = indicator_df.index[-1]
        return {**state, "last_sent_ts": seed_ts.isoformat()}, []

    all_events = simulate(indicator_df, sl_buffer=sl_buffer)
    cutoff = pd.Timestamp(last_ts)
    new_events = [e for e in all_events if e["ts"] > cutoff]

    if new_events:
        state = {**state, "last_sent_ts": new_events[-1]["ts"].isoformat()}

    return state, new_events
