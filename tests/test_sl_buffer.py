"""
Sanity check for SL_BUFFER_POINTS (config.py): confirms that passing a
non-zero sl_buffer actually pushes the stop-loss further from entry (and,
for strategies whose target is an RR-multiple of the stop distance,
widens the target too) versus buffer=0 (the old book-literal behavior),
without changing which bar the entry fires on.

Uses strategy.py (strategy 1) and strategy4.py (strategy 4) as
representative cases: one whose sl is SAR-based, one whose sl is
candle-low/high-based.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import strategy
import strategy4


def _mk_frame(rows: list[dict]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01 09:15", periods=len(rows), freq="3min")
    df = pd.DataFrame(rows, index=idx)
    return df


def test_strategy1_buffer_widens_sl_and_targets():
    row = pd.Series(
        {"open": 100, "high": 105, "low": 99, "close": 104, "ha_color": "bullish", "sar": 98, "rsi": 60}
    )
    row.name = pd.Timestamp("2024-01-01 09:15")

    no_buf = strategy._detect_setup(row, sl_buffer=0.0)
    buf = strategy._detect_setup(row, sl_buffer=5.0)

    assert no_buf["sl"] == 98.0
    assert buf["sl"] == 93.0, "long sl should move 5 points further away (down)"
    assert buf["target1"] > no_buf["target1"]
    assert buf["target2"] > no_buf["target2"]
    assert buf["trigger"] == no_buf["trigger"], "entry trigger must be unchanged"
    print("strategy1 buffer OK: sl/targets widen, trigger untouched.")


def test_strategy4_buffer_widens_sl_only_via_run():
    rng = np.random.default_rng(7)
    rows = []
    price = 24000.0
    # trend-up warmup so EMA/trend regime forms
    for _ in range(40):
        price += 3
        rows.append({"open": price - 1, "high": price + 1, "low": price - 2, "close": price})
    # tight consolidation
    for _ in range(6):
        rows.append({"open": price, "high": price + 2, "low": price - 2, "close": price + 0.5})
    # breakout candle
    price += 20
    rows.append({"open": price - 20, "high": price + 1, "low": price - 21, "close": price})
    for _ in range(5):
        price += 1
        rows.append({"open": price - 1, "high": price + 1, "low": price - 1, "close": price})

    import indicators

    bars = _mk_frame(rows)
    ind_df = indicators.build_indicator_frame_consolidation(bars).dropna(
        subset=["atr", "range_high", "range_low"]
    )

    events_no_buf = strategy4.simulate(ind_df, sl_buffer=0.0)
    events_buf = strategy4.simulate(ind_df, sl_buffer=5.0)

    entries_no_buf = [e for e in events_no_buf if e["type"] == "entry"]
    entries_buf = [e for e in events_buf if e["type"] == "entry"]

    assert len(entries_no_buf) >= 1 and len(entries_buf) >= 1, "expected a breakout entry in both runs"
    e0, e1 = entries_no_buf[0], entries_buf[0]
    assert e0["entry"] == e1["entry"], "buffer must not change the entry price"
    assert e0["entry_ts"] == e1["entry_ts"], "buffer must not change which bar enters"
    if e0["direction"] == "long":
        assert e1["sl"] < e0["sl"], "buffer should push a long sl further down"
        assert e1["target"] > e0["target"], "wider risk -> proportionally wider RR target"
    else:
        assert e1["sl"] > e0["sl"], "buffer should push a short sl further up"
        assert e1["target"] < e0["target"], "wider risk -> proportionally wider RR target"
    print("strategy4 buffer OK: entry unchanged, sl widened, RR target widened proportionally.")


def main():
    test_strategy1_buffer_widens_sl_and_targets()
    test_strategy4_buffer_widens_sl_only_via_run()
    print("\nSL_BUFFER_POINTS sanity checks OK.")


if __name__ == "__main__":
    main()
