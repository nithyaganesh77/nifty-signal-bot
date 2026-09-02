"""
Mechanical implementation of the discretionary strategy described in the
"51 Trading Strategies" pages:

Confluences on a 3-minute chart:
  1. Heiken Ashi candle turns bullish (no lower body) / bearish (no upper body)
  2. Parabolic SAR (0.02, 0.02, 0.2) is below the candle (uptrend) / above (downtrend)
  3. RSI(14, close) is above 50 (bullish) / below 50 (bearish)

Rules (from the "TO BUY" / "TO SELL" pages):
  - When all three confluences hold on a closed candle, that candle is the
    "signal candle".
  - BUY is triggered on a move above the high of the bullish signal candle
    (mirrored: SELL on a move below the low of the bearish signal candle).
  - Stop-loss sits at the Parabolic SAR value of the signal candle.
  - Target is 1:2 risk:reward; close half the position at 1:1.

This module turns that into a small state machine driven bar-by-bar over
*closed* candles only (never a still-forming bar, to avoid repainting).
State is a plain dict so it can be JSON-serialized between polls/restarts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

# how many closed bars a setup is allowed to wait for a breakout before
# it's considered stale and dropped (20 bars * 3min = 1 hour)
SETUP_EXPIRY_BARS = 20

# after the 1:1 partial is booked, move the stop to entry (breakeven) for
# the remaining runner. Set False to keep the original SAR stop instead.
TRAIL_SL_TO_ENTRY_AFTER_PARTIAL = True


def fresh_state() -> dict:
    """
    State persisted across polls is just a dedup marker — see run()'s
    docstring for why the engine itself (phase/setup/trade) is replayed
    fresh from the indicator history every call rather than persisted.
    """
    return {"last_processed_ts": None}


def _fresh_engine_state() -> dict:
    return {"phase": "idle", "setup": None, "trade": None}


def _risk_targets(entry: float, sl: float, direction: str) -> tuple[float, float]:
    risk = abs(entry - sl)
    if direction == "long":
        return entry + risk, entry + 2 * risk  # target1 (1:1), target2 (1:2)
    else:
        return entry - risk, entry - 2 * risk


def _detect_setup(row: pd.Series) -> Optional[dict]:
    if pd.isna(row.get("sar")) or pd.isna(row.get("rsi")):
        return None

    if row["ha_color"] == "bullish" and row["sar"] < row["low"] and row["rsi"] > 50:
        trigger = row["high"]
        sl = row["sar"]
        if sl >= trigger:
            return None  # degenerate bar, skip
        t1, t2 = _risk_targets(trigger, sl, "long")
        return {
            "direction": "long",
            "signal_ts": row.name.isoformat(),
            "trigger": float(trigger),
            "sl": float(sl),
            "target1": float(t1),
            "target2": float(t2),
            "bars_waited": 0,
        }

    if row["ha_color"] == "bearish" and row["sar"] > row["high"] and row["rsi"] < 50:
        trigger = row["low"]
        sl = row["sar"]
        if sl <= trigger:
            return None
        t1, t2 = _risk_targets(trigger, sl, "short")
        return {
            "direction": "short",
            "signal_ts": row.name.isoformat(),
            "trigger": float(trigger),
            "sl": float(sl),
            "target1": float(t1),
            "target2": float(t2),
            "bars_waited": 0,
        }

    return None


def step(state: dict, row: pd.Series) -> tuple[dict, list[dict]]:
    """
    Advance the state machine by exactly one closed bar. Returns
    (new_state, events) where events is a list of dicts describing
    anything notification-worthy that happened on this bar.
    """
    events: list[dict] = []
    ts = row.name

    if state["phase"] == "idle":
        setup = _detect_setup(row)
        if setup is not None:
            state = {**state, "phase": "setup", "setup": setup}
            events.append({"type": "setup", "ts": ts, **setup})

    elif state["phase"] == "setup":
        setup = state["setup"]
        direction = setup["direction"]

        if direction == "long":
            if row["low"] <= setup["sl"]:
                events.append({"type": "setup_invalidated", "ts": ts, **setup})
                state = {**state, "phase": "idle", "setup": None}
            elif row["high"] >= setup["trigger"]:
                trade = {
                    "direction": "long",
                    "entry": setup["trigger"],
                    "sl": setup["sl"],
                    "target1": setup["target1"],
                    "target2": setup["target2"],
                    "partial_booked": False,
                    "entry_ts": ts.isoformat(),
                    "signal_ts": setup["signal_ts"],
                }
                events.append({"type": "entry", "ts": ts, **trade})
                state = {**state, "phase": "in_trade", "setup": None, "trade": trade}
        else:
            if row["high"] >= setup["sl"]:
                events.append({"type": "setup_invalidated", "ts": ts, **setup})
                state = {**state, "phase": "idle", "setup": None}
            elif row["low"] <= setup["trigger"]:
                trade = {
                    "direction": "short",
                    "entry": setup["trigger"],
                    "sl": setup["sl"],
                    "target1": setup["target1"],
                    "target2": setup["target2"],
                    "partial_booked": False,
                    "entry_ts": ts.isoformat(),
                    "signal_ts": setup["signal_ts"],
                }
                events.append({"type": "entry", "ts": ts, **trade})
                state = {**state, "phase": "in_trade", "setup": None, "trade": trade}

        if state["phase"] == "setup":
            setup["bars_waited"] += 1
            if setup["bars_waited"] >= SETUP_EXPIRY_BARS:
                events.append({"type": "setup_expired", "ts": ts, **setup})
                state = {**state, "phase": "idle", "setup": None}
            else:
                state = {**state, "setup": setup}

        # A setup that just went idle (invalidated/expired) can immediately
        # form a brand-new setup on this same bar — check once more.
        if state["phase"] == "idle":
            fresh = _detect_setup(row)
            if fresh is not None:
                state = {**state, "phase": "setup", "setup": fresh}
                events.append({"type": "setup", "ts": ts, **fresh})

    elif state["phase"] == "in_trade":
        trade = dict(state["trade"])
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
            events.append({"type": "stoploss_hit", "ts": ts, **trade, "exit_ts": ts.isoformat()})
            state = {**state, "phase": "idle", "trade": None}
        else:
            if hit_t1:
                trade["partial_booked"] = True
                if TRAIL_SL_TO_ENTRY_AFTER_PARTIAL:
                    trade["sl"] = trade["entry"]
                events.append({"type": "target1_hit", "ts": ts, **trade, "at_ts": ts.isoformat()})
            if hit_t2:
                events.append({"type": "target2_hit", "ts": ts, **trade, "exit_ts": ts.isoformat()})
                state = {**state, "phase": "idle", "trade": None}
            else:
                state = {**state, "trade": trade}

    return state, events


def simulate(indicator_df: pd.DataFrame) -> list[dict]:
    """
    Pure function: replay the whole strategy from a fresh (idle) engine
    state across every row of indicator_df, in chronological order, and
    return every event produced. Since strategy 1 has no lookahead
    (Parabolic SAR and RSI are both causal), this full replay always
    reproduces the same event for the same bar no matter how much later
    history is appended — which is what makes the dedup-by-timestamp in
    run() safe.
    """
    engine_state = _fresh_engine_state()
    all_events: list[dict] = []
    for _, row in indicator_df.iterrows():
        engine_state, events = step(engine_state, row)
        all_events.extend(events)
    return all_events


def run(state: dict, indicator_df: pd.DataFrame) -> tuple[dict, list[dict]]:
    """
    Full-history replay + dedup against state['last_processed_ts'].
    Returns (new_state, new_events) — new_events excludes anything
    already reported on a previous poll.

    On the very first call ever (no last_processed_ts yet, e.g. a brand
    new state file), the lookback window can span days of history —
    replaying that would fire a burst of stale alerts. So the first call
    seeds last_processed_ts to the latest available bar silently and
    reports no events; every call after that reports only genuinely new
    events.
    """
    if indicator_df.empty:
        return state, []

    last_ts = state.get("last_processed_ts")
    if last_ts is None:
        seed_ts = indicator_df.index[-1]
        return {**state, "last_processed_ts": seed_ts.isoformat()}, []

    all_events = simulate(indicator_df)
    cutoff = pd.Timestamp(last_ts)
    new_events = [e for e in all_events if e["ts"] > cutoff]

    if new_events:
        state = {**state, "last_processed_ts": new_events[-1]["ts"].isoformat()}

    return state, new_events
