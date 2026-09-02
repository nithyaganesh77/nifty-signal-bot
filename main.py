"""
Entry point: polls Yahoo Finance for Nifty 50 candles during NSE market
hours and runs both strategies on every newly closed candle, sending
Telegram messages for setups / entries / exits.

  Strategy 1: Heiken Ashi + Parabolic SAR + RSI, 3-minute candles
  Strategy 2: RSI Divergence + Bollinger Bands, 1-minute candles

Either can be switched off via STRATEGY1_ENABLED / STRATEGY2_ENABLED in
.env. Run:

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
import strategy_rsi_bb
from telegram_bot import TelegramNotifier, format_event, format_event_bb

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
        msg = format_event(config.SYMBOL_LABEL, event)
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
        msg = format_event_bb(config.SYMBOL_LABEL, event)
        logger.info("[strat2] EVENT %s: %s", event["type"], event)
        if not notifier.send(msg):
            logger.error("[strat2] Failed to deliver Telegram message for %s", event["type"])

    save_json_state(config.STATE_FILE_2, new_state)
    return new_state


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set. "
            "Copy .env.example to .env and fill them in (see README.md)."
        )
    if not config.STRATEGY1_ENABLED and not config.STRATEGY2_ENABLED:
        raise SystemExit("Both STRATEGY1_ENABLED and STRATEGY2_ENABLED are false — nothing to run.")

    notifier = TelegramNotifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    state1 = load_json_state(config.STATE_FILE, strategy.fresh_state) if config.STRATEGY1_ENABLED else None
    state2 = load_json_state(config.STATE_FILE_2, strategy_rsi_bb.fresh_state) if config.STRATEGY2_ENABLED else None

    enabled = []
    if config.STRATEGY1_ENABLED:
        enabled.append(f"Strategy 1 (HA+SAR+RSI, {config.BAR_MINUTES}m)")
    if config.STRATEGY2_ENABLED:
        enabled.append(f"Strategy 2 (RSI-Div+BB, {config.BAR_MINUTES_2}m)")
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
            else:
                logger.info("Outside market hours (%s IST) — idling.", now.strftime("%H:%M"))

        except Exception:
            logger.exception("Unhandled error in poll loop — will retry next cycle")

        time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    main()
