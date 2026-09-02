# Nifty 50 Signal Bot (6 strategies)

A rule-based Telegram signal bot for four discretionary scalping
strategies:

1. **Heiken Ashi + Parabolic SAR + RSI** (3-minute chart)
2. **RSI Divergence + Bollinger Bands** (1-minute chart)
3. **RSI + VWAP Scalping** (1-minute chart)
4. **1-Minute Consolidation Breakout Scalping** (1-minute chart)

All four run concurrently and independently (each can be switched off
in `.env`), and every Telegram message opens with which strategy
generated it (e.g. `📊 Strategy: Strategy 3: RSI + VWAP Scalping
(1-min)`), so you always know which system called the signal. Each
target/stop-loss hit also shows the RL-style reward/penalty for that
strategy and its running cumulative score — see "Reward/penalty
scoring" below. The bot **only sends Telegram alerts** — it does not
place any real orders or touch your broker account.

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

## Strategy 3 logic: RSI + VWAP Scalping (1-min)

**Long setup**:
- RSI(14) dipped into the **oversold zone (<30)** within the last 10
  bars (configurable), and
- this candle's low touches/dips to the session **VWAP** line and it
  closes back **above** VWAP as a green (bullish) candle — a support
  bounce → *setup* alert, with trigger = that candle's high, stop-loss =
  the VWAP value, target = the upper VWAP std-dev band (band 1 by
  default; configurable).
- **Entry**: the next candle whose high breaks above the trigger →
  *entry* alert.
- **Target hit**: price reaches the VWAP band target → *closed* alert.
  **Stop-loss hit**: *stopped out* alert. Single stop/target trade, same
  as strategy 2 — the write-up mentions "trail it for maximum gains" as
  a discretionary option but gives no mechanical rule for it, so it
  isn't automated.

Short setups are the mirror: RSI overbought (>70) recently, then a red
candle rejects back below VWAP from above.

VWAP needs real traded **volume** to be meaningful — see "Data source
limitations" below, this is the one strategy most affected by it.

## Strategy 4 logic: 1-Minute Consolidation Breakout Scalping (1-min)

Unlike strategies 1-3, entry here is **immediate** — the breakout candle
itself is the entry, there's no separate "wait for a further breakout"
stage:

- **Trend filter**: EMA(9)'s slope over the last 15 bars must be
  positive (uptrend) or negative (downtrend) — a simple, adaptive stand-in
  for "identify the pre-established trend".
- **Consolidation**: the high/low of the 5 candles immediately before the
  current one form a range; it only counts if that range is "tight" —
  width ≤ 1.5× ATR(14) (configurable), approximating "small candle bodies
  with wicks".
- **Long**: in an uptrend, when a candle's **close** breaks above that
  tight range's high → immediate *entry* alert. Stop-loss = that candle's
  low. Target = entry + 3×risk (minimum 1:3, configurable).
- **Short**: mirror — downtrend, close breaks below the range's low, SL =
  that candle's high.
- **Time exit**: if neither target nor stop-loss is hit within 10 minutes
  (configurable), the trade is force-closed at market with a *time exit*
  alert — this is a hard rule from the write-up, not optional.

"Trail it for maximum gains" type discretion isn't present in this
strategy's rules, so there's nothing extra to automate here beyond the
above.

## Strategy 5 logic: Moving Average Scalping (5-min, first hour only)

A mean-reversion strategy: it only looks for trades in the **first hour**
of the session (9:15–10:15 IST) and stands down for the day otherwise.

- **Indicator**: EMA(5 or 7, configurable) on close, 5-minute chart.
- **Signal candle**: the very first candle of the day is skipped (too
  volatile). From the 2nd candle onward, a candle that closes above the
  EMA *and* never touches it (its low stays above the EMA) is a **short**
  signal candle; the mirror (closes below EMA, high stays below it) is a
  **long** signal candle.
- **Better entry**: if a later candle (still within the first hour, still
  untriggered) also qualifies in the same direction, it replaces the
  current signal candle — usually a tighter stop — sent as a
  *setup adjusted* alert.
