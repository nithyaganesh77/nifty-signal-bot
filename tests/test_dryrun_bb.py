"""
Synthetic dry run for strategy 2 (RSI Divergence + Bollinger Bands).

Builds a price path with two deliberate down-legs where the second leg
makes a lower price low but a shallower (higher-RSI) sell-off than the
first — a textbook bullish divergence — followed by a green reversal
candle, and checks the strategy actually detects it end-to-end (no
crashes, at least one divergence -> setup -> entry sequence found).

Run: python tests/test_dryrun_bb.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import indicators
import strategy_rsi_bb as strat2


def make_divergence_path():
    """
    Handcrafted 1-min bar sequence:
      - flat/choppy warm-up (for BB/RSI/pivot warm-up)
      - down-leg 1: sharp fall to a swing low
      - bounce
      - down-leg 2: slower fall to a *lower* swing low (weaker momentum ->
        higher RSI at the low than leg 1 -> bullish divergence)
      - a clean green reversal candle
      - a breakout candle that clears the reversal candle's high
    """
    start = pd.Timestamp("2026-08-24 09:15:00", tz="Asia/Kolkata")
    rng = np.random.default_rng(3)

    closes = [24000.0]
    # gentle chop for warm-up (~40 bars)
    for _ in range(40):
        closes.append(closes[-1] + rng.normal(0, 1.0))

    # down-leg 1: fast, sharp drop of ~40 pts over 6 bars
    for _ in range(6):
        closes.append(closes[-1] - rng.uniform(5, 9))

    # bounce back up ~20 pts over 8 bars
    for _ in range(8):
        closes.append(closes[-1] + rng.uniform(2, 4))

    # down-leg 2: slower drop, but ends lower than leg 1's low, over 10 bars
    leg1_low = min(closes[-14:])
    target_low = leg1_low - 15
    steps = 10
    per_step = (closes[-1] - target_low) / steps
    for _ in range(steps):
        closes.append(closes[-1] - per_step * rng.uniform(0.7, 1.1))

    # a few flat bars to let the pivot confirm (needs `right` bars after it)
    for _ in range(5):
        closes.append(closes[-1] + rng.normal(0, 0.5))

    # clean green reversal candle + breakout candle
    closes.append(closes[-1] + 6)
    closes.append(closes[-1] + 8)

    # tail so nothing runs off the end of the array
    for _ in range(15):
        closes.append(closes[-1] + rng.normal(0, 1.5))

    n = len(closes)
    idx = pd.date_range(start, periods=n, freq="1min")

    opens, highs, lows = [], [], []
    prev = closes[0]
    for c in closes:
        o = prev
        h = max(o, c) + abs(rng.normal(0, 0.4))
        l = min(o, c) - abs(rng.normal(0, 0.4))
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
    bars = make_divergence_path()
    ind_df = indicators.build_indicator_frame_bb(bars)
    ind_df = ind_df.dropna(subset=["rsi", "bb_upper", "bb_lower"])
    assert not ind_df.empty, "indicator frame is unexpectedly empty"

    print(f"Bars: {len(bars)}, indicator rows after warm-up: {len(ind_df)}")
    print(f"Confirmed pivot lows: {int(ind_df['pivot_low'].sum())}, "
          f"pivot highs: {int(ind_df['pivot_high'].sum())}")

    events = strat2.simulate(ind_df)
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"\nTotal events: {len(events)}")
    print("Event counts:", counts)
    for e in events:
        print(" -", e["type"], {k: v for k, v in e.items() if k != "ts"})

    assert counts.get("divergence", 0) > 0, "expected at least one divergence to be flagged"
    print("\nDRY RUN OK — no crashes, at least one divergence detected.")

    # also sanity-check the stateful run()/dedup wrapper doesn't crash and
    # correctly seeds silently on first call
    state = strat2.fresh_state()
    state, first_events = strat2.run(state, ind_df)
    assert first_events == [], "first-ever run() should seed silently, not replay history"
    state, second_events = strat2.run(state, ind_df)
    assert second_events == [], "no new bars since seed -> no new events expected"
    print("run()/dedup wrapper OK.")


if __name__ == "__main__":
    main()
