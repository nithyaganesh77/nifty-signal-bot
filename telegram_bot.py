"""
Minimal Telegram notifier — just a thin wrapper around the Bot API's
sendMessage endpoint over plain HTTP (no extra SDK needed).
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


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


def format_event(symbol_label: str, event: dict) -> str:
    """
    Turn one strategy 1 (Heiken Ashi + Parabolic SAR + RSI) event dict
    (see strategy.py) into a readable Telegram message.
    """
    etype = event["type"]
    direction = event.get("direction", "").upper()
    arrow = "🟢 LONG" if event.get("direction") == "long" else "🔴 SHORT"
    tag = "[HA+SAR+RSI 3m]"

    if etype == "setup":
        return (
            f"*{tag} {symbol_label} — SETUP DETECTED* ({arrow})\n"
            f"Signal candle: `{event['signal_ts']}`\n"
            f"Watching for breakout {'above' if direction == 'LONG' else 'below'} "
            f"`{event['trigger']:.2f}`\n"
            f"Planned SL: `{event['sl']:.2f}`\n"
            f"Target 1 (1:1, book half): `{event['target1']:.2f}`\n"
            f"Target 2 (1:2, final): `{event['target2']:.2f}`"
        )
    if etype == "setup_invalidated":
        return (
            f"*{tag} {symbol_label} — setup invalidated* ({arrow})\n"
            f"Price hit SL (`{event['sl']:.2f}`) before triggering entry. No trade."
        )
    if etype == "setup_expired":
        return (
            f"*{tag} {symbol_label} — setup expired* ({arrow})\n"
            f"No breakout within the wait window. Standing down."
        )
    if etype == "entry":
        return (
            f"*{tag} {symbol_label} — ENTRY TRIGGERED* ({arrow})\n"
            f"Entry: `{event['entry']:.2f}`\n"
            f"Stop-loss: `{event['sl']:.2f}`\n"
            f"Target 1 (book half): `{event['target1']:.2f}`\n"
            f"Target 2 (final): `{event['target2']:.2f}`"
        )
    if etype == "target1_hit":
        return (
            f"*{tag} {symbol_label} — TARGET 1 HIT (book half)* ({arrow})\n"
            f"Price: `{event['target1']:.2f}`\n"
            f"Stop moved to breakeven: `{event['sl']:.2f}`\n"
            f"Riding remaining half to Target 2: `{event['target2']:.2f}`"
        )
    if etype == "target2_hit":
        return (
            f"*{tag} {symbol_label} — TARGET 2 HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['target2']:.2f}`"
        )
    if etype == "stoploss_hit":
        return (
            f"*{tag} {symbol_label} — STOP-LOSS HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['sl']:.2f}`"
        )
    return f"{tag} {symbol_label} — {etype}: {event}"


def format_event_bb(symbol_label: str, event: dict) -> str:
    """
    Turn one strategy 2 (RSI Divergence + Bollinger Bands) event dict
    (see strategy_rsi_bb.py) into a readable Telegram message.
    """
    etype = event["type"]
    direction = event.get("direction", "").upper()
    arrow = "🟢 LONG" if event.get("direction") == "long" else "🔴 SHORT"
    tag = "[RSI-Div+BB 1m]"

    if etype == "divergence":
        kind = "Bullish" if direction == "LONG" else "Bearish"
        return (
            f"*{tag} {symbol_label} — {kind} RSI divergence spotted* ({arrow})\n"
            f"Price: `{event['price']:.2f}`, RSI: `{event['rsi']:.1f}`\n"
            f"Watching for a reversal candle to form a setup…"
        )
    if etype == "divergence_expired":
        return f"*{tag} {symbol_label} — divergence expired* ({arrow})\nNo reversal candle in time. Standing down."
    if etype == "setup":
        return (
            f"*{tag} {symbol_label} — SETUP DETECTED* ({arrow})\n"
            f"Signal candle: `{event['signal_ts']}`\n"
            f"Watching for breakout {'above' if direction == 'LONG' else 'below'} "
            f"`{event['trigger']:.2f}`\n"
            f"Planned SL: `{event['sl']:.2f}`\n"
            f"Target (Bollinger Band): `{event['target']:.2f}`"
        )
    if etype == "setup_invalidated":
        return (
            f"*{tag} {symbol_label} — setup invalidated* ({arrow})\n"
            f"Price hit SL (`{event['sl']:.2f}`) before triggering entry. No trade."
        )
    if etype == "setup_expired":
        return (
            f"*{tag} {symbol_label} — setup expired* ({arrow})\n"
            f"No breakout within the wait window. Standing down."
        )
    if etype == "entry":
        return (
            f"*{tag} {symbol_label} — ENTRY TRIGGERED* ({arrow})\n"
            f"Entry: `{event['entry']:.2f}`\n"
            f"Stop-loss: `{event['sl']:.2f}`\n"
            f"Target: `{event['target']:.2f}`"
        )
    if etype == "target_hit":
        return (
            f"*{tag} {symbol_label} — TARGET HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['target']:.2f}`"
        )
    if etype == "stoploss_hit":
        return (
            f"*{tag} {symbol_label} — STOP-LOSS HIT — trade closed* ({arrow})\n"
            f"Exit: `{event['sl']:.2f}`"
        )
    return f"{tag} {symbol_label} — {etype}: {event}"
