"""
Synthetic dry run for strategy 8 (2.2 Supertrend + Pivot Points).

Builds two trading days: a choppy day 1 (to establish prior-day R1/S1 via
indicators.daily_pivots), followed by a day-2 strong rally that breaks
R1 and stays above the Supertrend line, then a sharp reversal that flips
Supertrend against the trade — checking the setup -> breakout entry ->
Supertrend-flip exit sequence.

Run: python tests/test_dryrun_supertrend.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import indicators
import strategy8


def make_path():
    rng = np.random.default_rng(5)

    d1_start = pd.Timestamp("2026-08-03 09:15", tz="Asia/Kolkata")
    n1 = 75
    idx1 = pd.date_range(d1_start, periods=n1, freq="5min")
    c1 = 24000 + np.cumsum(rng.normal(0, 3, n1))
    o1 = np.roll(c1, 1)
    o1[0] = 24000
    h1 = np.maximum(o1, c1) + 2
    l1 = np.minimum(o1, c1) - 2

    d2_start = pd.Timestamp("2026-08-04 09:15", tz="Asia/Kolkata")
    closes2 = [c1[-1]]
    for _ in range(30):  # strong rally, breaks R1 and rides above Supertrend
        closes2.append(closes2[-1] + 15.0)
    for _ in range(15):  # sharp reversal, flips Supertrend
        closes2.append(closes2[-1] - 20.0)
    n2 = len(closes2) - 1
    idx2 = pd.date_range(d2_start, periods=n2, freq="5min")
    c2 = np.array(closes2[1:])
    o2 = np.array(closes2[:-1])
    h2 = np.maximum(o2, c2) + 2
    l2 = np.minimum(o2, c2) - 2

    idx = idx1.append(idx2)
    opens = np.concatenate([o1, o2])
    highs = np.concatenate([h1, h2])
    lows = np.concatenate([l1, l2])
    closes = np.concatenate([c1, c2])
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 0}, index=idx
    )


def main():
    bars = make_path()
    ind_df = indicators.build_indicator_frame_supertrend_pivot(bars, atr_length=7, st_mult=3.0)
    ind_df = ind_df.dropna(subset=["supertrend", "r1", "s1"])
    assert not ind_df.empty

    events = strategy8.simulate(ind_df)
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"Bars: {len(bars)}, indicator rows: {len(ind_df)}")
    print("Event counts:", counts)
    for e in events:
        print(" -", e["type"], {k: v for k, v in e.items() if k != "ts"})

    assert counts.get("setup", 0) > 0, "expected an R1-break + Supertrend setup"
    assert counts.get("entry", 0) > 0, "expected the breakout candle to trigger an entry"
    assert (counts.get("target_hit", 0) + counts.get("stoploss_hit", 0)) > 0, (
        "expected the Supertrend flip to close the trade"
    )
    print("\nDRY RUN OK — setup, breakout entry, Supertrend-flip exit all detected.")

    state = strategy8.fresh_state()
    state, first_events = strategy8.run(state, ind_df)
    assert first_events == [], "first-ever run() should seed silently, not replay history"
    state, second_events = strategy8.run(state, ind_df)
    assert second_events == [], "no new bars since seed -> no new events expected"
    print("run()/dedup wrapper OK.")


if __name__ == "__main__":
    main()