- **Entry**: triggers when price breaks the signal candle's low (short)
  or high (long). Stop-loss = that candle's high (short) / low (long).
- **Target**: risk:reward of at least 1:3, configurable up to 1:4
  (`TARGET_RR_5`).
- **No trade after the first hour**: if nothing has triggered by
  `FIRST_HOUR_END` (10:15 by default), the setup is dropped for the day —
  this strategy does not chase entries later in the session. A trade that
  did trigger in the first hour is still managed (target/SL) normally
  afterwards.

## Strategy 6 logic: Mean Reversion EMA(5,14) + Martingale sizing (1-min)

- **Indicators**: EMA(5) and EMA(14) on close, 1-minute chart. EMA(5)
  below EMA(14) reads as a "down" move (price has pulled away from its
  average); EMA(5) above EMA(14) reads as "up".
- **Signal candle**: in a "down" move, a bullish (green) candle is a
  long signal candle; in an "up" move, a bearish (red) candle is a short
  signal candle.
- **Entry**: triggers on a breakout of that candle's high (long) / low
  (short) — same setup → entry pattern as strategies 1–3. Stop-loss =
  the signal candle's low (long) / high (short).
- **Target**: fixed 1:1 risk:reward (`TARGET_RR_6`), per the write-up.
- **Martingale position sizing**: the write-up's "5.6 Martingale System"
  is a bet-sizing rule, not a signal rule — it only works cleanly on a
  fixed 1:1 R:R system like this one. Since this bot sends alerts rather
  than placing real orders, it's implemented as a *suggested* position
  multiplier shown on every alert: starts at **1x**, **doubles after
  every stop-loss** (capped at `MARTINGALE_MAX_MULTIPLIER`, default 8x),
  and **resets to 1x after every target hit** — mirroring "put net
  profit aside" in the write-up. This multiplier is *not* real
  money-management advice for you to blindly follow — martingale sizing
  can escalate risk fast on a losing streak; use it as a reference, not
  an instruction.

## End-of-day report

Shortly after `MARKET_CLOSE` (15:30 IST by default), the bot sends one
extra Telegram message summarizing the whole trading day: for every
strategy that had at least one entry, how many entries / target hits
(TP) / stop-losses (SL), and its accuracy (win rate = TP ÷ (TP + SL)).
It then calls out the best and worst accuracy, which strategy took the
most stop-losses, which hit the most targets, and an overall accuracy
across all strategies combined. If nothing triggered that day, it sends
a short "no entries" message instead.

