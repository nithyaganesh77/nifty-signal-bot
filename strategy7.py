"""
Mechanical implementation of the 2.1 "Moving Average and Fibonacci"
strategy (5-minute chart).

Rules (from the "TO BUY" / "TO SELL" pages):

  1. Apply the 200-period Moving Average (SMA, close) on a 5-minute chart.
  2. If price is above the 200-SMA, the market is in an uptrend — draw the
     Fibonacci Retracement tool from the last swing low to the swing high
     that followed it. If price is below the 200-SMA (downtrend), draw it
     from the last swing high to the swing low that followed it.
  3. Price above the Moving Average has the possibility to correct till
     any of the Fibonacci levels. At any level, if price is taking
     support (uptrend) / facing resistance (downtrend) and forms a
     bullish / bearish candle, place the BUY/SELL order at the HIGH/LOW
     of that closing candle — a breakout (stop) order, not an immediate
     entry.
  4. STOPLOSS at the lower/upper Fibonacci level (the level just beyond
     where price found support/resistance).
  5. TARGET at a minimum of 1:2 risk:reward.
  6. "A thing to remember": the Moving Average's own slope matters — a
     rising trade needs a Moving Average that isn't still falling (and
     vice-versa for a short), or it risks being a fake breakout. Modeled
     here as sma_slope >= 0 for longs / <= 0 for shorts (see
     indicators.build_indicator_frame_ma_fib).

Swing points are the confirmed pivot highs/lows from
indicators.find_pivots (same mechanism strategy_rsi_bb.py uses for
divergence) — a pivot at bar i can only be confirmed `pivot_right` bars
later, an inherent lag shared with every other confirmed-swing strategy
in this bot. The "lower/upper Fibonacci level" stop is taken literally as
the next retracement level beyond the one price actually touched.

Two-phase state machine per swing direction: idle -> setup (waiting for
the breakout of the signal candle) -> in_trade, mirroring strategy1.py /
strategy5.py. Not day-scoped (a multi-day trend tool, like strategies 1-4).
"""

from __future__ import annotations

import pandas as pd

import indicators

DEFAULT_TARGET_RR = 2.0  # minimum 1:2 per the write-up

# sorted ascending by retracement fraction: index 0 = swing high (0%), -1 = swing low (100%)
_FIB_KEYS = ["0.0", "0.236", "0.382", "0.5", "0.618", "0.786", "1.0"]


def fresh_state() -> dict:
    return {"last_sent_ts": None}


def _touch_zone(levels: dict, price: float) -> bool:
    """True if price sits within the 23.6%-78.6% retracement band."""
    hi = levels["0.236"]
    lo = levels["0.786"]
    return lo <= price <= hi


def _lower_level_for_long(levels: dict, low: float) -> float:
    """Next Fibonacci level at/just below `low` (the stoploss for a BUY)."""
    prices_desc = [levels[k] for k in _FIB_KEYS]  # high -> low, descending
    below = [p for p in prices_desc if p <= low]
    return min(below) if below else levels["1.0"]


def _upper_level_for_short(levels: dict, high: float) -> float:
    """Next Fibonacci level at/just above `high` (the stoploss for a SELL)."""
    prices_asc = [levels[k] for k in reversed(_FIB_KEYS)]  # low -> high, ascending
    above = [p for p in prices_asc if p >= high]
    return max(above) if above else levels["0.0"]


def simulate(df: pd.DataFrame, target_rr: float = DEFAULT_TARGET_RR, sl_buffer: float = 0.0) -> list[dict]:
    """
    Pure function: replay the whole strategy from an idle state across
    every row of df (must have columns from
    indicators.build_indicator_frame_ma_fib) and return every event, in
    chronological order. Each event dict has a 'ts' key.
    """
    events: list[dict] = []
    phase = "idle"
    setup = None
    trade = None
    last_pivot_low = None   # {"price": float, "ts": Timestamp}
    last_pivot_high = None

    for i in range(len(df)):
        row = df.iloc[i]
        ts = df.index[i]

        if bool(row.get("pivot_low")):
            last_pivot_low = {"price": float(row["low"]), "ts": ts}
        if bool(row.get("pivot_high")):
            last_pivot_high = {"price": float(row["high"]), "ts": ts}

        if phase == "idle":
            if pd.isna(row.get("sma200")) or pd.isna(row.get("sma_slope")):
                continue

            # --- uptrend: look for a BUY setup off a swing low -> swing high leg
            if (
                row["close"] > row["sma200"]
                and row["sma_slope"] >= 0
                and last_pivot_low is not None
                and last_pivot_high is not None
                and last_pivot_high["ts"] > last_pivot_low["ts"]
                and last_pivot_high["price"] > last_pivot_low["price"]
            ):
                levels = indicators.fibonacci_levels(last_pivot_low["price"], last_pivot_high["price"])
                is_bullish = row["close"] > row["open"]
                if is_bullish and _touch_zone(levels, row["low"]):
                    trigger = float(row["high"])
                    sl = _lower_level_for_long(levels, float(row["low"])) - sl_buffer
                    if sl < trigger:
                        setup = {
                            "direction": "long",
                            "signal_ts": ts.isoformat(),
                            "trigger": trigger,
                            "sl": sl,
                        }
                        events.append({"type": "setup", "ts": ts, **setup})
                        phase = "setup"
                        continue

            # --- downtrend: look for a SELL setup off a swing high -> swing low leg
            if (
                row["close"] < row["sma200"]
                and row["sma_slope"] <= 0
                and last_pivot_high is not None
                and last_pivot_low is not None
                and last_pivot_low["ts"] > last_pivot_high["ts"]
                and last_pivot_low["price"] < last_pivot_high["price"]
            ):
                levels = indicators.fibonacci_levels(last_pivot_low["price"], last_pivot_high["price"])
                is_bearish = row["close"] < row["open"]
                if is_bearish and _touch_zone(levels, row["high"]):
                    trigger = float(row["low"])
                    sl = _upper_level_for_short(levels, float(row["high"])) + sl_buffer
                    if sl > trigger:
                        setup = {
                            "direction": "short",
                            "signal_ts": ts.isoformat(),
                            "trigger": trigger,
                            "sl": sl,
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
                    risk = entry - sl
                    target = entry + target_rr * risk
                    trade = {
                        "direction": "long", "entry": float(entry), "sl": float(sl),
                        "target": float(target), "entry_ts": ts.isoformat(),
                        "signal_ts": setup["signal_ts"],
                    }
                    events.append({"type": "entry", "ts": ts, **trade})
                    phase, setup = "in_trade", None
            else:
                if row["high"] >= setup["sl"]:
                    events.append({"type": "setup_invalidated", "ts": ts, **setup})
                    phase, setup = "idle", None
                elif row["low"] <= setup["trigger"]:
                    entry, sl = setup["trigger"], setup["sl"]
                    risk = sl - entry
                    target = entry - target_rr * risk
                    trade = {
                        "direction": "short", "entry": float(entry), "sl": float(sl),
                        "target": float(target), "entry_ts": ts.isoformat(),
                        "signal_ts": setup["signal_ts"],
                    }
                    events.append({"type": "entry", "ts": ts, **trade})
                    phase, setup = "in_trade", None

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
