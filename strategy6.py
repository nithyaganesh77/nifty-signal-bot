"""
Mechanical implementation of the sixth strategy: Mean Reversion with
EMA(5) and EMA(14), combined with a Martingale position-sizing overlay
(1-minute chart).

Entry rules (from the "TO BUY" / "TO SELL" pages):

  TO BUY:
    1. Apply EMA(5) and EMA(14) on close, 1-minute chart.
    2. Look for a downward move (EMA(5) below EMA(14) — price has pulled
       away from its average) and wait until the market gives a bullish
       reversal sign (a bullish/green candle).
    3. BUY at the high of that bullish reversal candle.
    4. STOPLOSS at the low of the bullish candle. TARGET at a 1:1
       risk:reward.

  TO SELL (mirror): uptrend (EMA(5) above EMA(14)), bearish reversal
  candle, SELL at its low, STOPLOSS at its high, TARGET 1:1.

Same setup -> entry -> target/SL state machine as strategy.py / strategy3.py.

Martingale position sizing (the "5.6 Martingale System" half of the
write-up) isn't a signal-detection rule — it's a bet-sizing overlay on
TOP of a fixed-R:R system like this one ("the size of the winning bet
exceeds the combined losses of all previous trades" only works cleanly
at a 1:1 R:R, which is exactly this strategy's target). Since this
signal bot doesn't place orders or track capital, the martingale
sequence is applied as a *suggested position-size multiplier* attached
to each Telegram alert (see apply_martingale() in main.py): it starts at
1x, doubles after every stop-loss (capped at MARTINGALE_MAX_MULTIPLIER),
and resets to 1x after every target hit — mirroring "put net profit
aside" in the write-up.
"""

from __future__ import annotations

import pandas as pd

# how many closed bars a setup is allowed to wait for a breakout before
# it's considered stale and dropped
SETUP_EXPIRY_BARS = 20
DEFAULT_TARGET_RR = 1.0  # "average Risk to Reward ratio is 1:1"


def fresh_state() -> dict:
    return {"last_sent_ts": None}


def _detect_setup(row: pd.Series, sl_buffer: float = 0.0) -> dict | None:
    if pd.isna(row.get("ema_fast")) or pd.isna(row.get("ema_slow")):
        return None

    is_bullish = row["close"] > row["open"]
    is_bearish = row["close"] < row["open"]

    if row.get("trend") == "down" and is_bullish:
        trigger = row["high"]
        sl = row["low"] - sl_buffer
        if sl >= trigger:
            return None
        return {
            "direction": "long",
            "signal_ts": row.name.isoformat(),
            "trigger": float(trigger),
            "sl": float(sl),
            "bars_waited": 0,
        }

    if row.get("trend") == "up" and is_bearish:
        trigger = row["low"]
        sl = row["high"] + sl_buffer
        if sl <= trigger:
            return None
        return {
            "direction": "short",
            "signal_ts": row.name.isoformat(),
            "trigger": float(trigger),
            "sl": float(sl),
            "bars_waited": 0,
        }

    return None


def simulate(df: pd.DataFrame, target_rr: float = DEFAULT_TARGET_RR, sl_buffer: float = 0.0) -> list[dict]:
    """
    Pure function: replay the whole strategy from an idle state across
    every row of df (must have columns from
    indicators.build_indicator_frame_meanrev) and return every event, in
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
            found = _detect_setup(row, sl_buffer=sl_buffer)
            if found is not None:
                setup = found
                phase = "setup"
                events.append({"type": "setup", "ts": ts, **found})

        elif phase == "setup":
            direction = setup["direction"]
            if direction == "long":
                invalidated = row["low"] <= setup["sl"]
                triggered = row["high"] >= setup["trigger"]
            else:
                invalidated = row["high"] >= setup["sl"]
                triggered = row["low"] <= setup["trigger"]

            if invalidated:
                events.append({"type": "setup_invalidated", "ts": ts, **setup})
                phase, setup = "idle", None
            elif triggered:
                entry = setup["trigger"]
                sl = setup["sl"]
                risk = (entry - sl) if direction == "long" else (sl - entry)
                target = entry + target_rr * risk if direction == "long" else entry - target_rr * risk
                trade = {
                    "direction": direction,
                    "entry": float(entry),
                    "sl": float(sl),
                    "target": float(target),
                    "entry_ts": ts.isoformat(),
                    "signal_ts": setup["signal_ts"],
                }
                events.append({"type": "entry", "ts": ts, **trade})
                phase, setup = "in_trade", None
            else:
                setup["bars_waited"] += 1
                if setup["bars_waited"] >= SETUP_EXPIRY_BARS:
                    events.append({"type": "setup_expired", "ts": ts, **setup})
                    phase, setup = "idle", None

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
    """
    Full-history replay + dedup against state['last_sent_ts']. Same
    silent-seed-on-first-call behavior as the other strategies.
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
