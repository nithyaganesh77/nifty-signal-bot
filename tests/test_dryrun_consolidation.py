"""
Synthetic dry run for strategy 4 (1-Minute Consolidation Breakout).

Builds a price path with a clear uptrend, a tight 5-bar consolidation,
then a decisive breakout candle, and checks the strategy detects the
immediate entry -> target/SL/time-exit sequence end-to-end.

Run: python tests/test_dryrun_consolidation.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import indicators
import strategy4 as strat4


def make_breakout_path():
    start = pd.Timestamp("2026-08-24 09:15:00", tz="Asia/Kolkata")
    rng = np.random.default_rng(5)

    closes = [24000.0]
    # steady uptrend for ~30 bars, to build a clear positive EMA slope
    for _ in range(30):
        closes.append(closes[-1] + rng.uniform(1.0, 2.5))

    # tight 5-bar consolidation: small back-and-forth, ~no net drift
    for _ in range(5):
        closes.append(closes[-1] + rng.normal(0, 0.5))

    # decisive breakout candle: a clean, sizeable move up
    closes.append(closes[-1] + 12)

    # continue up enough to hit a 1:3 target on a modest-risk breakout
    for _ in range(6):
        closes.append(closes[-1] + rng.uniform(2, 5))

    # tail
    for _ in range(10):
        closes.append(closes[-1] + rng.normal(0, 1.0))

    n = len(closes)
    idx = pd.date_range(start, periods=n, freq="1min")

    opens, highs, lows = [], [], []
    prev = closes[0]
    for c in closes:
        o = prev
        h = max(o, c) + abs(rng.normal(0, 0.3))
        l = min(o, c) - abs(rng.normal(0, 0.3))
        opens.append(o)
        highs.append(h)
        lows.append(l)
        prev = c

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 0},
        index=idx,
    )
    return df


def main():
    bars = make_breakout_path()
    ind_df = indicators.build_indicator_frame_consolidation(bars)
    ind_df = ind_df.dropna(subset=["atr", "range_high", "range_low"])
    assert not ind_df.empty, "indicator frame is unexpectedly empty"

    print(f"Bars: {len(bars)}, indicator rows after warm-up: {len(ind_df)}")
    print(ind_df[["close", "trend", "atr", "range_high", "range_low"]].tail(12).to_string())

    events = strat4.simulate(ind_df, target_rr=3.0, time_exit_bars=10)
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"\nTotal events: {len(events)}")
    print("Event counts:", counts)
    for e in events:
        print(" -", e["type"], {k: v for k, v in e.items() if k != "ts"})

    assert counts.get("entry", 0) > 0, "expected at least one breakout entry on this engineered path"
    print("\nDRY RUN OK — no crashes, at least one breakout entry detected.")

    # run()/dedup wrapper: first call seeds silently
    state = strat4.fresh_state()
    state, first_events = strat4.run(state, ind_df)
    assert first_events == [], "first-ever run() should seed silently, not replay history"
    state, second_events = strat4.run(state, ind_df)
    assert second_events == [], "no new bars since seed -> no new events expected"
    print("run()/dedup wrapper OK.")


if __name__ == "__main__":
    main()