This is computed with a fresh, pure replay of each strategy's logic over
that day's bars (the same `simulate()` function `run()` uses internally)
rather than counters accumulated during the day — so it can't drift from
what was actually alerted, and it isn't lost if the bot restarts partway
through the day. It only fires once per calendar day (tracked in
memory, so a restart very late in the day could send it again on the
next cycle if it hadn't gone out yet that day).

## Reward/penalty scoring

Each strategy keeps a running score, shown alongside every target/SL
alert: `🏆 Reward: +1.00 | Cumulative score: +2.50` on a target hit,
`💀 Penalty: -1.00 | Cumulative score: +1.50` on a stop-loss hit.
Configurable in `.env`: `REWARD_TARGET1` / `REWARD_TARGET2` (strategy
1's partial/final targets), `REWARD_TARGET` (strategies 2, 3, 4, 5 & 6's
single target), `PENALTY_STOPLOSS` (all six). Strategy 4's time-exit
isn't scored — it can close in profit or loss depending on where price
sits at the 10-minute mark, so it isn't a clean win/loss. The score is
just a running tally for your own tracking — it doesn't feed back into
the strategy logic (no actual learning/adaptation happens).

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
`MARKET_CLOSE`, per-strategy `STRATEGY1_ENABLED` / `STRATEGY2_ENABLED` /
`STRATEGY3_ENABLED` / `STRATEGY4_ENABLED` / `STRATEGY5_ENABLED` /
`STRATEGY6_ENABLED` toggles, each strategy's own indicator settings
(`BAR_MINUTES`, `SAR_START/STEP/MAX` for strategy 1; `BAR_MINUTES_2`,
`BB_LENGTH`, `BB_MULT`, `PIVOT_LEFT/RIGHT` for strategy 2; `BAR_MINUTES_3`,
`VWAP_RECENT_WINDOW`, `VWAP_TARGET_BAND`, `RSI_OVERSOLD/OVERBOUGHT` for
strategy 3; `BAR_MINUTES_4`, `EMA_LENGTH`, `TREND_LOOKBACK`, `RANGE_BARS`,
`ATR_LENGTH`, `CONSOLIDATION_MAX_ATR_MULT`, `TARGET_RR`, `TIME_EXIT_BARS`
for strategy 4; `BAR_MINUTES_5`, `EMA_LENGTH_5`, `FIRST_HOUR_END`,
`TARGET_RR_5` for strategy 5; `BAR_MINUTES_6`, `EMA_FAST_6`, `EMA_SLOW_6`,
`TARGET_RR_6`, `MARTINGALE_MAX_MULTIPLIER` for strategy 6), and the
reward/penalty values.

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
touching `indicators.py`, the strategy modules, or `telegram_bot.py` at
all. Say the word if you'd like that swapped in.

Strategy 3 specifically needs real **volume** for a meaningful VWAP —
index tickers like `^NSEI` typically report zero volume on yfinance. The
bot detects this and automatically falls back to an equal-weighted
running average instead of crashing or producing a flat line (see
`indicators.session_vwap`), and logs a one-time warning when it does.
For a truer VWAP, point `SYMBOL` at a stock or futures ticker that
carries real volume.

## Files

| File | Purpose |
|---|---|
| `indicators.py` | Heiken Ashi, Parabolic SAR, RSI, Bollinger Bands, pivot detection, session VWAP, EMA/ATR/trend/range — pure functions |
| `data_feed.py` | Pulls + resamples Yahoo Finance data into N-minute bars |
| `strategy.py` | Strategy 1 state machine (setup/entry/target1/target2/SL) |
| `strategy_rsi_bb.py` | Strategy 2 state machine (divergence/setup/entry/target/SL) |
| `strategy3.py` | Strategy 3 state machine (VWAP bounce setup/entry/target/SL) |
| `strategy4.py` | Strategy 4 state machine (breakout entry/target/SL/time-exit) |
| `strategy5.py` | Strategy 5 state machine (EMA extension setup/entry/target/SL, first-hour only) |
| `strategy6.py` | Strategy 6 state machine (EMA(5,14) mean-reversion setup/entry/target/SL) |
| `telegram_bot.py` | Telegram sendMessage wrapper + message formatting for all six strategies |
| `main.py` | Polling loop for all six strategies, market-hours guard, state persistence, reward scoring, Martingale sizing, end-of-day report |
| `send_test_message.py` | One-off Telegram connectivity check |
| `.env.example` | Copy to `.env` and fill in your settings |
| `tests/test_dryrun.py` | Synthetic (no network) check of strategy 1's logic |
| `tests/test_dryrun_bb.py` | Synthetic (no network) check of strategy 2's logic |
| `tests/test_dryrun_vwap.py` | Synthetic (no network) check of strategy 3's logic |
| `tests/test_dryrun_consolidation.py` | Synthetic (no network) check of strategy 4's logic |
| `tests/test_dryrun_ma.py` | Synthetic (no network) check of strategy 5's logic |
| `tests/test_dryrun_meanrev.py` | Synthetic (no network) check of strategy 6's logic + Martingale sizing |
| `tests/test_dryrun_report.py` | Synthetic (no network) check of the end-of-day report's formatting/analysis |

## Disclaimer

This is a mechanical translation of a discretionary strategy description
into rules, for educational/informational purposes. It is not investment
advice, and past strategy performance (including the example trades in
the original write-up) does not guarantee future results. You are
responsible for validating any signal before acting on it and for all
trading decisions and outcomes.
