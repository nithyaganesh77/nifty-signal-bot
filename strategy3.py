"""
Mechanical implementation of the third strategy: "Scalp Trading with RSI
and VWAP" (1-minute chart).

Rules (from the "TO BUY" / "TO SELL" pages):

  TO BUY:
    1. Add VWAP (session, hlc3, bands at 1/2/3 std-dev) and RSI(14) on a
       1-min chart.
    2. Look for RSI to be in the oversold zone (<30) and price to take
       support at the VWAP.
    3. BUY when both indicators give a buy signal — here: RSI was
       oversold recently AND this candle touches/dips to the VWAP line
       and closes back above it as a bullish (green) candle — a bounce.
       Entry is IMMEDIATE on that bounce candle (the write-up doesn't ask
       for a further breakout above it, unlike strategy 1's "above the
       high of the bullish candle").
    4. STOPLOSS below the VWAP. TARGET at the (upper) VWAP band, or trail
       it for maximum gains.

  TO SELL (mirror):
    2. RSI in the overbought zone (>70) and price faces rejection at VWAP.
    3. SELL immediately when this candle touches/rises to the VWAP and
       closes back below it as a bearish (red) candle.
    4. STOPLOSS above the VWAP. TARGET at the (lower) VWAP band.

Like strategy 2, there's no partial-exit rule in the write-up, so this is
a single stop-loss / single-target trade. "Trail it for maximum gains"
is a discretionary add-on the write-up mentions but doesn't give
mechanical rules for, so it isn't automated here — the single VWAP-band
target is used as-is (see VWAP_TARGET_BAND in config.py to pick which
band: 1, 2, or 3).

Same full-history deterministic-replay design as strategy_rsi_bb.py: the
touch/bounce candle IS the entry (no separate "wait for a breakout"
stage — see the fix note below), so the state machine is simply
idle -> in_trade.
"""

from __future__ import annotations

import pandas as pd


def fresh_state() -> dict:
    return {"last_sent_ts": None}


def _detect_trade(row: pd.Series, target_band: int, sl_buffer: float = 0.0) -> dict | None:
    if pd.isna(row.get("rsi")) or pd.isna(row.get("vwap")):
        return None

    upper_col = f"vwap_upper{target_band}"
    lower_col = f"vwap_lower{target_band}"

    is_bullish_bounce = row["close"] > row["open"] and row["close"] > row["vwap"]
    is_bearish_rejection = row["close"] < row["open"] and row["close"] < row["vwap"]

    if bool(row.get("recent_oversold")) and row["low"] <= row["vwap"] and is_bullish_bounce:
        entry = row["close"]
        sl = row["vwap"] - sl_buffer
        target = row[upper_col]
        if target > entry and sl < entry:
            return {
                "direction": "long",
                "signal_ts": row.name.isoformat(),
                "entry": float(entry),
                "sl": float(sl),
                "target": float(target),
            }

    if bool(row.get("recent_overbought")) and row["high"] >= row["vwap"] and is_bearish_rejection:
        entry = row["close"]
        sl = row["vwap"] + sl_buffer
        target = row[lower_col]
        if target < entry and sl > entry:
            return {
                "direction": "short",
                "signal_ts": row.name.isoformat(),
                "entry": float(entry),
                "sl": float(sl),
                "target": float(target),
            }

    return None


def simulate(df: pd.DataFrame, target_band: int = 1, sl_buffer: float = 0.0) -> list[dict]:
    """
    Pure function: replay the whole strategy from an idle state across
    every row of df (must have columns from
    indicators.build_indicator_frame_vwap) and return every event, in
    chronological order. Entry fires immediately on the bounce/rejection
    candle (see module docstring's fix note) — no separate setup/trigger
    stage. Each event dict has a 'ts' key for ordering/dedup by the caller.
    """
    events: list[dict] = []
    phase = "idle"
    trade = None

    for i in range(len(df)):
        row = df.iloc[i]
        ts = df.index[i]

        if phase == "idle":
            found = _detect_trade(row, target_band, sl_buffer=sl_buffer)
            if found is not None:
                trade = {**found, "entry_ts": ts.isoformat()}
                events.append({"type": "entry", "ts": ts, **found})
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

    return events


def run(
    state: dict, indicator_df: pd.DataFrame, target_band: int = 1, sl_buffer: float = 0.0
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

    all_events = simulate(indicator_df, target_band=target_band, sl_buffer=sl_buffer)
    cutoff = pd.Timestamp(last_ts)
    new_events = [e for e in all_events if e["ts"] > cutoff]

    if new_events:
        state = {**state, "last_sent_ts": new_events[-1]["ts"].isoformat()}

    return state, new_events
