"""
Not a broker-connected test — a synthetic dry run to make sure the
indicator math and strategy state machine don't crash and produce
sane-looking events on a fabricated up/down/up price path.

Run: python tests/test_dryrun.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import indicators
import strategy


def make_synthetic_bars(n=300, seed=7):
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-08-24 09:15:00", tz="Asia/Kolkata")
    idx = pd.date_range(start, periods=n, freq="3min")

    price = 24000.0
    opens, highs, lows, closes = [], [], [], []
    trend = 1
    for i in range(n):
        if i % 40 == 0:
            trend *= -1  # flip trend periodically so both long and short
            # setups should occur
        drift = trend * rng.uniform(0.5, 3.0)
        o = price
        c = o + drift + rng.normal(0, 1.5)
        h = max(o, c) + abs(rng.normal(0, 1.0))
        l = min(o, c) - abs(rng.normal(0, 1.0))
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        price = c

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 0},
        index=idx,
    )
    return df


def main():
    bars = make_synthetic_bars()
    ind_df = indicators.build_indicator_frame(bars)
    ind_df = ind_df.dropna(subset=["rsi", "sar"])
    assert not ind_df.empty, "indicator frame is unexpectedly empty"

    print(f"Bars: {len(bars)}, indicator rows after warm-up: {len(ind_df)}")
    print(ind_df[["close", "ha_color", "sar", "rsi"]].tail(5))

    events = strategy.simulate(ind_df)

    print(f"\nTotal events: {len(events)}")
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print("Event counts:", counts)

    for e in events[:8]:
        print(" -", e["type"], {k: v for k, v in e.items() if k not in ("signal_ts", "ts")})

    assert counts.get("setup", 0) > 0, "expected at least one setup to form"
    print("\nDRY RUN OK — no crashes, at least one setup formed.")

    # sanity-check the stateful run()/dedup wrapper: first call should seed
    # silently (no backlog spam), second call on the same data -> no new events
    state = strategy.fresh_state()
    state, first_events = strategy.run(state, ind_df)
    assert first_events == [], "first-ever run() should seed silently, not replay history"
    state, second_events = strategy.run(state, ind_df)
    assert second_events == [], "no new bars since seed -> no new events expected"
    print("run()/dedup wrapper OK.")


if __name__ == "__main__":
    main()
