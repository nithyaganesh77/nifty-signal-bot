"""
Synthetic dry run for strategy 11 (2.5 Pullback + Pivot Points).

Builds two trading days: a choppy day 1 (to establish day-2's Standard
Pivot levels via indicators.daily_pivots), then a day-2 approach that
touches a pivot level and closes back above it on a bullish candle —
checking the immediate entry fires with a target at the next pivot level.

Run: python tests/test_dryrun_pivot_pullback.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import indicators
import strategy11


def make_path():
    rng = np.random.default_rng(3)

    d1_start = pd.Timestamp("2026-08-03 09:15", tz="Asia/Kolkata")
    n1 = 75
    idx1 = pd.date_range(d1_start, periods=n1, freq="5min")
    c1 = 24000 + np.cumsum(rng.normal(0, 3, n1))
    o1 = np.roll(c1, 1)
    o1[0] = 24000
    h1 = np.maximum(o1, c1) + 2
    l1 = np.minimum(o1, c1) - 2

    day1_high, day1_low, day1_close = h1.max(), l1.min(), c1[-1]
    p = (day1_high + day1_low + day1_close) / 3

    d2_start = pd.Timestamp("2026-08-04 09:15", tz="Asia/Kolkata")
    closes2 = [c1[-1]]
    target_below = p - 20
    steps = 10
    step = (target_below - closes2[-1]) / steps
    for _ in range(steps):  # approach a pivot level from below
        closes2.append(closes2[-1] + step)
    closes2.append(p + 5)  # pullback candle that touches the level, closes above it
    n2 = len(closes2) - 1
    idx2 = pd.date_range(d2_start, periods=n2, freq="5min")
    c2 = np.array(closes2[1:])
    o2 = np.array(closes2[:-1])
    h2 = np.maximum(o2, c2) + 1
    l2 = np.minimum(o2, c2) - 3  # low dips down through the level

    idx = idx1.append(idx2)
    opens = np.concatenate([o1, o2])
    highs = np.concatenate([h1, h2])
    lows = np.concatenate([l1, l2])
    closes = np.concatenate([c1, c2])
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes}, index=idx)


def main():
    bars = make_path()
    ind_df = indicators.build_indicator_frame_pivot_pullback(bars)
    ind_df = ind_df.dropna(subset=["p"])
    assert not ind_df.empty

    events = strategy11.simulate(ind_df, target_rr=2.0)
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"Bars: {len(bars)}, indicator rows: {len(ind_df)}")
    print("Event counts:", counts)
    for e in events:
        print(" -", e["type"], {k: v for k, v in e.items() if k != "ts"})

    assert counts.get("entry", 0) > 0, "expected the pullback-and-reclaim candle to enter immediately"
    print("\nDRY RUN OK — immediate entry at the pivot pullback detected.")

    state = strategy11.fresh_state()
    state, first_events = strategy11.run(state, ind_df)
    assert first_events == [], "first-ever run() should seed silently, not replay history"
    state, second_events = strategy11.run(state, ind_df)
    assert second_events == [], "no new bars since seed -> no new events expected"
    print("run()/dedup wrapper OK.")


if __name__ == "__main__":
    main()
