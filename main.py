"""
Entry point: polls Yahoo Finance for Nifty 50 candles during NSE market
hours and runs all thirteen strategies on every newly closed candle,
sending Telegram messages for setups / entries / exits.

  Strategy 1: Heiken Ashi + Parabolic SAR + RSI, 3-minute candles
  Strategy 2: RSI Divergence + Bollinger Bands, 1-minute candles
  Strategy 3: RSI + VWAP Scalping, 1-minute candles
  Strategy 4: 1-Minute Consolidation Breakout Scalping, 1-minute candles
  Strategy 5: Moving Average Scalping, 5-minute candles, first hour only
  Strategy 6: Mean Reversion EMA(5,14) + Martingale sizing, 1-minute candles
  Strategy 7: Moving Average + Fibonacci, 5-minute candles
  Strategy 8: Supertrend + Pivot Points, 5-minute candles
  Strategy 9: VWAP + Standard Deviations, 5-minute candles
  Strategy 10: RSI + Volume Oscillator, 5-minute candles
  Strategy 11: Pullback + Pivot Points, 5-minute candles
  Strategy 12: Double RSI (5-min + hourly), 5-minute candles
  Strategy 13: CPR with Trend Following, 5-minute candles

Also sends a Telegram end-of-day report shortly after MARKET_CLOSE:
entries/TP/SL per strategy, accuracy (win rate), which strategy hit the
most SL, which hit the most TP, and which had the best/worst accuracy.

Any of the thirteen can be switched off via STRATEGY1_ENABLED ...
STRATEGY13_ENABLED in .env. Run:

    python main.py

Runs forever (until Ctrl-C or the process is killed) — see README.md for
how to keep it running unattended (systemd, screen/tmux, or a small VPS).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
import time

import pandas as pd

import config
import data_feed
import indicators
import strategy
import strategy3
import strategy4
import strategy5
import strategy6
import strategy7
import strategy8
import strategy9
import strategy10
import strategy11
import strategy12
import strategy13
import strategy_rsi_bb
from telegram_bot import (
    TelegramNotifier,
    format_event,
    format_event_bb,
    format_event_consolidation,
    format_event_cpr,
    format_event_double_rsi,
    format_event_ma,
    format_event_ma_fib,
    format_event_meanrev,
    format_event_pivot_pullback,
    format_event_rsi_volosc,
    format_event_supertrend,
    format_event_vwap,
    format_event_vwap_std,
)

IST = data_feed.IST

# A plain logging.StreamHandler() defaults to stderr — Railway (and most
# host log viewers) then tag EVERY line "error" based on the stream alone,
# ignoring the actual [INFO]/[WARNING] text inside it. Split by level
# instead: INFO/DEBUG go to stdout (shown as normal), WARNING+ go to
# stderr (so real problems still get flagged) — same content either way,
# just correctly labeled in the host's UI.
_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setLevel(logging.DEBUG)
_stdout_handler.addFilter(lambda record: record.levelno < logging.WARNING)
_stdout_handler.setFormatter(_formatter)

_stderr_handler = logging.StreamHandler(sys.stderr)
_stderr_handler.setLevel(logging.WARNING)
_stderr_handler.setFormatter(_formatter)

_file_handler = logging.FileHandler(config.LOG_FILE)
_file_handler.setFormatter(_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[_stdout_handler, _stderr_handler, _file_handler],
)
logger = logging.getLogger("main")

# RL-style reward/penalty per event type — a "win" (target hit) adds to a
# strategy's cumulative score, a "loss" (stop-loss hit, post-entry only)
# subtracts. The running total is persisted in that strategy's state file.
REWARD_MAP_STRAT1 = {
    "target1_hit": config.REWARD_TARGET1,
    "target2_hit": config.REWARD_TARGET2,
    "stoploss_hit": -config.PENALTY_STOPLOSS,
}
REWARD_MAP_STRAT2 = {
    "target_hit": config.REWARD_TARGET,
    "stoploss_hit": -config.PENALTY_STOPLOSS,
}
REWARD_MAP_STRAT3 = {
    "target_hit": config.REWARD_TARGET,
    "stoploss_hit": -config.PENALTY_STOPLOSS,
}
REWARD_MAP_STRAT4 = {
    "target_hit": config.REWARD_TARGET,
    "stoploss_hit": -config.PENALTY_STOPLOSS,
    # time_exit isn't scored: it can close in profit or loss depending on
    # where price sits at the 10-minute mark, which isn't a clean win/loss
}
REWARD_MAP_STRAT5 = {
    "target_hit": config.REWARD_TARGET,
    "stoploss_hit": -config.PENALTY_STOPLOSS,
}
REWARD_MAP_STRAT6 = {
    "target_hit": config.REWARD_TARGET,
    "stoploss_hit": -config.PENALTY_STOPLOSS,
}
REWARD_MAP_STRAT7 = {
    "target_hit": config.REWARD_TARGET,
    "stoploss_hit": -config.PENALTY_STOPLOSS,
}
REWARD_MAP_STRAT8 = {
    # win/loss is decided by P&L at the Supertrend-flip exit (see
    # strategy8.py), so both come through as target_hit/stoploss_hit already
    "target_hit": config.REWARD_TARGET,
    "stoploss_hit": -config.PENALTY_STOPLOSS,
}
REWARD_MAP_STRAT9 = {
    "target1_hit": config.REWARD_TARGET1,
    "target2_hit": config.REWARD_TARGET2,
    "stoploss_hit": -config.PENALTY_STOPLOSS,
}
REWARD_MAP_STRAT10 = {
    "target_hit": config.REWARD_TARGET,
    "stoploss_hit": -config.PENALTY_STOPLOSS,
}
REWARD_MAP_STRAT11 = {
    "target_hit": config.REWARD_TARGET,
    "stoploss_hit": -config.PENALTY_STOPLOSS,
}
REWARD_MAP_STRAT12 = {
    # win/loss decided by P&L at the RSI-pivot exit (see strategy12.py)
    "target_hit": config.REWARD_TARGET,
    "stoploss_hit": -config.PENALTY_STOPLOSS,
}
REWARD_MAP_STRAT13 = {
    "target_hit": config.REWARD_TARGET,
    "stoploss_hit": -config.PENALTY_STOPLOSS,
}


def apply_reward(state: dict, event: dict, reward_map: dict) -> tuple[dict, float]:
    """
    Update state["score"] for a reward-bearing event and return
    (new_state, delta) — delta is 0.0 for events with no reward mapped.
    """
    delta = reward_map.get(event["type"], 0.0)
    if delta:
        score = state.get("score", 0.0) + delta
        state = {**state, "score": score}
    return state, delta


def apply_martingale(state: dict, event: dict, max_multiplier: float) -> tuple[dict, float]:
    """
    Strategy 6's Martingale position-size overlay: returns
    (new_state, multiplier_for_this_event) where the multiplier is the
    one that was ACTIVE going into this event (i.e. the size to use for
    an "entry"). A stop-loss doubles the multiplier for the *next* trade
    (capped at max_multiplier); a target hit resets it to 1x — mirroring
    "put net profit aside" in the write-up. This is purely a sizing
    suggestion shown in the Telegram message — the bot doesn't place
    orders or track real capital.
    """
    mult = state.get("martingale_multiplier", 1.0)
    if event["type"] == "stoploss_hit":
        state = {**state, "martingale_multiplier": min(mult * 2.0, max_multiplier)}
    elif event["type"] == "target_hit":
        state = {**state, "martingale_multiplier": 1.0}
    return state, mult


def load_json_state(path: str, fresh_fn) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            merged = fresh_fn()
            merged.update(data)
            return merged
        except (json.JSONDecodeError, OSError):
            logger.exception("Could not read state file %s, starting fresh", path)
    return fresh_fn()


def save_json_state(path: str, state: dict) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, path)


def in_market_hours(now: dt.datetime) -> bool:
    if now.weekday() >= 5:  # Sat/Sun
        return False
    open_h, open_m = (int(x) for x in config.MARKET_OPEN.split(":"))
    close_h, close_m = (int(x) for x in config.MARKET_CLOSE.split(":"))
    open_t = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    close_t = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    return open_t <= now <= close_t
    # NOTE: this does not account for NSE trading holidays. On a holiday
    # the bot will just find no new data from yfinance and idle quietly.


def is_after_market_close(now: dt.datetime) -> bool:
    if now.weekday() >= 5:
        return False
    close_h, close_m = (int(x) for x in config.MARKET_CLOSE.split(":"))
    close_t = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    return now >= close_t


# --- End-of-day report ------------------------------------------------------
#
# Rather than tallying counts incrementally as events stream in (which
# would be lost on a restart), the report does a fresh, pure replay of
# each enabled strategy's simulate() over the day's bars and keeps only
# the events that happened today. This can't drift from what was
# actually alerted (same simulate() function run() uses) and needs no
# extra persisted state.

STRAT_LABELS = {
    "strat1": "Strategy 1 (HA+SAR+RSI)",
    "strat2": "Strategy 2 (RSI-Div+BB)",
    "strat3": "Strategy 3 (RSI+VWAP)",
    "strat4": "Strategy 4 (Consolidation Breakout)",
    "strat5": "Strategy 5 (MA Scalping)",
    "strat6": "Strategy 6 (Mean Reversion+Martingale)",
    "strat7": "Strategy 7 (MA+Fibonacci)",
    "strat8": "Strategy 8 (Supertrend+Pivots)",
    "strat9": "Strategy 9 (VWAP+StdDev)",
    "strat10": "Strategy 10 (RSI+Volume Osc)",
    "strat11": "Strategy 11 (Pullback+Pivots)",
    "strat12": "Strategy 12 (Double RSI)",
    "strat13": "Strategy 13 (CPR+Trend)",
}
# which event type counts as a "win" (target hit) for each strategy —
# strategy 1/9's target1_hit is only a partial booking, not a trade close,
# so target2_hit (the final exit) is the one that counts here.
WIN_EVENT_TYPE = {
    "strat1": "target2_hit",
    "strat2": "target_hit",
    "strat3": "target_hit",
    "strat4": "target_hit",
    "strat5": "target_hit",
    "strat6": "target_hit",
    "strat7": "target_hit",
    "strat8": "target_hit",
    "strat9": "target2_hit",
    "strat10": "target_hit",
    "strat11": "target_hit",
    "strat12": "target_hit",
    "strat13": "target_hit",
}
LOSS_EVENT_TYPE = "stoploss_hit"  # same for every strategy
# events that close a trade but aren't a clean win/loss (excluded from
# the accuracy/win-rate denominator)
NEUTRAL_EVENT_TYPE = {"strat4": "time_exit"}


def _collect_daily_events(report_date: dt.date) -> dict:
    """
    For each enabled strategy, fetch its bars, replay simulate() (the
    same pure function run() uses internally), and keep only events
    whose timestamp falls on report_date.
    """
    results: dict[str, list[dict]] = {}

    if config.STRATEGY1_ENABLED:
        bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES)
        if not bars.empty:
            ind_df = indicators.build_indicator_frame(
                bars, af_start=config.SAR_START, af_step=config.SAR_STEP,
                af_max=config.SAR_MAX, rsi_length=config.RSI_LENGTH,
            ).dropna(subset=["rsi", "sar"])
            events = strategy.simulate(ind_df, sl_buffer=config.SL_BUFFER_POINTS) if not ind_df.empty else []
            results["strat1"] = [e for e in events if e["ts"].date() == report_date]

    if config.STRATEGY2_ENABLED:
        bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_2)
        if not bars.empty:
            ind_df = indicators.build_indicator_frame_bb(
                bars, bb_length=config.BB_LENGTH, bb_mult=config.BB_MULT,
                rsi_length=config.RSI_LENGTH, pivot_left=config.PIVOT_LEFT,
                pivot_right=config.PIVOT_RIGHT,
            ).dropna(subset=["rsi", "bb_upper", "bb_lower"])
            events = strategy_rsi_bb.simulate(ind_df, sl_buffer=config.SL_BUFFER_POINTS) if not ind_df.empty else []
            results["strat2"] = [e for e in events if e["ts"].date() == report_date]

    if config.STRATEGY3_ENABLED:
        bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_3)
        if not bars.empty:
            ind_df = indicators.build_indicator_frame_vwap(
                bars, rsi_length=config.RSI_LENGTH, recent_window=config.VWAP_RECENT_WINDOW,
                rsi_oversold=config.RSI_OVERSOLD, rsi_overbought=config.RSI_OVERBOUGHT,
            ).dropna(subset=["rsi", "vwap"])
            events = (
                strategy3.simulate(
                    ind_df, target_band=config.VWAP_TARGET_BAND, sl_buffer=config.SL_BUFFER_POINTS
                )
                if not ind_df.empty else []
            )
            results["strat3"] = [e for e in events if e["ts"].date() == report_date]

    if config.STRATEGY4_ENABLED:
        bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_4)
        if not bars.empty:
            ind_df = indicators.build_indicator_frame_consolidation(
                bars, ema_length=config.EMA_LENGTH, trend_lookback=config.TREND_LOOKBACK,
                range_bars=config.RANGE_BARS, atr_length=config.ATR_LENGTH,
            ).dropna(subset=["atr", "range_high", "range_low"])
            events = (
                strategy4.simulate(
                    ind_df, target_rr=config.TARGET_RR, time_exit_bars=config.TIME_EXIT_BARS,
                    max_atr_mult=config.CONSOLIDATION_MAX_ATR_MULT, sl_buffer=config.SL_BUFFER_POINTS,
                )
                if not ind_df.empty else []
            )
            results["strat4"] = [e for e in events if e["ts"].date() == report_date]

    if config.STRATEGY5_ENABLED:
        bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_5)
        if not bars.empty:
            ind_df = indicators.build_indicator_frame_ma(
                bars, ema_length=config.EMA_LENGTH_5, market_open=config.MARKET_OPEN,
                first_hour_end=config.FIRST_HOUR_END,
            ).dropna(subset=["ema"])
            events = (
                strategy5.simulate(ind_df, target_rr=config.TARGET_RR_5, sl_buffer=config.SL_BUFFER_POINTS)
                if not ind_df.empty else []
            )
            results["strat5"] = [e for e in events if e["ts"].date() == report_date]

    if config.STRATEGY6_ENABLED:
        bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_6)
        if not bars.empty:
            ind_df = indicators.build_indicator_frame_meanrev(
                bars, ema_fast=config.EMA_FAST_6, ema_slow=config.EMA_SLOW_6,
            ).dropna(subset=["ema_fast", "ema_slow"])
            events = (
                strategy6.simulate(ind_df, target_rr=config.TARGET_RR_6, sl_buffer=config.SL_BUFFER_POINTS)
                if not ind_df.empty else []
            )
            results["strat6"] = [e for e in events if e["ts"].date() == report_date]

    if config.STRATEGY7_ENABLED:
        bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_7)
        if not bars.empty:
            ind_df = indicators.build_indicator_frame_ma_fib(
                bars, sma_length=config.SMA_LENGTH_7, pivot_left=config.PIVOT_LEFT_7,
                pivot_right=config.PIVOT_RIGHT_7, ma_slope_lookback=config.MA_SLOPE_LOOKBACK_7,
            ).dropna(subset=["sma200"])
            events = (
                strategy7.simulate(ind_df, target_rr=config.TARGET_RR_7, sl_buffer=config.SL_BUFFER_POINTS)
                if not ind_df.empty else []
            )
            results["strat7"] = [e for e in events if e["ts"].date() == report_date]

    if config.STRATEGY8_ENABLED:
        bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_8)
        if not bars.empty:
            ind_df = indicators.build_indicator_frame_supertrend_pivot(
                bars, atr_length=config.ATR_LENGTH_8, st_mult=config.SUPERTREND_MULT_8,
            ).dropna(subset=["supertrend", "r1", "s1"])
            events = strategy8.simulate(ind_df, sl_buffer=config.SL_BUFFER_POINTS) if not ind_df.empty else []
            results["strat8"] = [e for e in events if e["ts"].date() == report_date]

    if config.STRATEGY9_ENABLED:
        bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_9)
        if not bars.empty:
            ind_df = indicators.build_indicator_frame_vwap_std(
                bars, band_mult=config.VWAP_BAND_MULT_9,
            ).dropna(subset=["vwap", "vwap_upper", "vwap_lower"])
            events = strategy9.simulate(ind_df, sl_buffer=config.SL_BUFFER_POINTS) if not ind_df.empty else []
            results["strat9"] = [e for e in events if e["ts"].date() == report_date]

    if config.STRATEGY10_ENABLED:
        bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_10)
        if not bars.empty:
            ind_df = indicators.build_indicator_frame_rsi_volosc(
                bars, rsi_length=config.RSI_LENGTH, vo_fast=config.VOL_OSC_FAST_10,
                vo_slow=config.VOL_OSC_SLOW_10, pivot_left=config.PIVOT_LEFT_10,
                pivot_right=config.PIVOT_RIGHT_10,
            ).dropna(subset=["rsi", "vol_osc"])
            events = (
                strategy10.simulate(ind_df, target_rr=config.TARGET_RR_10, sl_buffer=config.SL_BUFFER_POINTS)
                if not ind_df.empty else []
            )
            results["strat10"] = [e for e in events if e["ts"].date() == report_date]

    if config.STRATEGY11_ENABLED:
        bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_11)
        if not bars.empty:
            ind_df = indicators.build_indicator_frame_pivot_pullback(bars).dropna(subset=["p"])
            events = (
                strategy11.simulate(ind_df, target_rr=config.TARGET_RR_11, sl_buffer=config.SL_BUFFER_POINTS)
                if not ind_df.empty else []
            )
            results["strat11"] = [e for e in events if e["ts"].date() == report_date]

    if config.STRATEGY12_ENABLED:
        bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_12)
        if not bars.empty:
            ind_df = indicators.build_indicator_frame_double_rsi(
                bars, rsi_length=config.RSI_LENGTH,
            ).dropna(subset=["rsi_fast", "rsi_slow"])
            events = strategy12.simulate(ind_df, sl_buffer=config.SL_BUFFER_POINTS) if not ind_df.empty else []
            results["strat12"] = [e for e in events if e["ts"].date() == report_date]

    if config.STRATEGY13_ENABLED:
        bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_13)
        if not bars.empty:
            ind_df = indicators.build_indicator_frame_cpr(
                bars, atr_length=config.ATR_LENGTH_13, narrow_atr_mult=config.CPR_NARROW_ATR_MULT_13,
            ).dropna(subset=["p", "atr"])
            events = (
                strategy13.simulate(ind_df, target_rr=config.TARGET_RR_13, sl_buffer=config.SL_BUFFER_POINTS)
                if not ind_df.empty else []
            )
            results["strat13"] = [e for e in events if e["ts"].date() == report_date]

    return results


def build_daily_report(events_by_strategy: dict, symbol_label: str, report_date: dt.date) -> str:
    lines = [f"📋 *{symbol_label} — Daily Report ({report_date.strftime('%Y-%m-%d')})*", ""]

    rows = []
    any_activity = False
    for key, label in STRAT_LABELS.items():
        events = events_by_strategy.get(key, [])
        if not events:
            continue
        counts: dict[str, int] = {}
        for e in events:
            counts[e["type"]] = counts.get(e["type"], 0) + 1

        wins = counts.get(WIN_EVENT_TYPE[key], 0)
        losses = counts.get(LOSS_EVENT_TYPE, 0)
        neutral_type = NEUTRAL_EVENT_TYPE.get(key)
        neutrals = counts.get(neutral_type, 0) if neutral_type else 0
        entries = counts.get("entry", 0)
        decided = wins + losses
        accuracy = (wins / decided * 100.0) if decided > 0 else None

        if entries or wins or losses or neutrals:
            any_activity = True
        rows.append(
            {
                "key": key, "label": label, "entries": entries, "wins": wins,
                "losses": losses, "neutrals": neutrals, "accuracy": accuracy,
            }
        )

    if not any_activity:
        lines.append("No entries triggered by any strategy today.")
        return "\n".join(lines)

    total_entries = sum(r["entries"] for r in rows)
    total_wins = sum(r["wins"] for r in rows)
    total_losses = sum(r["losses"] for r in rows)

    for r in rows:
        acc_str = f"{r['accuracy']:.0f}%" if r["accuracy"] is not None else "—"
        extra = f", {r['neutrals']} time-exit" if r["neutrals"] else ""
        lines.append(
            f"*{r['label']}*\n"
            f"  {r['entries']} entries — ✅ {r['wins']} TP / ❌ {r['losses']} SL{extra} "
            f"(accuracy: {acc_str})"
        )

    lines.append("")
    lines.append(f"*Total*: {total_entries} entries — ✅ {total_wins} TP / ❌ {total_losses} SL")

    decided_rows = [r for r in rows if r["accuracy"] is not None]
    if decided_rows:
        best = max(decided_rows, key=lambda r: r["accuracy"])
        worst = min(decided_rows, key=lambda r: r["accuracy"])
        lines.append(f"\n🎯 Best accuracy: {best['label']} ({best['accuracy']:.0f}%)")
        if worst["key"] != best["key"]:
            lines.append(f"⚠️ Lowest accuracy: {worst['label']} ({worst['accuracy']:.0f}%)")

    sl_rows = [r for r in rows if r["losses"] > 0]
    if sl_rows:
        most_sl = max(sl_rows, key=lambda r: r["losses"])
        lines.append(f"🔴 Most stop-losses: {most_sl['label']} ({most_sl['losses']} SL)")

    tp_rows = [r for r in rows if r["wins"] > 0]
    if tp_rows:
        most_tp = max(tp_rows, key=lambda r: r["wins"])
        lines.append(f"🟢 Most targets hit: {most_tp['label']} ({most_tp['wins']} TP)")

    if (total_wins + total_losses) > 0:
        overall = total_wins / (total_wins + total_losses) * 100.0
        lines.append(f"\n📊 Overall accuracy across all strategies: {overall:.0f}%")

    return "\n".join(lines)


def poll_strategy1(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES)
    if bars.empty or len(bars) < max(config.RSI_LENGTH, 10) + 5:
        logger.debug("[strat1] Not enough closed bars yet (%d) — waiting.", len(bars))
        return state

    ind_df = indicators.build_indicator_frame(
        bars,
        af_start=config.SAR_START,
        af_step=config.SAR_STEP,
        af_max=config.SAR_MAX,
        rsi_length=config.RSI_LENGTH,
    )
    ind_df = ind_df.dropna(subset=["rsi", "sar"])
    if ind_df.empty:
        return state

    new_state, events = strategy.run(state, ind_df, sl_buffer=config.SL_BUFFER_POINTS)

    for event in events:
        new_state, delta = apply_reward(new_state, event, REWARD_MAP_STRAT1)
        msg = format_event(config.SYMBOL_LABEL, event)
        if delta:
            sign = "🏆 Reward" if delta > 0 else "💀 Penalty"
            msg += f"\n{sign}: {delta:+.2f} | Cumulative score: {new_state['score']:+.2f}"
        logger.info("[strat1] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat1] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE, new_state)
    return new_state


def poll_strategy2(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_2)
    min_needed = max(config.BB_LENGTH, config.RSI_LENGTH) + config.PIVOT_LEFT + config.PIVOT_RIGHT + 5
    if bars.empty or len(bars) < min_needed:
        logger.debug("[strat2] Not enough closed bars yet (%d) — waiting.", len(bars))
        return state

    ind_df = indicators.build_indicator_frame_bb(
        bars,
        bb_length=config.BB_LENGTH,
        bb_mult=config.BB_MULT,
        rsi_length=config.RSI_LENGTH,
        pivot_left=config.PIVOT_LEFT,
        pivot_right=config.PIVOT_RIGHT,
    )
    ind_df = ind_df.dropna(subset=["rsi", "bb_upper", "bb_lower"])
    if ind_df.empty:
        return state

    new_state, events = strategy_rsi_bb.run(state, ind_df, sl_buffer=config.SL_BUFFER_POINTS)

    for event in events:
        new_state, delta = apply_reward(new_state, event, REWARD_MAP_STRAT2)
        msg = format_event_bb(config.SYMBOL_LABEL, event)
        if delta:
            sign = "🏆 Reward" if delta > 0 else "💀 Penalty"
            msg += f"\n{sign}: {delta:+.2f} | Cumulative score: {new_state['score']:+.2f}"
        logger.info("[strat2] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat2] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE_2, new_state)
    return new_state


def poll_strategy3(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_3)
    min_needed = max(config.RSI_LENGTH, config.VWAP_RECENT_WINDOW) + 5
    if bars.empty or len(bars) < min_needed:
        logger.debug("[strat3] Not enough closed bars yet (%d) — waiting.", len(bars))
        return state

    ind_df = indicators.build_indicator_frame_vwap(
        bars,
        rsi_length=config.RSI_LENGTH,
        recent_window=config.VWAP_RECENT_WINDOW,
        rsi_oversold=config.RSI_OVERSOLD,
        rsi_overbought=config.RSI_OVERBOUGHT,
    )
    ind_df = ind_df.dropna(subset=["rsi", "vwap"])
    if ind_df.empty:
        return state

    # ^NSEI (and most index tickers) often report zero volume on
    # yfinance — session_vwap() falls back to an equal-weighted running
    # average in that case (see indicators.session_vwap docstring). Warn
    # once so it isn't a silent surprise, without spamming every poll.
    if not state.get("_warned_volume_fallback") and bool(ind_df["used_volume_fallback"].any()):
        logger.warning(
            "[strat3] %s reports zero volume — VWAP is using an equal-weighted "
            "fallback instead of true volume weighting. Consider pointing SYMBOL "
            "at a ticker with real volume (a stock or futures contract) for a "
            "more faithful VWAP.",
            config.SYMBOL,
        )
        state = {**state, "_warned_volume_fallback": True}

    new_state, events = strategy3.run(
        state, ind_df, target_band=config.VWAP_TARGET_BAND, sl_buffer=config.SL_BUFFER_POINTS
    )

    for event in events:
        new_state, delta = apply_reward(new_state, event, REWARD_MAP_STRAT3)
        msg = format_event_vwap(config.SYMBOL_LABEL, event)
        if delta:
            sign = "🏆 Reward" if delta > 0 else "💀 Penalty"
            msg += f"\n{sign}: {delta:+.2f} | Cumulative score: {new_state['score']:+.2f}"
        logger.info("[strat3] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat3] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE_3, new_state)
    return new_state


def poll_strategy4(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_4)
    min_needed = max(config.EMA_LENGTH + config.TREND_LOOKBACK, config.ATR_LENGTH, config.RANGE_BARS) + 5
    if bars.empty or len(bars) < min_needed:
        logger.debug("[strat4] Not enough closed bars yet (%d) — waiting.", len(bars))
        return state

    ind_df = indicators.build_indicator_frame_consolidation(
        bars,
        ema_length=config.EMA_LENGTH,
        trend_lookback=config.TREND_LOOKBACK,
        range_bars=config.RANGE_BARS,
        atr_length=config.ATR_LENGTH,
    )
    ind_df = ind_df.dropna(subset=["atr", "range_high", "range_low"])
    if ind_df.empty:
        return state

    new_state, events = strategy4.run(
        state,
        ind_df,
        target_rr=config.TARGET_RR,
        time_exit_bars=config.TIME_EXIT_BARS,
        max_atr_mult=config.CONSOLIDATION_MAX_ATR_MULT,
        sl_buffer=config.SL_BUFFER_POINTS,
    )

    for event in events:
        new_state, delta = apply_reward(new_state, event, REWARD_MAP_STRAT4)
        msg = format_event_consolidation(config.SYMBOL_LABEL, event)
        if delta:
            sign = "🏆 Reward" if delta > 0 else "💀 Penalty"
            msg += f"\n{sign}: {delta:+.2f} | Cumulative score: {new_state['score']:+.2f}"
        logger.info("[strat4] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat4] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE_4, new_state)
    return new_state


def poll_strategy5(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_5)
    min_needed = config.EMA_LENGTH_5 + 15
    if bars.empty or len(bars) < min_needed:
        logger.debug("[strat5] Not enough closed bars yet (%d) — waiting.", len(bars))
        return state

    ind_df = indicators.build_indicator_frame_ma(
        bars,
        ema_length=config.EMA_LENGTH_5,
        market_open=config.MARKET_OPEN,
        first_hour_end=config.FIRST_HOUR_END,
    )
    ind_df = ind_df.dropna(subset=["ema"])
    if ind_df.empty:
        return state

    new_state, events = strategy5.run(
        state, ind_df, target_rr=config.TARGET_RR_5, sl_buffer=config.SL_BUFFER_POINTS
    )

    for event in events:
        new_state, delta = apply_reward(new_state, event, REWARD_MAP_STRAT5)
        msg = format_event_ma(config.SYMBOL_LABEL, event)
        if delta:
            sign = "🏆 Reward" if delta > 0 else "💀 Penalty"
            msg += f"\n{sign}: {delta:+.2f} | Cumulative score: {new_state['score']:+.2f}"
        logger.info("[strat5] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat5] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE_5, new_state)
    return new_state


def poll_strategy6(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_6)
    min_needed = config.EMA_SLOW_6 + 10
    if bars.empty or len(bars) < min_needed:
        logger.debug("[strat6] Not enough closed bars yet (%d) — waiting.", len(bars))
        return state

    ind_df = indicators.build_indicator_frame_meanrev(
        bars, ema_fast=config.EMA_FAST_6, ema_slow=config.EMA_SLOW_6
    )
    ind_df = ind_df.dropna(subset=["ema_fast", "ema_slow"])
    if ind_df.empty:
        return state

    new_state, events = strategy6.run(
        state, ind_df, target_rr=config.TARGET_RR_6, sl_buffer=config.SL_BUFFER_POINTS
    )

    for event in events:
        new_state, delta = apply_reward(new_state, event, REWARD_MAP_STRAT6)
        new_state, mult = apply_martingale(new_state, event, config.MARTINGALE_MAX_MULTIPLIER)
        msg = format_event_meanrev(config.SYMBOL_LABEL, event)
        if event["type"] == "entry":
            msg += f"\n♟️ Martingale position size: {mult:g}x"
        elif event["type"] == "stoploss_hit":
            msg += f"\n♟️ Martingale: next trade sizes up to {new_state['martingale_multiplier']:g}x"
        elif event["type"] == "target_hit":
            msg += "\n♟️ Martingale: reset — next trade back to 1x"
        if delta:
            sign = "🏆 Reward" if delta > 0 else "💀 Penalty"
            msg += f"\n{sign}: {delta:+.2f} | Cumulative score: {new_state['score']:+.2f}"
        logger.info("[strat6] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat6] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE_6, new_state)
    return new_state


def poll_strategy7(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_7)
    min_needed = config.SMA_LENGTH_7 + config.PIVOT_LEFT_7 + config.PIVOT_RIGHT_7 + 5
    if bars.empty or len(bars) < min_needed:
        logger.debug("[strat7] Not enough closed bars yet (%d) — waiting.", len(bars))
        return state

    ind_df = indicators.build_indicator_frame_ma_fib(
        bars,
        sma_length=config.SMA_LENGTH_7,
        pivot_left=config.PIVOT_LEFT_7,
        pivot_right=config.PIVOT_RIGHT_7,
        ma_slope_lookback=config.MA_SLOPE_LOOKBACK_7,
    )
    ind_df = ind_df.dropna(subset=["sma200"])
    if ind_df.empty:
        return state

    new_state, events = strategy7.run(
        state, ind_df, target_rr=config.TARGET_RR_7, sl_buffer=config.SL_BUFFER_POINTS
    )

    for event in events:
        new_state, delta = apply_reward(new_state, event, REWARD_MAP_STRAT7)
        msg = format_event_ma_fib(config.SYMBOL_LABEL, event)
        if delta:
            sign = "🏆 Reward" if delta > 0 else "💀 Penalty"
            msg += f"\n{sign}: {delta:+.2f} | Cumulative score: {new_state['score']:+.2f}"
        logger.info("[strat7] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat7] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE_7, new_state)
    return new_state


def poll_strategy8(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_8)
    min_needed = config.ATR_LENGTH_8 + 10
    if bars.empty or len(bars) < min_needed:
        logger.debug("[strat8] Not enough closed bars yet (%d) — waiting.", len(bars))
        return state

    ind_df = indicators.build_indicator_frame_supertrend_pivot(
        bars, atr_length=config.ATR_LENGTH_8, st_mult=config.SUPERTREND_MULT_8,
    )
    ind_df = ind_df.dropna(subset=["supertrend", "r1", "s1"])
    if ind_df.empty:
        return state

    new_state, events = strategy8.run(state, ind_df, sl_buffer=config.SL_BUFFER_POINTS)

    for event in events:
        new_state, delta = apply_reward(new_state, event, REWARD_MAP_STRAT8)
        msg = format_event_supertrend(config.SYMBOL_LABEL, event)
        if delta:
            sign = "🏆 Reward" if delta > 0 else "💀 Penalty"
            msg += f"\n{sign}: {delta:+.2f} | Cumulative score: {new_state['score']:+.2f}"
        logger.info("[strat8] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat8] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE_8, new_state)
    return new_state


def poll_strategy9(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_9)
    min_needed = 30
    if bars.empty or len(bars) < min_needed:
        logger.debug("[strat9] Not enough closed bars yet (%d) — waiting.", len(bars))
        return state

    ind_df = indicators.build_indicator_frame_vwap_std(bars, band_mult=config.VWAP_BAND_MULT_9)
    ind_df = ind_df.dropna(subset=["vwap", "vwap_upper", "vwap_lower"])
    if ind_df.empty:
        return state

    new_state, events = strategy9.run(state, ind_df, sl_buffer=config.SL_BUFFER_POINTS)

    for event in events:
        new_state, delta = apply_reward(new_state, event, REWARD_MAP_STRAT9)
        msg = format_event_vwap_std(config.SYMBOL_LABEL, event)
        if delta:
            sign = "🏆 Reward" if delta > 0 else "💀 Penalty"
            msg += f"\n{sign}: {delta:+.2f} | Cumulative score: {new_state['score']:+.2f}"
        logger.info("[strat9] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat9] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE_9, new_state)
    return new_state


def poll_strategy10(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_10)
    min_needed = max(config.RSI_LENGTH, config.VOL_OSC_SLOW_10) + 10
    if bars.empty or len(bars) < min_needed:
        logger.debug("[strat10] Not enough closed bars yet (%d) — waiting.", len(bars))
        return state

    ind_df = indicators.build_indicator_frame_rsi_volosc(
        bars,
        rsi_length=config.RSI_LENGTH,
        vo_fast=config.VOL_OSC_FAST_10,
        vo_slow=config.VOL_OSC_SLOW_10,
        pivot_left=config.PIVOT_LEFT_10,
        pivot_right=config.PIVOT_RIGHT_10,
    )
    ind_df = ind_df.dropna(subset=["rsi", "vol_osc"])
    if ind_df.empty:
        return state

    if not state.get("_warned_volume_fallback") and bool(ind_df["used_volume_fallback"].any()):
        logger.warning(
            "[strat10] %s reports zero volume — the Volume Oscillator will "
            "sit at 0 and this strategy will rarely fire. Consider pointing "
            "SYMBOL at a ticker with real volume for a faithful signal.",
            config.SYMBOL,
        )
        state = {**state, "_warned_volume_fallback": True}

    new_state, events = strategy10.run(
        state, ind_df, target_rr=config.TARGET_RR_10, sl_buffer=config.SL_BUFFER_POINTS
    )

    for event in events:
        new_state, delta = apply_reward(new_state, event, REWARD_MAP_STRAT10)
        msg = format_event_rsi_volosc(config.SYMBOL_LABEL, event)
        if delta:
            sign = "🏆 Reward" if delta > 0 else "💀 Penalty"
            msg += f"\n{sign}: {delta:+.2f} | Cumulative score: {new_state['score']:+.2f}"
        logger.info("[strat10] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat10] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE_10, new_state)
    return new_state


def poll_strategy11(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_11)
    min_needed = 10
    if bars.empty or len(bars) < min_needed:
        logger.debug("[strat11] Not enough closed bars yet (%d) — waiting.", len(bars))
        return state

    ind_df = indicators.build_indicator_frame_pivot_pullback(bars)
    ind_df = ind_df.dropna(subset=["p"])
    if ind_df.empty:
        return state

    new_state, events = strategy11.run(
        state, ind_df, target_rr=config.TARGET_RR_11, sl_buffer=config.SL_BUFFER_POINTS
    )

    for event in events:
        new_state, delta = apply_reward(new_state, event, REWARD_MAP_STRAT11)
        msg = format_event_pivot_pullback(config.SYMBOL_LABEL, event)
        if delta:
            sign = "🏆 Reward" if delta > 0 else "💀 Penalty"
            msg += f"\n{sign}: {delta:+.2f} | Cumulative score: {new_state['score']:+.2f}"
        logger.info("[strat11] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat11] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE_11, new_state)
    return new_state


def poll_strategy12(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_12)
    min_needed = config.RSI_LENGTH + 15
    if bars.empty or len(bars) < min_needed:
        logger.debug("[strat12] Not enough closed bars yet (%d) — waiting.", len(bars))
        return state

    ind_df = indicators.build_indicator_frame_double_rsi(bars, rsi_length=config.RSI_LENGTH)
    ind_df = ind_df.dropna(subset=["rsi_fast", "rsi_slow"])
    if ind_df.empty:
        return state

    new_state, events = strategy12.run(state, ind_df, sl_buffer=config.SL_BUFFER_POINTS)

    for event in events:
        new_state, delta = apply_reward(new_state, event, REWARD_MAP_STRAT12)
        msg = format_event_double_rsi(config.SYMBOL_LABEL, event)
        if delta:
            sign = "🏆 Reward" if delta > 0 else "💀 Penalty"
            msg += f"\n{sign}: {delta:+.2f} | Cumulative score: {new_state['score']:+.2f}"
        logger.info("[strat12] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat12] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE_12, new_state)
    return new_state


def poll_strategy13(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES_13)
    min_needed = config.ATR_LENGTH_13 + 10
    if bars.empty or len(bars) < min_needed:
        logger.debug("[strat13] Not enough closed bars yet (%d) — waiting.", len(bars))
        return state

    ind_df = indicators.build_indicator_frame_cpr(
        bars, atr_length=config.ATR_LENGTH_13, narrow_atr_mult=config.CPR_NARROW_ATR_MULT_13,
    )
    ind_df = ind_df.dropna(subset=["p", "atr"])
    if ind_df.empty:
        return state

    new_state, events = strategy13.run(
        state, ind_df, target_rr=config.TARGET_RR_13, sl_buffer=config.SL_BUFFER_POINTS
    )

    for event in events:
        new_state, delta = apply_reward(new_state, event, REWARD_MAP_STRAT13)
        msg = format_event_cpr(config.SYMBOL_LABEL, event)
        if delta:
            sign = "🏆 Reward" if delta > 0 else "💀 Penalty"
            msg += f"\n{sign}: {delta:+.2f} | Cumulative score: {new_state['score']:+.2f}"
        logger.info("[strat13] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat13] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE_13, new_state)
    return new_state


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set. "
            "Copy .env.example to .env and fill them in (see README.md)."
        )
    if not any(
        [
            config.STRATEGY1_ENABLED,
            config.STRATEGY2_ENABLED,
            config.STRATEGY3_ENABLED,
            config.STRATEGY4_ENABLED,
            config.STRATEGY5_ENABLED,
            config.STRATEGY6_ENABLED,
            config.STRATEGY7_ENABLED,
            config.STRATEGY8_ENABLED,
            config.STRATEGY9_ENABLED,
            config.STRATEGY10_ENABLED,
            config.STRATEGY11_ENABLED,
            config.STRATEGY12_ENABLED,
            config.STRATEGY13_ENABLED,
        ]
    ):
        raise SystemExit("All thirteen STRATEGYn_ENABLED flags are false — nothing to run.")

    notifier = TelegramNotifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    state1 = load_json_state(config.STATE_FILE, strategy.fresh_state) if config.STRATEGY1_ENABLED else None
    state2 = load_json_state(config.STATE_FILE_2, strategy_rsi_bb.fresh_state) if config.STRATEGY2_ENABLED else None
    state3 = load_json_state(config.STATE_FILE_3, strategy3.fresh_state) if config.STRATEGY3_ENABLED else None
    state4 = load_json_state(config.STATE_FILE_4, strategy4.fresh_state) if config.STRATEGY4_ENABLED else None
    state5 = load_json_state(config.STATE_FILE_5, strategy5.fresh_state) if config.STRATEGY5_ENABLED else None
    state6 = load_json_state(config.STATE_FILE_6, strategy6.fresh_state) if config.STRATEGY6_ENABLED else None
    state7 = load_json_state(config.STATE_FILE_7, strategy7.fresh_state) if config.STRATEGY7_ENABLED else None
    state8 = load_json_state(config.STATE_FILE_8, strategy8.fresh_state) if config.STRATEGY8_ENABLED else None
    state9 = load_json_state(config.STATE_FILE_9, strategy9.fresh_state) if config.STRATEGY9_ENABLED else None
    state10 = load_json_state(config.STATE_FILE_10, strategy10.fresh_state) if config.STRATEGY10_ENABLED else None
    state11 = load_json_state(config.STATE_FILE_11, strategy11.fresh_state) if config.STRATEGY11_ENABLED else None
    state12 = load_json_state(config.STATE_FILE_12, strategy12.fresh_state) if config.STRATEGY12_ENABLED else None
    state13 = load_json_state(config.STATE_FILE_13, strategy13.fresh_state) if config.STRATEGY13_ENABLED else None

    enabled = []
    if config.STRATEGY1_ENABLED:
        enabled.append(f"Strategy 1 (HA+SAR+RSI, {config.BAR_MINUTES}m)")
    if config.STRATEGY2_ENABLED:
        enabled.append(f"Strategy 2 (RSI-Div+BB, {config.BAR_MINUTES_2}m)")
    if config.STRATEGY3_ENABLED:
        enabled.append(f"Strategy 3 (RSI+VWAP, {config.BAR_MINUTES_3}m)")
    if config.STRATEGY4_ENABLED:
        enabled.append(f"Strategy 4 (Consolidation Breakout, {config.BAR_MINUTES_4}m)")
    if config.STRATEGY5_ENABLED:
        enabled.append(f"Strategy 5 (MA Scalping, {config.BAR_MINUTES_5}m, first hour)")
    if config.STRATEGY6_ENABLED:
        enabled.append(f"Strategy 6 (Mean Reversion EMA5/14 + Martingale, {config.BAR_MINUTES_6}m)")
    if config.STRATEGY7_ENABLED:
        enabled.append(f"Strategy 7 (MA+Fibonacci, {config.BAR_MINUTES_7}m)")
    if config.STRATEGY8_ENABLED:
        enabled.append(f"Strategy 8 (Supertrend+Pivots, {config.BAR_MINUTES_8}m)")
    if config.STRATEGY9_ENABLED:
        enabled.append(f"Strategy 9 (VWAP+StdDev, {config.BAR_MINUTES_9}m)")
    if config.STRATEGY10_ENABLED:
        enabled.append(f"Strategy 10 (RSI+Volume Osc, {config.BAR_MINUTES_10}m)")
    if config.STRATEGY11_ENABLED:
        enabled.append(f"Strategy 11 (Pullback+Pivots, {config.BAR_MINUTES_11}m)")
    if config.STRATEGY12_ENABLED:
        enabled.append(f"Strategy 12 (Double RSI, {config.BAR_MINUTES_12}m)")
    if config.STRATEGY13_ENABLED:
        enabled.append(f"Strategy 13 (CPR+Trend, {config.BAR_MINUTES_13}m)")
    logger.info(
        "Starting signal bot for %s (%s). Active: %s. Polling every %ds",
        config.SYMBOL_LABEL,
        config.SYMBOL,
        ", ".join(enabled),
        config.POLL_SECONDS,
    )

    heartbeat_sent_date = None
    report_sent_date = None

    while True:
        try:
            now = pd.Timestamp.now(tz=IST)

            if in_market_hours(now):
                if config.SEND_HEARTBEAT and heartbeat_sent_date != now.date():
                    notifier.send(
                        f"✅ {config.SYMBOL_LABEL} signal bot is running "
                        f"({now.strftime('%Y-%m-%d %H:%M')} IST) — {', '.join(enabled)}"
                    )
                    heartbeat_sent_date = now.date()

                if config.STRATEGY1_ENABLED:
                    state1 = poll_strategy1(state1, notifier)
                if config.STRATEGY2_ENABLED:
                    state2 = poll_strategy2(state2, notifier)
                if config.STRATEGY3_ENABLED:
                    state3 = poll_strategy3(state3, notifier)
                if config.STRATEGY4_ENABLED:
                    state4 = poll_strategy4(state4, notifier)
                if config.STRATEGY5_ENABLED:
                    state5 = poll_strategy5(state5, notifier)
                if config.STRATEGY6_ENABLED:
                    state6 = poll_strategy6(state6, notifier)
                if config.STRATEGY7_ENABLED:
                    state7 = poll_strategy7(state7, notifier)
                if config.STRATEGY8_ENABLED:
                    state8 = poll_strategy8(state8, notifier)
                if config.STRATEGY9_ENABLED:
                    state9 = poll_strategy9(state9, notifier)
                if config.STRATEGY10_ENABLED:
                    state10 = poll_strategy10(state10, notifier)
                if config.STRATEGY11_ENABLED:
                    state11 = poll_strategy11(state11, notifier)
                if config.STRATEGY12_ENABLED:
                    state12 = poll_strategy12(state12, notifier)
                if config.STRATEGY13_ENABLED:
                    state13 = poll_strategy13(state13, notifier)
            else:
                logger.debug("Outside market hours (%s IST) — idling.", now.strftime("%H:%M"))

                if is_after_market_close(now) and report_sent_date != now.date():
                    events_by_strategy = _collect_daily_events(now.date())
                    report_text = build_daily_report(events_by_strategy, config.SYMBOL_LABEL, now.date())
                    if notifier.send(report_text):
                        logger.info("Sent daily report for %s", now.date())
                        report_sent_date = now.date()
                    else:
                        logger.error("Failed to deliver daily report — will retry next cycle")

        except Exception:
            logger.exception("Unhandled error in poll loop — will retry next cycle")

        time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    main()
