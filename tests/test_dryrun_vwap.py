"""
Synthetic dry run for strategy 3 (RSI + VWAP Scalping).

Builds a price path with a sharp sell-off (pushes RSI into oversold) that
then bounces cleanly off a level near VWAP, and checks the strategy
detects the support-bounce -> setup -> entry sequence end-to-end.

Run: python tests/test_dryrun_vwap.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import indicators
import strategy3 as strat3


def make_bounce_path():
    start = pd.Timestamp("2026-08-24 09:15:00", tz="Asia/Kolkata")
    rng = np.random.default_rng(11)

    closes = [24000.0]
    # chop near a level for warm-up so VWAP settles (~15 bars)
    for _ in range(15):
        closes.append(closes[-1] + rng.normal(0, 1.0))

    # sharp sell-off: drives RSI into oversold, over 8 bars
    for _ in range(8):
        closes.append(closes[-1] - rng.uniform(4, 7))

    # bounce: a clean green candle back up, then a breakout candle.
    # Session VWAP is a running average since 9:15, so after a fast
    # decline it still sits well above the current low (it's dragged
    # down slowly) — the bounce needs to be large enough to actually
    # close back above that lagging VWAP line, not just tick up.
    closes.append(closes[-1] + 20)
    closes.append(closes[-1] + 20)

    # tail
    for _ in range(15):
        closes.append(closes[-1] + rng.normal(0, 1.2))

    n = len(closes)
    idx = pd.date_range(start, periods=n, freq="1min")

    opens, highs, lows, vols = [], [], [], []
    prev = closes[0]
    for c in closes:
        o = prev
        h = max(o, c) + abs(rng.normal(0, 0.4))
        l = min(o, c) - abs(rng.normal(0, 0.4))
        opens.append(o)
        highs.append(h)
        lows.append(l)
        vols.append(0)  # simulate an index ticker with no volume, like ^NSEI
        prev = c

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=idx,
    )
    return df


def main():
    bars = make_bounce_path()
    ind_df = indicators.build_indicator_frame_vwap(bars)
    ind_df = ind_df.dropna(subset=["rsi", "vwap"])
    assert not ind_df.empty, "indicator frame is unexpectedly empty"
    assert bool(ind_df["used_volume_fallback"].all()), "zero-volume bars should trigger the fallback"

    print(f"Bars: {len(bars)}, indicator rows after warm-up: {len(ind_df)}")
    print(f"Volume fallback active: {bool(ind_df['used_volume_fallback'].iloc[-1])}")

    events = strat3.simulate(ind_df, target_band=1)
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"\nTotal events: {len(events)}")
    print("Event counts:", counts)
    for e in events:
        print(" -", e["type"], {k: v for k, v in e.items() if k != "ts"})

    assert len(events) > 0, "expected at least one event on this engineered bounce path"
    print("\nDRY RUN OK — no crashes, VWAP fallback engaged correctly.")

    # run()/dedup wrapper: first call seeds silently
    state = strat3.fresh_state()
    state, first_events = strat3.run(state, ind_df)
    assert first_events == [], "first-ever run() should seed silently, not replay history"
    state, second_events = strat3.run(state, ind_df)
    assert second_events == [], "no new bars since seed -> no new events expected"
    print("run()/dedup wrapper OK.")


if __name__ == "__main__":
    main()
