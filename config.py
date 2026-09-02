from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SYMBOL = os.getenv("SYMBOL", "^NSEI")  # Nifty 50 index on Yahoo Finance
SYMBOL_LABEL = os.getenv("SYMBOL_LABEL", "NIFTY 50")

MARKET_OPEN = os.getenv("MARKET_OPEN", "09:15")
MARKET_CLOSE = os.getenv("MARKET_CLOSE", "15:30")

LOG_FILE = os.getenv("LOG_FILE", "signal_bot.log")
SEND_HEARTBEAT = _get_bool("SEND_HEARTBEAT", True)

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
RSI_LENGTH = int(os.getenv("RSI_LENGTH", "14"))

# --- Strategy 1: Heiken Ashi + Parabolic SAR + RSI (3-min) -----------------
STRATEGY1_ENABLED = _get_bool("STRATEGY1_ENABLED", True)
BAR_MINUTES = int(os.getenv("BAR_MINUTES", "3"))
SAR_START = float(os.getenv("SAR_START", "0.02"))
SAR_STEP = float(os.getenv("SAR_STEP", "0.02"))
SAR_MAX = float(os.getenv("SAR_MAX", "0.2"))
STATE_FILE = os.getenv("STATE_FILE", "state.json")

# --- Strategy 2: RSI Divergence + Bollinger Bands (1-min) -------------------
STRATEGY2_ENABLED = _get_bool("STRATEGY2_ENABLED", True)
BAR_MINUTES_2 = int(os.getenv("BAR_MINUTES_2", "1"))
BB_LENGTH = int(os.getenv("BB_LENGTH", "20"))
BB_MULT = float(os.getenv("BB_MULT", "2.0"))
PIVOT_LEFT = int(os.getenv("PIVOT_LEFT", "3"))
PIVOT_RIGHT = int(os.getenv("PIVOT_RIGHT", "3"))
STATE_FILE_2 = os.getenv("STATE_FILE_2", "state_rsi_bb.json")

# --- Strategy 3: RSI + VWAP Scalping (1-min) --------------------------------
STRATEGY3_ENABLED = _get_bool("STRATEGY3_ENABLED", True)
BAR_MINUTES_3 = int(os.getenv("BAR_MINUTES_3", "1"))
VWAP_RECENT_WINDOW = int(os.getenv("VWAP_RECENT_WINDOW", "10"))
VWAP_TARGET_BAND = int(os.getenv("VWAP_TARGET_BAND", "1"))  # which band (1/2/3) is the target
RSI_OVERSOLD = float(os.getenv("RSI_OVERSOLD", "30"))
RSI_OVERBOUGHT = float(os.getenv("RSI_OVERBOUGHT", "70"))
STATE_FILE_3 = os.getenv("STATE_FILE_3", "state_rsi_vwap.json")

# --- Strategy 4: 1-Minute Consolidation Breakout Scalping ------------------
STRATEGY4_ENABLED = _get_bool("STRATEGY4_ENABLED", True)
BAR_MINUTES_4 = int(os.getenv("BAR_MINUTES_4", "1"))
EMA_LENGTH = int(os.getenv("EMA_LENGTH", "9"))
TREND_LOOKBACK = int(os.getenv("TREND_LOOKBACK", "15"))
RANGE_BARS = int(os.getenv("RANGE_BARS", "5"))
ATR_LENGTH = int(os.getenv("ATR_LENGTH", "14"))
CONSOLIDATION_MAX_ATR_MULT = float(os.getenv("CONSOLIDATION_MAX_ATR_MULT", "1.5"))
TARGET_RR = float(os.getenv("TARGET_RR", "3.0"))  # minimum 1:3 per the strategy
TIME_EXIT_BARS = int(os.getenv("TIME_EXIT_BARS", "10"))  # close after 10 minutes
STATE_FILE_4 = os.getenv("STATE_FILE_4", "state_consolidation.json")

# --- Reward / penalty scoring (RL-style running score per strategy) --------
# Added to a strategy's cumulative score on the given event; a running
# total is persisted in that strategy's state file and shown in each
# reward-bearing Telegram message.
REWARD_TARGET1 = float(os.getenv("REWARD_TARGET1", "0.5"))  # strat 1 partial (1:1)
REWARD_TARGET2 = float(os.getenv("REWARD_TARGET2", "1.0"))  # strat 1 final (1:2)
REWARD_TARGET = float(os.getenv("REWARD_TARGET", "1.0"))    # strat 2 final
PENALTY_STOPLOSS = float(os.getenv("PENALTY_STOPLOSS", "1.0"))  # both strategies
