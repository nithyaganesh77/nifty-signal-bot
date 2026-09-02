"""
Quick standalone check that your Telegram bot token + chat id are correct,
before running the full bot. Run:

    python send_test_message.py
"""

import config
from telegram_bot import TelegramNotifier

if __name__ == "__main__":
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set. "
            "Copy .env.example to .env and fill them in first."
        )
    notifier = TelegramNotifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
    ok = notifier.send("👋 Test message from the Nifty 50 signal bot — setup looks good!")
    print("Sent OK" if ok else "Send FAILED — check your token/chat id and the logs above.")
