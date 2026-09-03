"""
Mechanical implementation of the fifth strategy: "Scalping with Moving
Average" / mean-reversion off an EMA (5-minute chart, first hour only).

Rules (from the write-up):

  1. EMA(5 or 7) on close, 5-minute chart.
  2. Only trade in the FIRST HOUR of the session (9:15-10:15 IST). Skip the
     very first candle of the day (too volatile).
  3. Watch for price to move irrationally far away from the EMA in the
     first 2-3 candles WITHOUT the candle touching the EMA at all:
       - SHORT setup: a candle closes above the EMA and its low never
         touched the EMA.
       - LONG setup (mirror): a candle closes below the EMA and its high
         never touched the EMA.
     That candle is the "signal candle".
  4. Entry triggers when price breaks the signal candle's low (short) or
     high (long). Stop-loss = the signal candle's high (short) / low
     (long).
  5. "I will adjust the entries from time to time" — if a LATER candle
     (still in the first hour, still un-triggered) also qualifies as a
     signal candle in the same direction, it replaces the current one
     (usually a tighter stop). This is the `setup_updated` event below.
  6. Target: risk:reward of at least 1:3 (configurable, up to 1:4 per the
     write-up).
  7. If no entry triggers within the first hour, stand down for the day —
     "I will not execute any trades after the first hour."

Same full-history deterministic-replay design as the other strategies,
but this one resets per calendar day (a pending, un-triggered setup from
one day is dropped at the next day's open — it's a "first hour only"
strategy, not a multi-day carry). A trade already in progress is left to
play out normally (target/SL) even after the first hour ends.
"""

from __future__ import annotations

import pandas as pd

DEFAULT_TARGET_RR = 3.0  # 1:3 minimum per the write-up (can go to 1:4)


def fresh_state() -> dict:
    return {"last_sent_ts": None}


def _signal_candidate(row: pd.Series, sl_buffer: float = 0.0):
    """
    Return ("short" | "long", trigger, sl) if this row qualifies as a
    fresh signal candle, else None. trigger/sl are floats. sl_buffer
    (config.SL_BUFFER_POINTS) pushes sl further from trigger.
    """
    if pd.isna(row.get("ema")):
        return None

    is_short = row["close"] > row["ema"] and row["low"] > row["ema"]
    is_long = row["close"] < row["ema"] and row["high"] < row["ema"]

    if is_short:
        return "short", float(row["low"]), float(row["high"]) + sl_buffer
    if is_long:
        return "long", float(row["high"]), float(row["low"]) - sl_buffer
    return None


def simulate(df: pd.DataFrame, target_rr: float = DEFAULT_TARGET_RR, sl_buffer: float = 0.0) -> list[dict]:
    """
    Pure function: replay the whole strategy from an idle state across
    every row of df (must have columns from
    indicators.build_indicator_frame_ma) and return every event, in
    chronological order. Resets to idle at each new calendar day unless a
    trade is already open. Each event dict has a 'ts' key.
    """
    events: list[dict] = []
    phase = "idle"
    signal = None
    trade = None
    current_date = None

    for i in range(len(df)):
        row = df.iloc[i]
        ts = df.index[i]
        date = ts.date()

        if date != current_date:
            if phase == "setup":
                events.append({"type": "setup_expired", "ts": ts, **signal})
                phase, signal = "idle", None
            current_date = date

        if phase in ("idle", "setup"):
            if bool(row.get("in_first_hour")) and row.get("bar_index_in_day", 0) >= 1:
                candidate = _signal_candidate(row, sl_buffer=sl_buffer)
                if candidate is not None:
                    direction, trigger, sl = candidate
                    new_signal = {
                        "direction": direction,
                        "signal_ts": ts.isoformat(),
                        "trigger": trigger,
                        "sl": sl,
                    }
                    if phase == "idle":
                        signal = new_signal
                        phase = "setup"
                        events.append({"type": "setup", "ts": ts, **signal})
                    elif phase == "setup" and signal["direction"] == direction:
                        signal = new_signal
                        events.append({"type": "setup_updated", "ts": ts, **signal})

            if phase == "setup":
                direction = signal["direction"]
                if direction == "short":
                    triggered = row["low"] < signal["trigger"]
                else:
                    triggered = row["high"] > signal["trigger"]

                if triggered:
                    entry = signal["trigger"]
                    sl = signal["sl"]
                    risk = (sl - entry) if direction == "short" else (entry - sl)
                    if risk > 0:
                        target = (
                            entry - target_rr * risk
                            if direction == "short"
                            else entry + target_rr * risk
                        )
                        trade = {
                            "direction": direction,
                            "entry": float(entry),
                            "sl": float(sl),
                            "target": float(target),
                            "entry_ts": ts.isoformat(),
                            "signal_ts": signal["signal_ts"],
                        }
                        events.append({"type": "entry", "ts": ts, **trade})
                        phase, signal = "in_trade", None
                    else:
                        phase, signal = "idle", None
                elif not bool(row.get("in_first_hour")):
                    events.append({"type": "setup_expired", "ts": ts, **signal})
                    phase, signal = "idle", None

        elif phase == "in_trade":
            direction = trade["direction"]
            if direction == "short":
                hit_sl = row["high"] >= trade["sl"]
                hit_target = row["low"] <= trade["target"]
            else:
                hit_sl = row["low"] <= trade["sl"]
                hit_target = row["high"] >= trade["target"]

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
    """
    Full-history replay + dedup against state['last_sent_ts']. Same
    silent-seed-on-first-call behavior as the other strategies, to avoid
    a burst of stale alerts on a brand new state file.
    """
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
