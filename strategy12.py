"""
Mechanical implementation of the 2.6 "Double RSI" strategy (5-minute
chart, with a second RSI computed on 1-hour bars).

Rules (from "PURPOSE OF DOUBLE RSI" / "THE STRATEGY" pages):

  1. 5-minute chart. Apply RSI(14) (the "first RSI"). Apply a second
     RSI(14) computed on an HOURLY timeframe (the "second RSI") — filters
     noise, only shifts every couple of days.
  2. BUY signal: the first (5-min) RSI is below 30 AND the second
     (hourly) RSI is above 50 — both in tandem.
  3. SELL signal: the first RSI is above 70 AND the second RSI is below 50.
  4. "The take profit point is at the pivot of the first RSI" — i.e. the
     trade is closed once the 5-min RSI pivots back through the level
     that triggered entry (crosses back above 30 for a BUY, back below
     70 for a SELL). A hard stop-loss (the signal candle's low/high)
     protects the trade before that pivot happens.

Entry is IMMEDIATE on the qualifying candle's close (the write-up doesn't
ask for a further breakout). The RSI-pivot exit is classified as a win
(target_hit) or loss (stoploss_hit) by comparing the exit price to entry,
same convention as strategy8.py's Supertrend-flip exit — a trend/momentum
exit rather than a fixed price target, but it still needs to slot into
the bot's usual win/loss accounting.

See indicators.build_indicator_frame_double_rsi for how the hourly RSI is
computed and mapped back onto the 5-minute index.
"""

from __future__ import annotations

import pandas as pd

DEFAULT_RSI_OVERSOLD = 30.0
DEFAULT_RSI_OVERBOUGHT = 70.0


def fresh_state() -> dict:
    return {"last_sent_ts": None}


def simulate(
    df: pd.DataFrame,
    rsi_oversold: float = DEFAULT_RSI_OVERSOLD,
    rsi_overbought: float = DEFAULT_RSI_OVERBOUGHT,
    sl_buffer: float = 0.0,
) -> list[dict]:
    """
    Pure function: replay the whole strategy from an idle state across
    every row of df (must have columns from
    indicators.build_indicator_frame_double_rsi) and return every event,
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
            if pd.isna(row.get("rsi_fast")) or pd.isna(row.get("rsi_slow")):
                continue

            if row["rsi_fast"] < rsi_oversold and row["rsi_slow"] > 50:
                trade = {
                    "direction": "long", "entry": float(row["close"]), "sl": float(row["low"]) - sl_buffer,
                    "entry_ts": ts.isoformat(),
                    "rsi_fast": float(row["rsi_fast"]), "rsi_slow": float(row["rsi_slow"]),
                }
                if trade["sl"] < trade["entry"]:
                    events.append({"type": "entry", "ts": ts, **trade})
                    phase = "in_trade"
                    continue

            if row["rsi_fast"] > rsi_overbought and row["rsi_slow"] < 50:
                trade = {
                    "direction": "short", "entry": float(row["close"]), "sl": float(row["high"]) + sl_buffer,
                    "entry_ts": ts.isoformat(),
                    "rsi_fast": float(row["rsi_fast"]), "rsi_slow": float(row["rsi_slow"]),
                }
                if trade["sl"] > trade["entry"]:
                    events.append({"type": "entry", "ts": ts, **trade})
                    phase = "in_trade"
                    continue

        elif phase == "in_trade":
            direction = trade["direction"]
            if pd.isna(row.get("rsi_fast")):
                continue

            if direction == "long":
                hit_sl = row["low"] <= trade["sl"]
                pivot_exit = row["rsi_fast"] >= rsi_oversold
            else:
                hit_sl = row["high"] >= trade["sl"]
                pivot_exit = row["rsi_fast"] <= rsi_overbought

            if hit_sl:
                events.append({"type": "stoploss_hit", "ts": ts, "exit_price": float(row["low"] if direction == "long" else row["high"]), **trade})
                phase, trade = "idle", None
            elif pivot_exit:
                exit_price = float(row["close"])
                profitable = exit_price > trade["entry"] if direction == "long" else exit_price < trade["entry"]
                etype = "target_hit" if profitable else "stoploss_hit"
                events.append({"type": etype, "ts": ts, "exit_price": exit_price, **trade})
                phase, trade = "idle", None

    return events


def run(
    state: dict,
    indicator_df: pd.DataFrame,
    rsi_oversold: float = DEFAULT_RSI_OVERSOLD,
    rsi_overbought: float = DEFAULT_RSI_OVERBOUGHT,
    sl_buffer: float = 0.0,
) -> tuple[dict, list[dict]]:
    """Full-history replay + dedup — same silent-seed pattern as the other strategies."""
    if indicator_df.empty:
        return state, []

    last_ts = state.get("last_sent_ts")
    if last_ts is None:
        seed_ts = indicator_df.index[-1]
        return {**state, "last_sent_ts": seed_ts.isoformat()}, []

    all_events = simulate(
        indicator_df, rsi_oversold=rsi_oversold, rsi_overbought=rsi_overbought, sl_buffer=sl_buffer
    )
    cutoff = pd.Timestamp(last_ts)
    new_events = [e for e in all_events if e["ts"] > cutoff]

    if new_events:
        state = {**state, "last_sent_ts": new_events[-1]["ts"].isoformat()}

    return state, new_events
