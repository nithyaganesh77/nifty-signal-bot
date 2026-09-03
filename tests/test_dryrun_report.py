"""
Synthetic dry run for the end-of-day report (build_daily_report in
main.py). _collect_daily_events() itself needs live network data (it
calls data_feed.get_closed_bars), so this exercises build_daily_report()
directly with hand-built event lists instead — the same shape
strategy*.simulate() produces.

Run: python tests/test_dryrun_report.py
"""

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as bot_main


def main():
    report_date = dt.date(2026, 8, 24)

    events_by_strategy = {
        # strat1: 1 entry -> target1 (partial, not counted) -> target2 (win)
        "strat1": [
            {"type": "entry", "ts": _ts(report_date, "09:30")},
            {"type": "target1_hit", "ts": _ts(report_date, "09:36")},
            {"type": "target2_hit", "ts": _ts(report_date, "09:42")},
        ],
        # strat2: 1 entry -> stoploss (loss)
        "strat2": [
            {"type": "entry", "ts": _ts(report_date, "10:05")},
            {"type": "stoploss_hit", "ts": _ts(report_date, "10:09")},
        ],
        # strat3: no activity today
        "strat3": [],
        # strat4: 2 entries -> 1 target_hit (win), 1 time_exit (neutral)
        "strat4": [
            {"type": "entry", "ts": _ts(report_date, "09:20")},
            {"type": "target_hit", "ts": _ts(report_date, "09:24")},
            {"type": "entry", "ts": _ts(report_date, "11:00")},
            {"type": "time_exit", "ts": _ts(report_date, "11:10")},
        ],
        # strat5: 3 entries, 3 stoploss (worst accuracy, most SL)
        "strat5": [
            {"type": "entry", "ts": _ts(report_date, "09:25")},
            {"type": "stoploss_hit", "ts": _ts(report_date, "09:30")},
            {"type": "entry", "ts": _ts(report_date, "09:40")},
            {"type": "stoploss_hit", "ts": _ts(report_date, "09:45")},
            {"type": "entry", "ts": _ts(report_date, "09:55")},
            {"type": "stoploss_hit", "ts": _ts(report_date, "10:00")},
        ],
        # strat9: 1 entry -> target1 (partial, not counted) -> target2 (win)
        "strat9": [
            {"type": "entry", "ts": _ts(report_date, "13:00")},
            {"type": "target1_hit", "ts": _ts(report_date, "13:10")},
            {"type": "target2_hit", "ts": _ts(report_date, "13:20")},
        ],
        # strat8: Supertrend-flip exits, already pre-classified win/loss by P&L
        "strat8": [
            {"type": "entry", "ts": _ts(report_date, "09:35")},
            {"type": "target_hit", "ts": _ts(report_date, "10:15")},
        ],
    }

    report = bot_main.build_daily_report(events_by_strategy, "NIFTY 50", report_date)
    print(report)

    assert "2026-08-24" in report
    assert "Strategy 1" in report and "Strategy 5" in report and "Strategy 9" in report
    assert "Strategy 3" not in report, "strategy with zero events should be omitted"
    assert "Total" in report
    assert "Best accuracy" in report
    assert "Lowest accuracy" in report, "a tied 0% accuracy strategy should still be flagged as lowest"
    assert "Most stop-losses" in report and "Strategy 5" in report.split("Most stop-losses")[1].split("\n")[0]
    assert "Overall accuracy" in report
    print("\nDRY RUN OK — daily report formatting and analysis lines all present as expected.")

    # empty day -> "no entries" message, not a crash
    empty_report = bot_main.build_daily_report({}, "NIFTY 50", report_date)
    assert "No entries" in empty_report
    print("Empty-day report OK.")


def _ts(date, hhmm):
    import pandas as pd
    h, m = (int(x) for x in hhmm.split(":"))
    return pd.Timestamp(date.year, date.month, date.day, h, m, tz="Asia/Kolkata")


if __name__ == "__main__":
    main()
