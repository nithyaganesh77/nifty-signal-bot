"""
Synthetic dry run for strategy 5 (Moving Average Scalping, 5-min chart,
first hour only).

Builds a hand-crafted first hour of 5-min bars: candle 0 (skipped per the
rule), candle 1 extends cleanly above the EMA without touching it (short
signal candle), candle 2 breaks its low (entry), then price runs down
enough to hit a 1:3 target.

Run: python tests/test_dryrun_ma.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import indicators
import strategy5 as strat5


def make_short_scenario():
    start = pd.Timestamp("2026-08-24 09:15:00", tz="Asia/Kolkata")

    # (open, high, low, close) per 5-min bar, hand-picked so the EMA(7)
    # relationship is unambiguous rather than relying on random jitter.
    bars = [
        (24000.0, 24010.0, 23995.0, 24005.0),  # idx0 09:15 - first candle, skipped
        (24005.0, 24060.0, 24020.0, 24050.0),  # idx1 09:20 - extension, short signal
        (24050.0, 24055.0, 24000.0, 24010.0),  # idx2 09:25 - breaks 24020 -> entry
        (24010.0, 24015.0, 23950.0, 23960.0),  # idx3 09:30
        (23960.0, 23965.0, 23895.0, 23900.0),  # idx4 09:35 - low <= 23900 -> target hit
        (23900.0, 23920.0, 23890.0, 23910.0),  # idx5 09:40 - tail
        (23910.0, 23930.0, 23900.0, 23915.0),  # idx6 09:45 - tail
    ]
    idx = pd.date_range(start, periods=len(bars), freq="5min")
    df = pd.DataFrame(
        [{"open": o, "high": h, "low": l, "close": c, "volume": 0} for o, h, l, c in bars],
        index=idx,
    )
    return df


def main():
    bars = make_short_scenario()
    ind_df = indicators.build_indicator_frame_ma(bars, ema_length=7)
    print(ind_df[["close", "ema", "bar_index_in_day", "in_first_hour"]].to_string())

    events = strat5.simulate(ind_df, target_rr=3.0)
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"\nTotal events: {len(events)}")
    print("Event counts:", counts)
    for e in events:
        print(" -", e["type"], {k: v for k, v in e.items() if k != "ts"})

    assert counts.get("setup", 0) > 0, "expected a setup on the engineered extension candle"
    assert counts.get("entry", 0) > 0, "expected the entry to trigger on the breakout bar"
    assert counts.get("target_hit", 0) > 0, "expected the target to be hit on this engineered path"
    assert events[0]["type"] == "setup" and events[0]["direction"] == "short"
    print("\nDRY RUN OK — setup -> entry -> target_hit sequence detected as expected.")

    # run()/dedup wrapper: first call seeds silently
    state = strat5.fresh_state()
    state, first_events = strat5.run(state, ind_df)
    assert first_events == [], "first-ever run() should seed silently, not replay history"
    state, second_events = strat5.run(state, ind_df)
    assert second_events == [], "no new bars since seed -> no new events expected"
    print("run()/dedup wrapper OK.")


if __name__ == "__main__":
    main()
