"""
Sanity check for MAX_SL_POINTS (config.py / risk.py): confirms that a
raw stop-loss sitting further than max_sl_points from entry gets pulled
in to exactly max_sl_points, that a target computed as an RR-multiple of
risk shrinks proportionally (since risk is computed from the already-
capped sl), and that a normal, in-range stop is left untouched.

Uses risk.apply_sl() directly (the shared helper every strategy calls)
plus strategy.py (strategy 1, SAR-based sl) as one end-to-end case, since
that's the strategy whose live data motivated this cap (a 170+ point SAR
stop after an overnight gap).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import risk
import strategy


def test_apply_sl_caps_long():
    # entry 100, raw sl way out at 20 points ordinarily, but buffer pushes
    # it further, and the raw indicator value here is a full 170 away.
    sl = risk.apply_sl(entry=24000, raw_sl=23830, direction="long", buffer=5.0, max_points=40.0)
    assert sl == 24000 - 40.0, "long sl should be capped at max_points from entry"


def test_apply_sl_caps_short():
    sl = risk.apply_sl(entry=24000, raw_sl=24185, direction="short", buffer=5.0, max_points=40.0)
    assert sl == 24000 + 40.0, "short sl should be capped at max_points from entry"


def test_apply_sl_leaves_in_range_stop_untouched():
    # a normal 15-point-away stop plus a 5-point buffer = 20 points, well
    # inside a 40-point cap -> should pass through unchanged.
    sl = risk.apply_sl(entry=24000, raw_sl=23985, direction="long", buffer=5.0, max_points=40.0)
    assert sl == 23985 - 5.0
    assert (24000 - sl) < 40.0


def test_apply_sl_none_max_points_is_inert():
    sl = risk.apply_sl(entry=24000, raw_sl=23830, direction="long", buffer=5.0, max_points=None)
    assert sl == 23830 - 5.0, "max_points=None must reproduce the buffer-only behavior"


def test_strategy1_gap_sar_gets_capped():
    # SAR sitting 170 points below entry, mirroring the live 09-08/09
    # overnight-gap case that motivated this cap.
    row = pd.Series(
        {"open": 24000, "high": 24010, "low": 23999, "close": 24005,
         "ha_color": "bullish", "sar": 23835, "rsi": 60}
    )
    row.name = pd.Timestamp("2024-01-01 09:15")

    uncapped = strategy._detect_setup(row, sl_buffer=5.0, max_sl_points=None)
    capped = strategy._detect_setup(row, sl_buffer=5.0, max_sl_points=40.0)

    assert uncapped["trigger"] - uncapped["sl"] > 40.0, "uncapped case should reproduce the ballooned stop"
    assert capped["trigger"] - capped["sl"] == 40.0, "capped case should be pulled in to exactly max_sl_points"
    assert capped["trigger"] == uncapped["trigger"], "capping must not move the entry trigger"
    # target1/target2 are RR multiples of the (now smaller) risk, so they
    # should sit closer to entry too, not further.
    assert capped["target2"] < uncapped["target2"]
    print("strategy1 gap-SAR case OK: sl capped, trigger untouched, targets shrink with it.")


def main():
    test_apply_sl_caps_long()
    test_apply_sl_caps_short()
    test_apply_sl_leaves_in_range_stop_untouched()
    test_apply_sl_none_max_points_is_inert()
    test_strategy1_gap_sar_gets_capped()
    print("\nMAX_SL_POINTS sanity checks OK.")


if __name__ == "__main__":
    main()
