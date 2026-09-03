"""
Synthetic dry run for strategy 9 (2.3 VWAP + Standard Deviations).

Builds a 5-min path with a sharp sell-off that pushes price below the
2-std-dev lower VWAP band, then a green reversal candle and a breakout
candle, followed by a continuation strong enough to book the first
target — checking the setup -> breakout entry -> target1 (partial)
sequence.

Run: python tests/test_dryrun_vwap_std.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import indicators
import strategy9


def make_path():
    start = pd.Timestamp("2026-08-24 09:15", tz="Asia/Kolkata")
    rng = np.random.default_rng(7)

    closes = [24000.0]
    for _ in range(20):
        closes.append(closes[-1] + rng.normal(0, 1.5))
    for _ in range(10):  # sharp sell-off below the lower band
        closes.append(closes[-1] - rng.uniform(8, 14))
    closes.append(closes[-1] + 25)  # green reversal candle
    closes.append(closes[-1] + 20)  # breakout candle
    for _ in range(15):  # continuation toward the target(s)
        closes.append(closes[-1] + rng.uniform(3, 6))

    n = len(closes)
    idx = pd.date_range(start, periods=n, freq="5min")
    opens, highs, lows = [], [], []
    prev = closes[0]
    for c in closes:
        o = prev
        h = max(o, c) + abs(rng.normal(0, 0.5))
        l = min(o, c) - abs(rng.normal(0, 0.5))
        opens.append(o)
        highs.append(h)
        lows.append(l)
        prev = c

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 0}, index=idx
    )


def main():
    bars = make_path()
    ind_df = indicators.build_indicator_frame_vwap_std(bars, band_mult=2.0)
    ind_df = ind_df.dropna(subset=["vwap", "vwap_upper", "vwap_lower"])
    assert not ind_df.empty

    events = strategy9.simulate(ind_df)
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"Bars: {len(bars)}, indicator rows: {len(ind_df)}")
    print("Event counts:", counts)
    for e in events:
        print(" -", e["type"], {k: v for k, v in e.items() if k != "ts"})

    assert counts.get("setup", 0) > 0, "expected a lower-band reversal setup"
    assert counts.get("entry", 0) > 0, "expected the breakout candle to trigger an entry"
    assert counts.get("target1_hit", 0) > 0, "expected target 1 (VWAP) to be booked"
    print("\nDRY RUN OK — setup, breakout entry, target1 partial-book all detected.")

    state = strategy9.fresh_state()
    state, first_events = strategy9.run(state, ind_df)
    assert first_events == [], "first-ever run() should seed silently, not replay history"
    state, second_events = strategy9.run(state, ind_df)
    assert second_events == [], "no new bars since seed -> no new events expected"
    print("run()/dedup wrapper OK.")


if __name__ == "__main__":
    main()
