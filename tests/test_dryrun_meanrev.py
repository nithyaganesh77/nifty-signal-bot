"""
Synthetic dry run for strategy 6 (Mean Reversion EMA(5,14) + Martingale
sizing, 1-min chart).

Builds a steady 20-bar decline (so EMA(5) sits below EMA(14) -> "down"
trend), then a bullish reversal candle, a breakout bar that triggers
entry, and a follow-through bar that hits a 1:1 target. Also exercises
the Martingale multiplier logic directly (it lives in main.py, not
strategy6.py, since it's a sizing overlay rather than a signal rule).

Run: python tests/test_dryrun_meanrev.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import indicators
import strategy6 as strat6


def make_short_decline_then_reversal():
    start = pd.Timestamp("2026-08-24 09:15:00", tz="Asia/Kolkata")

    bars = []
    prev_close = 24000.0
    for i in range(20):
        close = prev_close - 5.0
        o = prev_close
        h = max(o, close) + 0.5
        l = min(o, close) - 0.5
        bars.append((o, h, l, close))
        prev_close = close

    # bullish reversal candle (close > open) after the decline
    bars.append((23905.0, 23930.0, 23895.0, 23920.0))
    # breakout bar: high breaks the reversal candle's high (23930) -> entry
    bars.append((23920.0, 23935.0, 23915.0, 23930.0))
    # follow-through: high >= target (entry 23930 + risk 35 = 23965)
    bars.append((23930.0, 23970.0, 23925.0, 23960.0))
    # tail
    bars.append((23960.0, 23965.0, 23955.0, 23962.0))

    idx = pd.date_range(start, periods=len(bars), freq="1min")
    df = pd.DataFrame(
        [{"open": o, "high": h, "low": l, "close": c, "volume": 0} for o, h, l, c in bars],
        index=idx,
    )
    return df


def main():
    bars = make_short_decline_then_reversal()
    ind_df = indicators.build_indicator_frame_meanrev(bars, ema_fast=5, ema_slow=14)
    print(ind_df[["close", "ema_fast", "ema_slow", "trend"]].tail(6).to_string())

    events = strat6.simulate(ind_df, target_rr=1.0)
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"\nTotal events: {len(events)}")
    print("Event counts:", counts)
    for e in events:
        print(" -", e["type"], {k: v for k, v in e.items() if k != "ts"})

    assert counts.get("setup", 0) > 0, "expected a setup on the engineered reversal candle"
    assert counts.get("entry", 0) > 0, "expected the entry to trigger on the breakout bar"
    assert counts.get("target_hit", 0) > 0, "expected the 1:1 target to be hit"
    assert events[0]["direction"] == "long"
    print("\nDRY RUN OK — setup -> entry -> target_hit sequence detected as expected.")

    # run()/dedup wrapper: first call seeds silently
    state = strat6.fresh_state()
    state, first_events = strat6.run(state, ind_df)
    assert first_events == [], "first-ever run() should seed silently, not replay history"
    state, second_events = strat6.run(state, ind_df)
    assert second_events == [], "no new bars since seed -> no new events expected"
    print("run()/dedup wrapper OK.")

    # Martingale sizing overlay (lives in main.py)
    import main as bot_main

    m_state = {"martingale_multiplier": 1.0}
    m_state, mult = bot_main.apply_martingale(m_state, {"type": "entry"}, max_multiplier=8)
    assert mult == 1.0
    m_state, mult = bot_main.apply_martingale(m_state, {"type": "stoploss_hit"}, max_multiplier=8)
    assert m_state["martingale_multiplier"] == 2.0
    m_state, mult = bot_main.apply_martingale(m_state, {"type": "stoploss_hit"}, max_multiplier=8)
    assert m_state["martingale_multiplier"] == 4.0
    m_state, mult = bot_main.apply_martingale(m_state, {"type": "stoploss_hit"}, max_multiplier=8)
    assert m_state["martingale_multiplier"] == 8.0
    m_state, mult = bot_main.apply_martingale(m_state, {"type": "stoploss_hit"}, max_multiplier=8)
    assert m_state["martingale_multiplier"] == 8.0, "should cap at max_multiplier"
    m_state, mult = bot_main.apply_martingale(m_state, {"type": "target_hit"}, max_multiplier=8)
    assert m_state["martingale_multiplier"] == 1.0, "should reset to 1x after a win"
    print("Martingale sizing overlay OK (1x -> 2x -> 4x -> 8x, capped, resets to 1x on a win).")


if __name__ == "__main__":
    main()
