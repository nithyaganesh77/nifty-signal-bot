# Nifty 50 Signal Bot (2 strategies)

A rule-based Telegram signal bot for two discretionary scalping
strategies:

1. **Heiken Ashi + Parabolic SAR + RSI** (3-minute chart)
2. **RSI Divergence + Bollinger Bands** (1-minute chart)

Both run concurrently and independently (each can be switched off in
`.env`), and each message is tagged so you can tell them apart in
Telegram: `[HA+SAR+RSI 3m]` vs `[RSI-Div+BB 1m]`. The bot **only sends
Telegram alerts** — it does not place any real orders or touch your
broker account.

Data source: **Yahoo Finance (yfinance)** — free, no broker account
needed. See the "Data source limitations" section below before trusting
this for real money.

## Strategy 1 logic: Heiken Ashi + Parabolic SAR + RSI (3-min)

**Long setup** — on a closed 3-min candle:
- Heiken Ashi candle has no lower wick (bullish)
- Parabolic SAR is below the candle's low (uptrend)
- RSI(14, close) is above 50

→ bot sends a *setup* alert with the trigger price (that candle's high),
stop-loss (the SAR value), target 1 (1:1) and target 2 (1:2).

- **Entry**: the next candle whose high breaks above the trigger price →
  *entry* alert.
- **Target 1 hit** (1:1): *book half* alert, stop is moved to breakeven.
- **Target 2 hit** (1:2): *final exit* alert.
- **Stop-loss hit** (before or after entry): *invalidated* / *stopped
  out* alert.
- A setup that goes an hour (20 candles) without triggering is dropped.

Short setups are the exact mirror (bearish HA candle, SAR above the
candle, RSI below 50).

## Strategy 2 logic: RSI Divergence + Bollinger Bands (1-min)

**Long setup**:
- A confirmed swing low forms *at or below* the lower Bollinger Band
  (20, close, mult 2), and it's a **lower low** in price than the
  previous such swing low, while RSI(14) makes a **higher low** at the
  same point → bullish divergence → *divergence* alert.
- The bot then watches for the next **green candle** (a reversal after
  the fall). That candle becomes the signal candle → *setup* alert, with
  trigger = that candle's high, stop-loss = that candle's low, target =
  the (upper) Bollinger Band value.
- **Entry**: the next candle whose high breaks above the trigger →
  *entry* alert.
- **Target hit**: price reaches the Bollinger Band target → *closed*
  alert. **Stop-loss hit**: *stopped out* alert. Unlike strategy 1, this
  one is a single stop/target trade — the write-up doesn't call for a
  partial exit here.
- Swing points need a few bars to confirm (same as TradingView's Pivot
  High/Low), and a divergence that doesn't get a reversal candle within
  15 bars, or a setup that doesn't trigger within 20 bars, is dropped.

Short setups are the mirror: swing high at/above the upper band with a
higher high in price but a lower high in RSI (bearish divergence), then
a red reversal candle sets up a short with target at the lower band.

## 1. Create your Telegram bot

1. In Telegram, message **@BotFather** → `/newbot` → follow the prompts.
   You'll get a **bot token** that looks like `123456789:AA...`.
2. Get your **chat id**:
   - Easiest: message **@userinfobot** on Telegram, it replies with your
     numeric id.
   - Or: send any message to your new bot, then open
     `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
     and read `"chat":{"id": ...}` from the JSON.
   - For a group chat instead of DMs: add the bot to the group, send a
     message in the group, then use the same `getUpdates` trick — group
     chat ids are negative numbers.

## 2. Install

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

## 3. Test Telegram is wired up

```bash
python send_test_message.py
```

You should get a message in Telegram within a couple seconds.

## 4. Run the bot

```bash
python main.py
```

It polls every 30 seconds (configurable via `POLL_SECONDS` in `.env`),
but only *acts* once a new 3-minute candle actually closes. Leave it
running during market hours (9:15–15:30 IST); it idles quietly outside
that window and picks up where it left off (state is saved to
`state.json` after every processed candle, so restarting the process
doesn't cause duplicate alerts).

To keep it running unattended:
- **Simplest**: run it inside `tmux` or `screen` on any always-on machine
  (a small VPS, a Raspberry Pi, an old laptop) so it survives you closing
  your terminal.
- **More robust**: run it as a `systemd` service (Linux) or a scheduled
  background task, so it auto-restarts if it crashes. Ask me if you want
  a ready-made systemd unit file or a Dockerfile — happy to add one.

## Configuration

Everything is in `.env` (see `.env.example` for defaults and comments):
`SYMBOL` / `SYMBOL_LABEL`, `POLL_SECONDS`, `RSI_LENGTH`, `MARKET_OPEN` /
`MARKET_CLOSE`, per-strategy `STRATEGY1_ENABLED` / `STRATEGY2_ENABLED`
toggles, and each strategy's own indicator settings (`BAR_MINUTES`,
`SAR_START/STEP/MAX` for strategy 1; `BAR_MINUTES_2`, `BB_LENGTH`,
`BB_MULT`, `PIVOT_LEFT/RIGHT` for strategy 2).

To track Bank Nifty instead, set `SYMBOL=^NSEBANK` and
`SYMBOL_LABEL=BANK NIFTY`. For an individual stock, use its Yahoo ticker,
e.g. `SYMBOL=RELIANCE.NS`.

## Data source limitations — please read

yfinance is a **free, unofficial** wrapper around Yahoo Finance's public
endpoints. For Indian indices specifically:

- Data can be **delayed** by several minutes, and Yahoo doesn't guarantee
  any particular latency.
- Occasional **gaps or a stale/incomplete latest bar** are possible, and
  Yahoo can silently change or throttle the endpoint.
- 1-minute history is only available for the last few days, which is why
  the bot resamples 1-minute bars into 3-minute bars itself rather than
  requesting 3-minute bars directly (Yahoo doesn't offer a native 3m
  interval).

This is fine for learning the strategy, paper-trading, and testing the
logic — **it is not a substitute for a real broker market-data feed** if
you intend to size real capital off these alerts. `data_feed.py` is a
small, self-contained module — swapping it for Zerodha Kite Connect,
Upstox, or Fyers later (for live tick-accurate data) doesn't require
touching `indicators.py`, `strategy.py`, or `telegram_bot.py` at all. Say
the word if you'd like that swapped in.

## Files

| File | Purpose |
|---|---|
| `indicators.py` | Heiken Ashi, Parabolic SAR, RSI, Bollinger Bands, pivot detection — pure functions |
| `data_feed.py` | Pulls + resamples Yahoo Finance data into N-minute bars |
| `strategy.py` | Strategy 1 state machine (setup/entry/target1/target2/SL) |
| `strategy_rsi_bb.py` | Strategy 2 state machine (divergence/setup/entry/target/SL) |
| `telegram_bot.py` | Telegram sendMessage wrapper + message formatting for both strategies |
| `main.py` | Polling loop for both strategies, market-hours guard, state persistence |
| `send_test_message.py` | One-off Telegram connectivity check |
| `.env.example` | Copy to `.env` and fill in your settings |
| `tests/test_dryrun.py` | Synthetic (no network) check of strategy 1's logic |
| `tests/test_dryrun_bb.py` | Synthetic (no network) check of strategy 2's logic |

## Disclaimer

This is a mechanical translation of a discretionary strategy description
into rules, for educational/informational purposes. It is not investment
advice, and past strategy performance (including the example trades in
the original write-up) does not guarantee future results. You are
responsible for validating any signal before acting on it and for all
trading decisions and outcomes.
