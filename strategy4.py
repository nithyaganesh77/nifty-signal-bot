"""
Mechanical implementation of the fourth strategy: "Scalping 1 Minute
Consolidation Breakouts" (1-minute chart).

Rules (from the "5 rules" page):
  1. Identify the pre-established trend — only trade with it.
  2. Once trend is established, wait for the next 4-5 candles to form a
     tight range (small bodies with wicks — a consolidation).
  3. Bullish trend: buy when a candle breaks the high of the range.
     Bearish trend: sell when a candle breaks the low of the range.
  4. Minimum target of 1:3, stop-loss above/below the breakout/breakdown
     candle (below it for a buy, above it for a sell).
  5. Close the trade after 10 minutes regardless of target/SL.

Unlike strategies 1-3, entry here is immediate: the breakout candle
itself (the one whose close clears the range) IS the entry, not a
separate "wait for a further breakout of this candle's high" stage — so
the state machine is simpler: idle -> in_trade, with a hard time-based
exit added on top of the usual target/stop-loss checks.

"Small candle bodies with wicks" (a tight range) is approximated here as
range_width <= CONSOLIDATION_MAX_ATR_MULT * ATR — adaptive to recent
volatility rather than a fixed price threshold. See
indicators.build_indicator_frame_consolidation for trend/range/ATR.
"""

from __future__ import annotations

import pandas as pd

# how "tight" the preceding range must be, relative to ATR, to count as
# a consolidation rather than just a slice of a trending move
CONSOLIDATION_MAX_ATR_MULT = 1.5


def fresh_state() -> dict:
    return {"last_sent_ts": None}


def simulate(
    df: pd.DataFrame,
    target_rr: float = 3.0,
    time_exit_bars: int = 10,
    max_atr_mult: float = CONSOLIDATION_MAX_ATR_MULT,
) -> list[dict]:
    """
    Pure function: replay the whole strategy from an idle state across
    every row of df (must have columns from
    indicators.build_indicator_frame_consolidation) and return every
    event, in chronological order. Each event dict has a 'ts' key for
    ordering/dedup by the caller.
    """
    events: list[dict] = []
    phase = "idle"
    trade = None

    for i in range(len(df)):
        row = df.iloc[i]
        ts = df.index[i]

        if phase == "idle":
            if (
                not pd.isna(row.get("atr"))
                and not pd.isna(row.get("range_high"))
                and not pd.isna(row.get("range_low"))
                and row.get("trend") in ("up", "down")
                and row["atr"] > 0
            ):
                range_width = row["range_high"] - row["range_low"]
                is_tight = range_width <= max_atr_mult * row["atr"]

                if is_tight and row["trend"] == "up" and row["close"] > row["range_high"]:
                    entry = row["close"]
                    sl = row["low"]
                    risk = entry - sl
                    if risk > 0:
                        target = entry + target_rr * risk
                        trade = {
                            "direction": "long",
                            "entry": float(entry),
                            "sl": float(sl),
                            "target": float(target),
                            "entry_ts": ts.isoformat(),
                            "entry_idx": i,
                        }
                        events.append({"type": "entry", "ts": ts, **trade})
                        phase = "in_trade"

                elif is_tight and row["trend"] == "down" and row["close"] < row["range_low"]:
                    entry = row["close"]
                    sl = row["high"]
                    risk = sl - entry
                    if risk > 0:
                        target = entry - target_rr * risk
                        trade = {
                            "direction": "short",
                            "entry": float(entry),
                            "sl": float(sl),
                            "target": float(target),
                            "entry_ts": ts.isoformat(),
                            "entry_idx": i,
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
            bars_elapsed = i - trade["entry_idx"]

            if hit_sl:
                events.append({"type": "stoploss_hit", "ts": ts, "exit_price": trade["sl"], **trade})
                phase, trade = "idle", None
            elif hit_target:
                events.append({"type": "target_hit", "ts": ts, "exit_price": trade["target"], **trade})
                phase, trade = "idle", None
            elif bars_elapsed >= time_exit_bars:
                events.append(
                    {"type": "time_exit", "ts": ts, "exit_price": float(row["close"]), **trade}
                )
                phase, trade = "idle", None

    return events


def run(
    state: dict,
    indicator_df: pd.DataFrame,
    target_rr: float = 3.0,
    time_exit_bars: int = 10,
    max_atr_mult: float = CONSOLIDATION_MAX_ATR_MULT,
) -> tuple[dict, list[dict]]:
    """
    Full-history replay + dedup against state['last_sent_ts']. See
    strategy_rsi_bb.run() — same silent-seed-on-first-call behavior to
    avoid a burst of stale alerts on a brand new state file.
    """
    if indicator_df.empty:
        return state, []

    last_ts = state.get("last_sent_ts")
    if last_ts is None:
        seed_ts = indicator_df.index[-1]
        return {**state, "last_sent_ts": seed_ts.isoformat()}, []

    all_events = simulate(
        indicator_df, target_rr=target_rr, time_exit_bars=time_exit_bars, max_atr_mult=max_atr_mult
    )
    cutoff = pd.Timestamp(last_ts)
    new_events = [e for e in all_events if e["ts"] > cutoff]

    if new_events:
        state = {**state, "last_sent_ts": new_events[-1]["ts"].isoformat()}

    return state, new_events
