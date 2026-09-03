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

# --- Strategy 5: Moving Average Scalping (5-min, first hour only) ----------
STRATEGY5_ENABLED = _get_bool("STRATEGY5_ENABLED", True)
BAR_MINUTES_5 = int(os.getenv("BAR_MINUTES_5", "5"))
EMA_LENGTH_5 = int(os.getenv("EMA_LENGTH_5", "7"))  # 5 or 7 both work per the write-up
FIRST_HOUR_END = os.getenv("FIRST_HOUR_END", "10:15")
TARGET_RR_5 = float(os.getenv("TARGET_RR_5", "3.0"))  # 1:3 minimum, up to 1:4
STATE_FILE_5 = os.getenv("STATE_FILE_5", "state_ma_scalp.json")

# --- Strategy 6: Mean Reversion EMA(5,14) + Martingale sizing (1-min) ------
STRATEGY6_ENABLED = _get_bool("STRATEGY6_ENABLED", True)
BAR_MINUTES_6 = int(os.getenv("BAR_MINUTES_6", "1"))
EMA_FAST_6 = int(os.getenv("EMA_FAST_6", "5"))
EMA_SLOW_6 = int(os.getenv("EMA_SLOW_6", "14"))
TARGET_RR_6 = float(os.getenv("TARGET_RR_6", "1.0"))  # 1:1 per the write-up
# Martingale: position-size suggestion doubles after each stop-loss (capped
# here) and resets to 1x after a target hit — see strategy6.py's docstring.
MARTINGALE_MAX_MULTIPLIER = float(os.getenv("MARTINGALE_MAX_MULTIPLIER", "8"))
STATE_FILE_6 = os.getenv("STATE_FILE_6", "state_meanrev_martingale.json")

# --- Strategy 7: Moving Average + Fibonacci (5-min) ------------------------
STRATEGY7_ENABLED = _get_bool("STRATEGY7_ENABLED", True)
BAR_MINUTES_7 = int(os.getenv("BAR_MINUTES_7", "5"))
SMA_LENGTH_7 = int(os.getenv("SMA_LENGTH_7", "200"))
PIVOT_LEFT_7 = int(os.getenv("PIVOT_LEFT_7", "3"))
PIVOT_RIGHT_7 = int(os.getenv("PIVOT_RIGHT_7", "3"))
MA_SLOPE_LOOKBACK_7 = int(os.getenv("MA_SLOPE_LOOKBACK_7", "5"))
TARGET_RR_7 = float(os.getenv("TARGET_RR_7", "2.0"))  # 1:2 per the write-up
STATE_FILE_7 = os.getenv("STATE_FILE_7", "state_ma_fib.json")

# --- Strategy 8: Supertrend + Pivot Points (5-min) --------------------------
STRATEGY8_ENABLED = _get_bool("STRATEGY8_ENABLED", True)
BAR_MINUTES_8 = int(os.getenv("BAR_MINUTES_8", "5"))
ATR_LENGTH_8 = int(os.getenv("ATR_LENGTH_8", "7"))  # "Set the ATR range to 7"
SUPERTREND_MULT_8 = float(os.getenv("SUPERTREND_MULT_8", "3.0"))
STATE_FILE_8 = os.getenv("STATE_FILE_8", "state_supertrend_pivot.json")

# --- Strategy 9: VWAP + Standard Deviations (5-min) -------------------------
STRATEGY9_ENABLED = _get_bool("STRATEGY9_ENABLED", True)
BAR_MINUTES_9 = int(os.getenv("BAR_MINUTES_9", "5"))
VWAP_BAND_MULT_9 = float(os.getenv("VWAP_BAND_MULT_9", "2.0"))
STATE_FILE_9 = os.getenv("STATE_FILE_9", "state_vwap_std.json")

# --- Strategy 10: RSI + Volume Oscillator (5-min) ---------------------------
STRATEGY10_ENABLED = _get_bool("STRATEGY10_ENABLED", True)
BAR_MINUTES_10 = int(os.getenv("BAR_MINUTES_10", "5"))
VOL_OSC_FAST_10 = int(os.getenv("VOL_OSC_FAST_10", "5"))
VOL_OSC_SLOW_10 = int(os.getenv("VOL_OSC_SLOW_10", "10"))
PIVOT_LEFT_10 = int(os.getenv("PIVOT_LEFT_10", "3"))
PIVOT_RIGHT_10 = int(os.getenv("PIVOT_RIGHT_10", "3"))
TARGET_RR_10 = float(os.getenv("TARGET_RR_10", "2.0"))  # conservative 1:2 per the write-up
STATE_FILE_10 = os.getenv("STATE_FILE_10", "state_rsi_volosc.json")

# --- Strategy 11: Pullback + Pivot Points (5-min) ---------------------------
STRATEGY11_ENABLED = _get_bool("STRATEGY11_ENABLED", True)
BAR_MINUTES_11 = int(os.getenv("BAR_MINUTES_11", "5"))
TARGET_RR_11 = float(os.getenv("TARGET_RR_11", "2.0"))  # fallback only — target is normally the next pivot
STATE_FILE_11 = os.getenv("STATE_FILE_11", "state_pivot_pullback.json")

# --- Strategy 12: Double RSI (5-min + hourly) -------------------------------
STRATEGY12_ENABLED = _get_bool("STRATEGY12_ENABLED", True)
BAR_MINUTES_12 = int(os.getenv("BAR_MINUTES_12", "5"))
STATE_FILE_12 = os.getenv("STATE_FILE_12", "state_double_rsi.json")

# --- Strategy 13: CPR with Trend Following (5-min) --------------------------
STRATEGY13_ENABLED = _get_bool("STRATEGY13_ENABLED", True)
BAR_MINUTES_13 = int(os.getenv("BAR_MINUTES_13", "5"))
ATR_LENGTH_13 = int(os.getenv("ATR_LENGTH_13", "14"))
CPR_NARROW_ATR_MULT_13 = float(os.getenv("CPR_NARROW_ATR_MULT_13", "1.0"))
TARGET_RR_13 = float(os.getenv("TARGET_RR_13", "2.0"))  # 1:2 per the write-up
STATE_FILE_13 = os.getenv("STATE_FILE_13", "state_cpr_trend.json")

# --- Reward / penalty scoring (RL-style running score per strategy) --------
# Added to a strategy's cumulative score on the given event; a running
# total is persisted in that strategy's state file and shown in each
# reward-bearing Telegram message.
REWARD_TARGET1 = float(os.getenv("REWARD_TARGET1", "0.5"))  # strat 1/9 partial (target1)
REWARD_TARGET2 = float(os.getenv("REWARD_TARGET2", "1.0"))  # strat 1/9 final (target2)
REWARD_TARGET = float(os.getenv("REWARD_TARGET", "1.0"))    # strat 2/3/4/5/6/7/8/10/11/12/13 final
PENALTY_STOPLOSS = float(os.getenv("PENALTY_STOPLOSS", "1.0"))  # all strategies
