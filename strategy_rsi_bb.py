"""
Mechanical implementation of the second strategy: "RSI Divergence +
Bollinger Bands Scalping Strategy" (1-minute chart).

Rules (from the "TO BUY" / "TO SELL" pages):

  TO BUY:
    1. Apply Bollinger Bands (20, close, mult 2) and RSI(14) on a 1-min chart.
    2. Wait for price to form lower lows near/at the lower Bollinger Band.
    3. If RSI is NOT reciprocating (RSI makes a higher low while price makes
       a lower low) -> bullish divergence.
    4. BUY entry is triggered when price makes a green candle after the
       fall (immediate entry — the write-up does NOT ask for a further
       breakout above that candle, unlike strategy 1's "buy above the high
       of the bullish candle"). Stop-loss below the low of that green
       candle. Target at the (upper) Bollinger Band.

  TO SELL (mirror):
    1. Same indicators.
    2. Wait for price to cross the upper Bollinger Band and form higher highs.
    3. If RSI makes a lower high while price makes a higher high -> bearish
       divergence.
    4. SELL entry is triggered immediately when price makes a red candle
       after the rise. Stop-loss above the high of that red candle. Target
       at the (lower) Bollinger Band.

Unlike strategy 1 (Heiken Ashi + SAR + RSI), this strategy's write-up
doesn't mention a partial 1:1 exit — it's a single stop-loss / single
target trade, so that's what's implemented here.

Because a pivot only gets *confirmed* a few bars after it actually forms
(same as TradingView's Pivot High/Low — see indicators.find_pivots), this
is implemented as a deterministic full-history replay rather than a
streaming step() like strategy.py: given the same indicator dataframe, the
resulting event sequence up to any point in time never changes as new bars
are appended (pivot confirmation never revises past bars), so re-running
the whole replay every poll and only sending genuinely new events (by
timestamp) is simple and safe.
"""

from __future__ import annotations

import pandas as pd

# how many bars (each direction) must confirm a swing point — matches
# indicators.find_pivots' left/right window
PIVOT_LEFT = 3
PIVOT_RIGHT = 3

# once a divergence is flagged, how many bars we'll wait for the
# green/red reversal candle before giving up (15 bars * 1min = 15 minutes)
REVERSAL_WAIT_BARS = 15


def simulate(df: pd.DataFrame, sl_buffer: float = 0.0) -> list[dict]:
    """
    Replay the full strategy over an indicator dataframe (must have
    columns: open, high, low, close, rsi, bb_upper, bb_lower, pivot_low,
    pivot_high — see indicators.build_indicator_frame_bb) and return every
    event that occurred, in chronological order. Each event dict has a
    'ts' (pandas Timestamp) key for ordering/dedup by the caller.
    sl_buffer (config.SL_BUFFER_POINTS) pushes the stop-loss this many
    points further from entry, to absorb ordinary noise.
    """
    events: list[dict] = []

    last_piv_low = None  # {"price":, "rsi":}
    last_piv_high = None

    phase = "idle"  # idle | pending | in_trade
    pending = None
    trade = None

    n = len(df)
    for i in range(n):
        row = df.iloc[i]
        ts = df.index[i]

        if pd.isna(row.get("rsi")) or pd.isna(row.get("bb_upper")) or pd.isna(row.get("bb_lower")):
            continue

        # --- 1. pivot bookkeeping + divergence detection -------------------
        if bool(row.get("pivot_low")):
            if (
                phase == "idle"
                and last_piv_low is not None
                and row["low"] < last_piv_low["price"]
                and row["rsi"] > last_piv_low["rsi"]
                and row["low"] <= row["bb_lower"]
            ):
                pending = {"direction": "long", "since_idx": i, "pivot_ts": ts.isoformat()}
                phase = "pending"
                events.append(
                    {
                        "type": "divergence",
                        "ts": ts,
                        "direction": "long",
                        "price": float(row["low"]),
                        "rsi": float(row["rsi"]),
                    }
                )
            last_piv_low = {"price": float(row["low"]), "rsi": float(row["rsi"])}

        if bool(row.get("pivot_high")):
            if (
                phase == "idle"
                and last_piv_high is not None
                and row["high"] > last_piv_high["price"]
                and row["rsi"] < last_piv_high["rsi"]
                and row["high"] >= row["bb_upper"]
            ):
                pending = {"direction": "short", "since_idx": i, "pivot_ts": ts.isoformat()}
                phase = "pending"
                events.append(
                    {
                        "type": "divergence",
                        "ts": ts,
                        "direction": "short",
                        "price": float(row["high"]),
                        "rsi": float(row["rsi"]),
                    }
                )
            last_piv_high = {"price": float(row["high"]), "rsi": float(row["rsi"])}

        # --- 2/3/4. state machine on the (possibly just-updated) phase -----
        # Entry is IMMEDIATE on the reversal candle (per the write-up: "BUY
        # entry is triggered when the price makes a green candle" — no
        # further breakout confirmation like strategy 1's "above the high").
        if phase == "pending":
            bars_since = i - pending["since_idx"]
            is_reversal = (
                row["close"] > row["open"]
                if pending["direction"] == "long"
                else row["close"] < row["open"]
            )
            if is_reversal:
                direction = pending["direction"]
                if direction == "long":
                    entry, sl, target = row["close"], row["low"] - sl_buffer, row["bb_upper"]
                    valid = target > entry and sl < entry
                else:
                    entry, sl, target = row["close"], row["high"] + sl_buffer, row["bb_lower"]
                    valid = target < entry and sl > entry

                if valid:
                    trade = {
                        "direction": direction,
                        "entry": float(entry),
                        "sl": float(sl),
                        "target": float(target),
                        "entry_ts": ts.isoformat(),
                        "signal_ts": pending["pivot_ts"],
                    }
                    events.append({"type": "entry", "ts": ts, **trade})
                    phase, pending = "in_trade", None
                else:
                    phase, pending = "idle", None
            elif bars_since >= REVERSAL_WAIT_BARS:
                events.append(
                    {"type": "divergence_expired", "ts": ts, "direction": pending["direction"]}
                )
                phase, pending = "idle", None

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


def fresh_state() -> dict:
    return {"last_sent_ts": None}


def run(state: dict, indicator_df: pd.DataFrame, sl_buffer: float = 0.0) -> tuple[dict, list[dict]]:
    """
    Full-history replay + dedup against state['last_sent_ts']. Returns
    (new_state, new_events) — new_events excludes anything already sent
    on a previous poll.

    On the very first call ever (no last_sent_ts yet, e.g. a brand new
    state file), the lookback window can span days of history — replaying
    that would fire a burst of stale alerts. So the first call seeds
    last_sent_ts to the latest available bar silently and reports no
    events; every call after that reports only genuinely new events.
    """
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
