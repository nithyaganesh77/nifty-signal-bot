"""
Free data feed for Nifty 50 (^NSEI) using yfinance.

IMPORTANT — read this before relying on the bot for real trading:
yfinance/Yahoo Finance is a free, unofficial data source. For Indian
indices it can be delayed by several minutes, occasionally has gaps or a
missing/incomplete latest bar, and Yahoo can change or throttle the feed
without notice. It's fine for learning, paper-trading and testing this
strategy, but it is NOT a substitute for a real broker market-data feed
(Zerodha Kite Connect / Upstox / Fyers) if you plan to trade real money on
these signals. The rest of the codebase doesn't care where bars come from
— swap this module out for a broker feed later without touching
indicators.py or strategy.py.

Nifty 50 index ticker on Yahoo: "^NSEI"
"""

from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

IST = "Asia/Kolkata"

# 9:15 IST market open = 555 minutes after midnight, and 555 is exactly
# divisible by 3, so a plain 3-minute resample anchored at midnight lands
# exactly on the real 9:15 / 9:18 / 9:21 ... bar boundaries. No custom
# origin offset needed.
BAR_MINUTES = 3


def fetch_raw_1m(symbol: str = "^NSEI", period: str = "5d") -> pd.DataFrame:
    """
    Pull recent 1-minute OHLC bars from Yahoo Finance.

    Yahoo only keeps a few days of 1-minute history, so `period` is capped
    low (yfinance itself will raise/trim if you ask for too much for a 1m
    interval). 5 days gives us comfortable indicator warm-up (SAR and RSI
    both need lookback) while staying inside Yahoo's window.
    """
    ticker = yf.Ticker(symbol)
    raw = ticker.history(period=period, interval="1m", auto_adjust=False)

    if raw.empty:
        logger.warning("yfinance returned no 1m data for %s", symbol)
        return raw

    raw = raw.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )[["open", "high", "low", "close", "volume"]]

    if raw.index.tz is None:
        raw.index = raw.index.tz_localize("UTC")
    raw.index = raw.index.tz_convert(IST)
    raw = raw.sort_index()
    raw = raw[~raw.index.duplicated(keep="last")]
    return raw


def resample_to_bars(raw_1m: pd.DataFrame, bar_minutes: int = BAR_MINUTES) -> pd.DataFrame:
    """
    Resample 1-minute bars into N-minute bars (default 3-minute, matching
    the strategy's "3-minute timeframe chart"). label='left' means a bar
    stamped 09:15:00 covers 09:15:00–09:17:59 and is only "closed" once
    the wall clock passes 09:18:00.
    """
    if raw_1m.empty:
        return raw_1m

    rule = f"{bar_minutes}min"
    bars = raw_1m.resample(rule, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    bars = bars.dropna(subset=["open", "high", "low", "close"])
    return bars


def get_closed_bars(
    symbol: str = "^NSEI",
    bar_minutes: int = BAR_MINUTES,
    period: str = "5d",
) -> pd.DataFrame:
    """
    Fetch + resample, then drop the bar that hasn't finished forming yet
    (its close time is still in the future). Only fully closed bars are
    safe to run the strategy against — using a forming bar would repaint.
    """
    raw = fetch_raw_1m(symbol=symbol, period=period)
    bars = resample_to_bars(raw, bar_minutes=bar_minutes)
    if bars.empty:
        return bars

    now = pd.Timestamp.now(tz=IST)
    bar_close_time = bars.index + pd.Timedelta(minutes=bar_minutes)
    closed_mask = bar_close_time <= now
    return bars[closed_mask]
