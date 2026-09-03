"""
Synthetic dry run for strategy 7 (2.1 Moving Average + Fibonacci).

Builds a deterministic 5-min path: a long, gentle uptrend to warm up the
200-SMA, then an explicit dip (swing low) -> rally (swing high) leg, then
a pullback into the 23.6%-78.6% Fibonacci retracement band with a
bullish reversal candle, then a breakout candle that clears its high —
and checks the strategy detects the setup and fires the breakout entry.

Run: python tests/test_dryrun_ma_fib.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import indicators
import strategy7


def make_path():
    start = pd.Timestamp("2026-08-01 09:15", tz="Asia/Kolkata")

    closes = [24000.0]
    for _ in range(210):  # slow uptrend warm-up for SMA(200)
        closes.append(closes[-1] + 0.05)
    for _ in range(10):  # dip -> swing low
        closes.append(closes[-1] - 3.0)
    for _ in range(20):  # rally -> swing high
        closes.append(closes[-1] + 10.0)

    swing_low = closes[220]
    swing_high = closes[240]
    target_pullback = swing_high - 0.5 * (swing_high - swing_low)
    steps = 8
    per_step = (closes[-1] - target_pullback) / steps
    for _ in range(steps):  # pullback into the Fib zone
        closes.append(closes[-1] - per_step)

    closes.append(closes[-1] + 5.0)  # bullish reversal (signal) candle
    closes.append(closes[-1] + 8.0)  # breakout candle
    for _ in range(10):
        closes.append(closes[-1] + 0.3)  # tail

    n = len(closes)
    idx = pd.date_range(start, periods=n, freq="5min")
    opens, highs, lows = [], [], []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        # tiny tie-breaking epsilon only around the dip/rally so the pivot
        # detector finds a clean, unambiguous swing low/high there
        eps = 0.01 * (i % 5) if 205 <= i <= 245 else 0.0
        h = max(o, c) + 0.3 + eps
        l = min(o, c) - 0.3 - eps
        opens.append(o)
        highs.append(h)
        lows.append(l)
        prev = c

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 0}, index=idx
    )


def main():
    bars = make_path()
    ind_df = indicators.build_indicator_frame_ma_fib(bars, sma_length=200, pivot_left=3, pivot_right=3)
    ind_df = ind_df.dropna(subset=["sma200"])
    assert not ind_df.empty

    events = strategy7.simulate(ind_df, target_rr=2.0)
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"Bars: {len(bars)}, indicator rows: {len(ind_df)}")
    print("Event counts:", counts)
    for e in events:
        print(" -", e["type"], {k: v for k, v in e.items() if k != "ts"})

    assert counts.get("setup", 0) > 0, "expected a Fibonacci pullback setup to be detected"
    assert counts.get("entry", 0) > 0, "expected the breakout candle to trigger an entry"
    print("\nDRY RUN OK — setup + breakout entry detected.")

    state = strategy7.fresh_state()
    state, first_events = strategy7.run(state, ind_df)
    assert first_events == [], "first-ever run() should seed silently, not replay history"
    state, second_events = strategy7.run(state, ind_df)
    assert second_events == [], "no new bars since seed -> no new events expected"
    print("run()/dedup wrapper OK.")


if __name__ == "__main__":
    main()
