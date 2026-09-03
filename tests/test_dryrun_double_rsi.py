"""
Synthetic dry run for strategy 12 (2.6 Double RSI).

Two checks:
  1. A realistic multi-day path (gentle multi-day uptrend, so the hourly
     RSI stays above 50, plus a sharp intraday plunge that pushes the
     5-min RSI below 30) — checks the tandem condition fires an
     immediate long entry, and that a hard stop-loss protects it when
     the decline continues.
  2. A small hand-built dataframe that directly exercises the "exit on
     the 5-min RSI pivoting back through 30, classified by P&L" rule —
     checks a profitable pivot-back exit is reported as target_hit.

Run: python tests/test_dryrun_double_rsi.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import indicators
import strategy12


def make_path():
    rng = np.random.default_rng(11)
    start = pd.Timestamp("2026-08-03 09:15", tz="Asia/Kolkata")

    closes = [24000.0]
    all_idx = []
    for day in range(3):  # 3 trading days of gentle uptrend -> hourly RSI stays > 50
        day_start = start + pd.Timedelta(days=day)
        for _ in range(75):
            closes.append(closes[-1] + rng.normal(0.6, 2.0))
        all_idx.extend(pd.date_range(day_start, periods=75, freq="5min"))

    for _ in range(10):  # sharp intraday plunge -> 5-min RSI oversold
        closes.append(closes[-1] - 12.0)
    extra_start = all_idx[-1] + pd.Timedelta(minutes=5)
    all_idx.extend(pd.date_range(extra_start, periods=10, freq="5min"))

    n = len(all_idx)
    closes_arr = np.array(closes[1 : n + 1])
    opens_arr = np.array(closes[0:n])
    highs = np.maximum(opens_arr, closes_arr) + 0.5
    lows = np.minimum(opens_arr, closes_arr) - 0.5
    return pd.DataFrame(
        {"open": opens_arr, "high": highs, "low": lows, "close": closes_arr},
        index=pd.DatetimeIndex(all_idx),
    )


def test_realistic_path():
    bars = make_path()
    ind_df = indicators.build_indicator_frame_double_rsi(bars, rsi_length=14)
    ind_df = ind_df.dropna(subset=["rsi_fast", "rsi_slow"])
    assert not ind_df.empty

    events = strategy12.simulate(ind_df)
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"Bars: {len(bars)}, indicator rows: {len(ind_df)}")
    print("Event counts:", counts)

    assert counts.get("entry", 0) > 0, "expected the RSI tandem oversold bar to enter immediately"
    assert (counts.get("target_hit", 0) + counts.get("stoploss_hit", 0)) > 0, "expected the trade to close"
    print("Realistic-path check OK.")

    state = strategy12.fresh_state()
    state, first_events = strategy12.run(state, ind_df)
    assert first_events == [], "first-ever run() should seed silently, not replay history"
    state, second_events = strategy12.run(state, ind_df)
    assert second_events == [], "no new bars since seed -> no new events expected"
    print("run()/dedup wrapper OK.")


def test_rsi_pivot_win_classification():
    idx = pd.date_range("2026-08-24 09:15", periods=3, freq="5min", tz="Asia/Kolkata")
    df = pd.DataFrame(
        {
            "open": [100, 101, 104],
            "high": [101, 102, 106],
            "low": [99, 99.5, 100],
            "close": [100, 101, 105],
            "rsi_fast": [25, 28, 31],  # dips below 30, then pivots back above it
            "rsi_slow": [55, 55, 55],  # hourly RSI stays > 50 throughout
        },
        index=idx,
    )
    events = strategy12.simulate(df)
    types = [e["type"] for e in events]
    print("Deterministic RSI-pivot events:", types)
    assert types == ["entry", "target_hit"], (
        "a profitable RSI-pivot-back exit should be classified as target_hit"
    )
    print("RSI-pivot win-classification check OK.")


def main():
    test_realistic_path()
    test_rsi_pivot_win_classification()
    print("\nDRY RUN OK.")


if __name__ == "__main__":
    main()
