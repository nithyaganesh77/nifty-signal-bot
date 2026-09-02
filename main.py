"""
Entry point: polls Yahoo Finance for Nifty 50 candles during NSE market
hours and runs all four strategies on every newly closed candle, sending
Telegram messages for setups / entries / exits.

  Strategy 1: Heiken Ashi + Parabolic SAR + RSI, 3-minute candles
  Strategy 2: RSI Divergence + Bollinger Bands, 1-minute candles
  Strategy 3: RSI + VWAP Scalping, 1-minute candles
  Strategy 4: 1-Minute Consolidation Breakout Scalping, 1-minute candles

Any of the four can be switched off via STRATEGY1_ENABLED /
STRATEGY2_ENABLED / STRATEGY3_ENABLED / STRATEGY4_ENABLED in .env. Run:

    python main.py

Runs forever (until Ctrl-C or the process is killed) — see README.md for
how to keep it running unattended (systemd, screen/tmux, or a small VPS).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time

import pandas as pd

import config
import data_feed
import indicators
import strategy
import strategy3
import strategy4
import strategy_rsi_bb
from telegram_bot import (
    TelegramNotifier,
    format_event,
    format_event_bb,
    format_event_consolidation,
    format_event_vwap,
)

IST = data_feed.IST

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.LOG_FILE),
    ],
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


def poll_strategy1(state: dict, notifier: TelegramNotifier) -> dict:
    bars = data_feed.get_closed_bars(symbol=config.SYMBOL, bar_minutes=config.BAR_MINUTES)
    if bars.empty or len(bars) < max(config.RSI_LENGTH, 10) + 5:
        logger.info("[strat1] Not enough closed bars yet (%d) — waiting.", len(bars))
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

    new_state, events = strategy.run(state, ind_df)

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
        logger.info("[strat2] Not enough closed bars yet (%d) — waiting.", len(bars))
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

    new_state, events = strategy_rsi_bb.run(state, ind_df)

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
        logger.info("[strat3] Not enough closed bars yet (%d) — waiting.", len(bars))
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

    new_state, events = strategy3.run(state, ind_df, target_band=config.VWAP_TARGET_BAND)

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
        logger.info("[strat4] Not enough closed bars yet (%d) — waiting.", len(bars))
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
        ]
    ):
        raise SystemExit("All four STRATEGYn_ENABLED flags are false — nothing to run.")

    notifier = TelegramNotifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    state1 = load_json_state(config.STATE_FILE, strategy.fresh_state) if config.STRATEGY1_ENABLED else None
    state2 = load_json_state(config.STATE_FILE_2, strategy_rsi_bb.fresh_state) if config.STRATEGY2_ENABLED else None
    state3 = load_json_state(config.STATE_FILE_3, strategy3.fresh_state) if config.STRATEGY3_ENABLED else None
    state4 = load_json_state(config.STATE_FILE_4, strategy4.fresh_state) if config.STRATEGY4_ENABLED else None

    enabled = []
    if config.STRATEGY1_ENABLED:
        enabled.append(f"Strategy 1 (HA+SAR+RSI, {config.BAR_MINUTES}m)")
    if config.STRATEGY2_ENABLED:
        enabled.append(f"Strategy 2 (RSI-Div+BB, {config.BAR_MINUTES_2}m)")
    if config.STRATEGY3_ENABLED:
        enabled.append(f"Strategy 3 (RSI+VWAP, {config.BAR_MINUTES_3}m)")
    if config.STRATEGY4_ENABLED:
        enabled.append(f"Strategy 4 (Consolidation Breakout, {config.BAR_MINUTES_4}m)")
    logger.info(
        "Starting signal bot for %s (%s). Active: %s. Polling every %ds",
        config.SYMBOL_LABEL,
        config.SYMBOL,
        ", ".join(enabled),
        config.POLL_SECONDS,
    )

    heartbeat_sent_date = None

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
            else:
                logger.info("Outside market hours (%s IST) — idling.", now.strftime("%H:%M"))

        except Exception:
            logger.exception("Unhandled error in poll loop — will retry next cycle")

        time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    main()
