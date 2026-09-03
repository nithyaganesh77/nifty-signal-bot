"""
Minimal Telegram notifier — just a thin wrapper around the Bot API's
sendMessage endpoint over plain HTTP (no extra SDK needed).
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

STRAT1_NAME = "Strategy 1: Heiken Ashi + Parabolic SAR + RSI (3-min)"
STRAT2_NAME = "Strategy 2: RSI Divergence + Bollinger Bands (1-min)"
STRAT3_NAME = "Strategy 3: RSI + VWAP Scalping (1-min)"
STRAT4_NAME = "Strategy 4: 1-Minute Consolidation Breakout Scalping (1-min)"
STRAT5_NAME = "Strategy 5: Moving Average Scalping (5-min, first hour only)"
STRAT6_NAME = "Strategy 6: Mean Reversion EMA(5,14) + Martingale Sizing (1-min)"


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, timeout: int = 10):
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot_token and chat_id are required")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def send(self, text: str, parse_mode: str = "Markdown") -> bool:
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            if resp.status_code != 200:
                logger.error("Telegram send failed [%s]: %s", resp.status_code, resp.text)
                return False
            return True
        except requests.RequestException:
            logger.exception("Telegram send raised an exception")
            return False


def _with_strategy_header(strategy_name: str, body: str) -> str:
    """Every alert names the strategy that generated it, up front."""
    return f"📊 Strategy: {strategy_name}\n{body}"


def format_event(symbol_label: str, event: dict) -> str:
    """
    Turn one strategy 1 (Heiken Ashi + Parabolic SAR + RSI) event dict
    (see strategy.py) into a readable Telegram message.
    """
    etype = event["type"]
    direction = event.get("direction", "").upper()
    arrow = "🟢 LONG" if event.get("direction") == "long" else "🔴 SHORT"

    if etype == "setup":
        body = (
            f"*{symbol_label} — SETUP DETECTED* ({arrow})\n"
            f"Signal candle: `{event['signal_ts']}`\n"
            f"Watching for breakout {'above' if direction == 'LONG' else 'below'} "
            f"`{event['trigger']:.2f}`\n"
            f"Planned SL: `{event['sl']:.2f}`\n"
            f"Target 1 (1:1, book half): `{event['target1']:.2f}`\n"
            f"Target 2 (1:2, final): `{event['target2']:.2f}`"
        )
    elif etype == "setup_invalidated":
        body = (
            f"*{symbol_label} — setup invalidated* ({arrow})\n"
            f"Price hit SL (`{event['sl']:.2f}`) before triggering entry. No trade."
        )
    elif etype == "setup_expired":
        body = (
            f"*{symbol_label} — setup expired* ({arrow})\n"
            f"No breakout within the wait window. Standing down."
        )
    elif etype == "entry":
        body = (
            f"*{symbol_label} — ENTRY TRIGGERED* ({arrow})\n"
            f"Entry: `{event['entry']:.2f}`\n"
            f"Stop-loss: `{event['sl']:.2f}`\n"
            f"Target 1 (book half): `{event['target1']:.2f}`\n"
            f"Target 2 (final): `{event['target2']:.2f}`"
        )
    elif etype == "target1_hit":
        body = (
            f"*{symbol_label} — TARGET 1 HIT (book half)* ({arrow})\n"
            f"Price: `{event['target1']:.2f}`\n"
            f"Stop moved to breakeven: `{event['sl']:.2f}`\n"
            f"Riding remaining half to Target 2: `{event['target2']:.2f}`"
        )
    elif etype == "target2_hit":
        body = (
            f"*{symbol_label} — TARGET 2 HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['target2']:.2f}`"
        )
    elif etype == "stoploss_hit":
        body = (
            f"*{symbol_label} — STOP-LOSS HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['sl']:.2f}`"
        )
    else:
        body = f"{symbol_label} — {etype}: {event}"

    return _with_strategy_header(STRAT1_NAME, body)


def format_event_bb(symbol_label: str, event: dict) -> str:
    """
    Turn one strategy 2 (RSI Divergence + Bollinger Bands) event dict
    (see strategy_rsi_bb.py) into a readable Telegram message.
    """
    etype = event["type"]
    direction = event.get("direction", "").upper()
    arrow = "🟢 LONG" if event.get("direction") == "long" else "🔴 SHORT"

    if etype == "divergence":
        kind = "Bullish" if direction == "LONG" else "Bearish"
        body = (
            f"*{symbol_label} — {kind} RSI divergence spotted* ({arrow})\n"
            f"Price: `{event['price']:.2f}`, RSI: `{event['rsi']:.1f}`\n"
            f"Watching for a reversal candle to enter…"
        )
    elif etype == "divergence_expired":
        body = f"*{symbol_label} — divergence expired* ({arrow})\nNo reversal candle in time. Standing down."
    elif etype == "entry":
        body = (
            f"*{symbol_label} — ENTRY TRIGGERED (reversal candle)* ({arrow})\n"
            f"Entry: `{event['entry']:.2f}`\n"
            f"Stop-loss: `{event['sl']:.2f}`\n"
            f"Target (Bollinger Band): `{event['target']:.2f}`"
        )
    elif etype == "target_hit":
        body = (
            f"*{symbol_label} — TARGET HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['target']:.2f}`"
        )
    elif etype == "stoploss_hit":
        body = (
            f"*{symbol_label} — STOP-LOSS HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['sl']:.2f}`"
        )
    else:
        body = f"{symbol_label} — {etype}: {event}"

    return _with_strategy_header(STRAT2_NAME, body)


def format_event_vwap(symbol_label: str, event: dict) -> str:
    """
    Turn one strategy 3 (RSI + VWAP Scalping) event dict (see
    strategy3.py) into a readable Telegram message.
    """
    etype = event["type"]
    direction = event.get("direction", "").upper()
    arrow = "🟢 LONG" if event.get("direction") == "long" else "🔴 SHORT"

    if etype == "entry":
        kind = "support bounce off VWAP" if direction == "LONG" else "rejection at VWAP"
        body = (
            f"*{symbol_label} — ENTRY TRIGGERED* ({kind}) ({arrow})\n"
            f"Signal candle: `{event['signal_ts']}`\n"
            f"Entry: `{event['entry']:.2f}`\n"
            f"Stop-loss (VWAP): `{event['sl']:.2f}`\n"
            f"Target (VWAP band): `{event['target']:.2f}`"
        )
    elif etype == "target_hit":
        body = (
            f"*{symbol_label} — TARGET HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['target']:.2f}`"
        )
    elif etype == "stoploss_hit":
        body = (
            f"*{symbol_label} — STOP-LOSS HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['sl']:.2f}`"
        )
    else:
        body = f"{symbol_label} — {etype}: {event}"

    return _with_strategy_header(STRAT3_NAME, body)


def format_event_consolidation(symbol_label: str, event: dict) -> str:
    """
    Turn one strategy 4 (1-Minute Consolidation Breakout) event dict (see
    strategy4.py) into a readable Telegram message. Entry is immediate
    here — no separate "setup" stage — so this only has entry/exit
    events.
    """
    etype = event["type"]
    direction = event.get("direction", "").upper()
    arrow = "🟢 LONG" if event.get("direction") == "long" else "🔴 SHORT"

    if etype == "entry":
        kind = "range breakout" if direction == "LONG" else "range breakdown"
        body = (
            f"*{symbol_label} — ENTRY ({kind})* ({arrow})\n"
            f"Entry: `{event['entry']:.2f}`\n"
            f"Stop-loss (breakout candle): `{event['sl']:.2f}`\n"
            f"Target (min 1:3): `{event['target']:.2f}`\n"
            f"Will force-close in 10 min if neither hits."
        )
    elif etype == "target_hit":
        body = (
            f"*{symbol_label} — TARGET HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['exit_price']:.2f}`"
        )
    elif etype == "stoploss_hit":
        body = (
            f"*{symbol_label} — STOP-LOSS HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['exit_price']:.2f}`"
        )
    elif etype == "time_exit":
        body = (
            f"*{symbol_label} — TIME EXIT (10 min) — trade closed* ({arrow})\n"
            f"Neither target nor SL hit in time; closed at market.\n"
            f"Exit: `{event['exit_price']:.2f}`"
        )
    else:
        body = f"{symbol_label} — {etype}: {event}"

    return _with_strategy_header(STRAT4_NAME, body)


def format_event_ma(symbol_label: str, event: dict) -> str:
    """
    Turn one strategy 5 (Moving Average Scalping) event dict (see
    strategy5.py) into a readable Telegram message.
    """
    etype = event["type"]
    direction = event.get("direction", "").upper()
    arrow = "🟢 LONG" if event.get("direction") == "long" else "🔴 SHORT"

    if etype == "setup":
        body = (
            f"*{symbol_label} — SETUP DETECTED* ({arrow})\n"
            f"Signal candle: `{event['signal_ts']}`\n"
            f"Watching for a break {'above' if direction == 'LONG' else 'below'} "
            f"`{event['trigger']:.2f}`\n"
            f"Planned SL: `{event['sl']:.2f}`"
        )
    elif etype == "setup_updated":
        body = (
            f"*{symbol_label} — setup adjusted (better entry)* ({arrow})\n"
            f"New signal candle: `{event['signal_ts']}`\n"
            f"Watching for a break {'above' if direction == 'LONG' else 'below'} "
            f"`{event['trigger']:.2f}`\n"
            f"Planned SL: `{event['sl']:.2f}`"
        )
    elif etype == "setup_expired":
        body = (
            f"*{symbol_label} — setup expired* ({arrow})\n"
            f"No breakout within the first hour. Standing down for today."
        )
    elif etype == "entry":
        body = (
            f"*{symbol_label} — ENTRY TRIGGERED* ({arrow})\n"
            f"Entry: `{event['entry']:.2f}`\n"
            f"Stop-loss: `{event['sl']:.2f}`\n"
            f"Target: `{event['target']:.2f}`"
        )
    elif etype == "target_hit":
        body = (
            f"*{symbol_label} — TARGET HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['target']:.2f}`"
        )
    elif etype == "stoploss_hit":
        body = (
            f"*{symbol_label} — STOP-LOSS HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['sl']:.2f}`"
        )
    else:
        body = f"{symbol_label} — {etype}: {event}"

    return _with_strategy_header(STRAT5_NAME, body)


def format_event_meanrev(symbol_label: str, event: dict) -> str:
    """
    Turn one strategy 6 (Mean Reversion EMA(5,14)) event dict (see
    strategy6.py) into a readable Telegram message. The Martingale
    position-size line is appended separately by main.py, after this.
    """
    etype = event["type"]
    direction = event.get("direction", "").upper()
    arrow = "🟢 LONG" if event.get("direction") == "long" else "🔴 SHORT"

    if etype == "setup":
        kind = "bullish reversal off a downward move" if direction == "LONG" else "bearish reversal off an upward move"
        body = (
            f"*{symbol_label} — SETUP DETECTED* ({kind}) ({arrow})\n"
            f"Signal candle: `{event['signal_ts']}`\n"
            f"Watching for breakout {'above' if direction == 'LONG' else 'below'} "
            f"`{event['trigger']:.2f}`\n"
            f"Planned SL: `{event['sl']:.2f}`"
        )
    elif etype == "setup_invalidated":
        body = (
            f"*{symbol_label} — setup invalidated* ({arrow})\n"
            f"Price hit SL (`{event['sl']:.2f}`) before triggering entry. No trade."
        )
    elif etype == "setup_expired":
        body = (
            f"*{symbol_label} — setup expired* ({arrow})\n"
            f"No breakout within the wait window. Standing down."
        )
    elif etype == "entry":
        body = (
            f"*{symbol_label} — ENTRY TRIGGERED* ({arrow})\n"
            f"Entry: `{event['entry']:.2f}`\n"
            f"Stop-loss: `{event['sl']:.2f}`\n"
            f"Target (1:1): `{event['target']:.2f}`"
        )
    elif etype == "target_hit":
        body = (
            f"*{symbol_label} — TARGET HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['target']:.2f}`"
        )
    elif etype == "stoploss_hit":
        body = (
            f"*{symbol_label} — STOP-LOSS HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['sl']:.2f}`"
        )
    else:
        body = f"{symbol_label} — {etype}: {event}"

    return _with_strategy_header(STRAT6_NAME, body)
