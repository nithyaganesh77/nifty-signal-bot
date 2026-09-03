"""
Synthetic dry run for strategy 13 (2.7 CPR with Trend Following).

Two day-1/day-2 pairs, one per CPR-width regime:
  - A choppy day 1 (close near the middle of its range) -> a NARROW CPR
    on day 2 -> checks the breakout-mode entry (price closing through a
    pivot level it was previously on the other side of).
  - A trending day 1 (close far from the middle of its range) -> a WIDE
    CPR on day 2 -> checks the range-fade-mode entry (a reversal candle
    that holds/reclaims a touched pivot level).

Run: python tests/test_dryrun_cpr.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import indicators
import strategy13


def _day1_and_day2(day1_close_fn, seed):
    rng = np.random.default_rng(seed)
    d1_start = pd.Timestamp("2026-08-03 09:15", tz="Asia/Kolkata")
    n1 = 75
    idx1 = pd.date_range(d1_start, periods=n1, freq="5min")
    c1 = day1_close_fn(rng, n1)
    o1 = np.roll(c1, 1)
    o1[0] = 24000
    h1 = np.maximum(o1, c1) + 2
    l1 = np.minimum(o1, c1) - 2

    day1_high, day1_low = h1.max(), l1.min()
    p = (day1_high + day1_low + c1[-1]) / 3

    d2_start = pd.Timestamp("2026-08-04 09:15", tz="Asia/Kolkata")
    closes2 = [c1[-1]]
    target_below = p - 20
    steps = 10
    step = (target_below - closes2[-1]) / steps
    for _ in range(steps):
        closes2.append(closes2[-1] + step)
    closes2.append(p + 5)  # reversal/reclaim candle at the level
    n2 = len(closes2) - 1
    idx2 = pd.date_range(d2_start, periods=n2, freq="5min")
    c2 = np.array(closes2[1:])
    o2 = np.array(closes2[:-1])
    h2 = np.maximum(o2, c2) + 1
    l2 = np.minimum(o2, c2) - 3

    idx = idx1.append(idx2)
    opens = np.concatenate([o1, o2])
    highs = np.concatenate([h1, h2])
    lows = np.concatenate([l1, l2])
    closes = np.concatenate([c1, c2])
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes}, index=idx)


def make_narrow_path():
    # gentle chop -> day-1 close near the middle of its range -> narrow CPR
    return _day1_and_day2(lambda rng, n: 24000 + np.cumsum(rng.normal(0, 3, n)), seed=13)


def make_wide_path():
    # strong trend all day -> day-1 close far from the middle -> wide CPR
    return _day1_and_day2(
        lambda rng, n: 24000 + np.linspace(0, 150, n) + rng.normal(0, 1, n), seed=13
    )


def _run_and_check(bars, expect_mode):
    ind_df = indicators.build_indicator_frame_cpr(bars, atr_length=14, narrow_atr_mult=1.0)
    ind_df = ind_df.dropna(subset=["p", "atr"])
    assert not ind_df.empty

    day2_mode = ind_df["cpr_mode"].iloc[-1]
    print(f"day-2 cpr_mode: {day2_mode} (width={ind_df['cpr_width'].iloc[-1]:.2f}, atr={ind_df['atr'].iloc[-1]:.2f})")
    assert day2_mode == expect_mode, f"expected {expect_mode} CPR for this synthetic day 1"

    events = strategy13.simulate(ind_df, target_rr=2.0)
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print("Event counts:", counts)
    for e in events:
        print(" -", e["type"], {k: v for k, v in e.items() if k != "ts"})

    assert counts.get("entry", 0) > 0, f"expected a {expect_mode}-mode entry"
    assert all(e.get("cpr_mode") == expect_mode for e in events if e["type"] == "entry")
    return ind_df


def main():
    print("--- narrow CPR (breakout mode) ---")
    narrow_bars = make_narrow_path()
    narrow_ind = _run_and_check(narrow_bars, "narrow")

    print("\n--- wide CPR (range-fade mode) ---")
    wide_bars = make_wide_path()
    wide_ind = _run_and_check(wide_bars, "wide")

    state = strategy13.fresh_state()
    state, first_events = strategy13.run(state, wide_ind)
    assert first_events == [], "first-ever run() should seed silently, not replay history"
    state, second_events = strategy13.run(state, wide_ind)
    assert second_events == [], "no new bars since seed -> no new events expected"
    print("\nrun()/dedup wrapper OK.")
    print("\nDRY RUN OK — both narrow (breakout) and wide (range-fade) modes detected.")


if __name__ == "__main__":
    main()
