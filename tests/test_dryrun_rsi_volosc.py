"""
Synthetic dry run for strategy 10 (2.4 RSI + Volume Oscillator).

Builds a 5-min path with a confirmed swing-low pivot (a support level),
then a decline with steadily FADING volume that pushes both RSI and the
Volume Oscillator into their oversold zones (<=30 / <=-30) in tandem
while price still sits above that support, then a bounce strong enough
to hit the 1:2 target — checking the immediate-entry + target sequence.

Run: python tests/test_dryrun_rsi_volosc.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import indicators
import strategy10


def make_path():
    start = pd.Timestamp("2026-08-24 09:15", tz="Asia/Kolkata")
    rng = np.random.default_rng(9)

    closes = [24000.0]
    vols = [1000]
    for _ in range(20):  # warm-up chop
        closes.append(closes[-1] + rng.normal(0, 0.5))
        vols.append(1000 + rng.integers(-50, 50))
    for _ in range(6):  # dip -> forms the support pivot
        closes.append(closes[-1] - 15.0)
        vols.append(1000)
    for _ in range(6):  # bounce off it
        closes.append(closes[-1] + 15.0)
        vols.append(1000)
    for _ in range(4):  # small run-up before the real decline
        closes.append(closes[-1] + 5.0)
        vols.append(1000)
    for i in range(12):  # decline with fading volume -> RSI+VolOsc tandem oversold
        closes.append(closes[-1] - 9.0)
        vols.append(max(50, 1000 - i * 70))
    for _ in range(4):  # bounce to secure the target
        closes.append(closes[-1] + 20.0)
        vols.append(500)

    n = len(closes)
    idx = pd.date_range(start, periods=n, freq="5min")
    opens, highs, lows = [], [], []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        eps = 0.01 * (i % 5) if 18 <= i <= 34 else 0.0  # tie-break around the dip/bounce
        h = max(o, c) + 0.3 + eps
        l = min(o, c) - 0.3 - eps
        opens.append(o)
        highs.append(h)
        lows.append(l)
        prev = c

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}, index=idx
    )


def main():
    bars = make_path()
    ind_df = indicators.build_indicator_frame_rsi_volosc(
        bars, rsi_length=14, vo_fast=5, vo_slow=10, pivot_left=3, pivot_right=3
    )
    ind_df = ind_df.dropna(subset=["rsi", "vol_osc"])
    assert not ind_df.empty
    assert not bool(ind_df["used_volume_fallback"].iloc[-1]), "this test uses real (nonzero) volume"

    events = strategy10.simulate(ind_df, target_rr=2.0)
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"Bars: {len(bars)}, indicator rows: {len(ind_df)}")
    print("Event counts:", counts)
    for e in events:
        print(" -", e["type"], {k: v for k, v in e.items() if k != "ts"})

    assert counts.get("entry", 0) > 0, "expected the RSI+VolOsc tandem oversold bar to enter immediately"
    assert counts.get("target_hit", 0) > 0, "expected the bounce to hit the 1:2 target"
    print("\nDRY RUN OK — immediate entry + target hit detected.")

    state = strategy10.fresh_state()
    state, first_events = strategy10.run(state, ind_df)
    assert first_events == [], "first-ever run() should seed silently, not replay history"
    state, second_events = strategy10.run(state, ind_df)
    assert second_events == [], "no new bars since seed -> no new events expected"
    print("run()/dedup wrapper OK.")


if __name__ == "__main__":
    main()
