# Nifty 50 Signal Bot (13 strategies)

A rule-based Telegram signal bot mechanically implementing 13
discretionary strategies from "51 Trading Strategies" by Aseem Singhal —
6 from the general strategies chapter, 7 from the "Intraday Strategies"
chapter:

1. **Heiken Ashi + Parabolic SAR + RSI** (3-minute chart)
2. **RSI Divergence + Bollinger Bands** (1-minute chart)
3. **RSI + VWAP Scalping** (1-minute chart)
4. **1-Minute Consolidation Breakout Scalping** (1-minute chart)
5. **Moving Average Scalping** (5-minute chart, first hour only)
6. **Mean Reversion EMA(5,14) + Martingale sizing** (1-minute chart)
7. **Moving Average + Fibonacci** (5-minute chart)
8. **Supertrend + Pivot Points** (5-minute chart)
9. **VWAP + Standard Deviations** (5-minute chart)
10. **RSI + Volume Oscillator** (5-minute chart)
11. **Pullback + Pivot Points** (5-minute chart)
12. **Double RSI** (5-min chart + hourly RSI)
13. **CPR with Trend Following** (5-minute chart)

All thirteen run concurrently and independently (each can be switched
off in `.env`), and every Telegram message opens with which strategy
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
  the fall). **Entry is immediate on that candle's close** — per the
  write-up ("BUY entry is triggered when the price makes a green
  candle"), there's no further breakout confirmation required (unlike
  strategy 1's explicit "buy above the high of the bullish candle").
  Stop-loss = that candle's low, target = the (upper) Bollinger Band
  value → *entry* alert.
- **Target hit**: price reaches the Bollinger Band target → *closed*
  alert. **Stop-loss hit**: *stopped out* alert. Unlike strategy 1, this
  one is a single stop/target trade — the write-up doesn't call for a
  partial exit here.
- Swing points need a few bars to confirm (same as TradingView's Pivot
  High/Low), and a divergence that doesn't get a reversal candle within
  15 bars is dropped.

Short setups are the mirror: swing high at/above the upper band with a
higher high in price but a lower high in RSI (bearish divergence), then
an immediate short entry on the next red reversal candle, target at the
lower band.

## Strategy 3 logic: RSI + VWAP Scalping (1-min)

**Long setup**:
- RSI(14) dipped into the **oversold zone (<30)** within the last 10
  bars (configurable), and
- this candle's low touches/dips to the session **VWAP** line and it
  closes back **above** VWAP as a green (bullish) candle — a support
  bounce. **Entry is immediate on that candle's close** (same fix as
  strategy 2 — the write-up doesn't ask for a further breakout above
  it), stop-loss = the VWAP value, target = the upper VWAP std-dev band
  (band 1 by default; configurable) → *entry* alert.
- **Target hit**: price reaches the VWAP band target → *closed* alert.
  **Stop-loss hit**: *stopped out* alert. Single stop/target trade, same
  as strategy 2 — the write-up mentions "trail it for maximum gains" as
  a discretionary option but gives no mechanical rule for it, so it
  isn't automated.

Short setups are the mirror: RSI overbought (>70) recently, then an
immediate short entry on a red candle that rejects back below VWAP from
above.

VWAP needs real traded **volume** to be meaningful — see "Data source
limitations" below, this is the one strategy most affected by it.

## Strategy 4 logic: 1-Minute Consolidation Breakout Scalping (1-min)

Like strategies 2 and 3, entry here is **immediate** — the breakout
candle itself is the entry, there's no separate "wait for a further
breakout" stage:

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
  (short) — same setup → entry pattern as strategy 1 (Heiken Ashi +
  SAR + RSI), matching the write-up's own worked example ("my entry is
  triggered on the 9th candle which broke the previous low"). Stop-loss
  = the signal candle's low (long) / high (short).
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

## Strategy 7 logic: Moving Average + Fibonacci (5-min)

From the book's "Intraday Strategies" chapter (2.1). **Indicators**:
SMA(200, close) on a 5-minute chart, plus a Fibonacci Retracement drawn
between the most recent confirmed swing low/high pivot pair (same
pivot-confirmation mechanism as strategy 2).

- Uptrend (price above SMA200, SMA not falling) → watch the 23.6%-78.6%
  retracement band of the last swing-low → swing-high leg for a bullish
  candle taking support there. BUY is a breakout order above that
  candle's high (like strategy 1 — a further breakout of the signal
  candle is required, unlike strategies 2/3's immediate entry).
  Downtrend is the exact mirror (SELL below a bearish candle's low in
  the retracement band of a swing-high → swing-low leg).
- **Stop-loss**: the next Fibonacci level beyond where price found
  support/resistance ("the lower/upper Fibonacci level" in the write-up).
- **Target**: minimum 1:2 risk:reward (`TARGET_RR_7`).
- **Fake-breakout filter**: the write-up's "thing to remember" — a
  falling MA under a long (or rising MA over a short) risks a fake
  breakout — is modeled as requiring the SMA's own slope to not be
  moving against the trade.

## Strategy 8 logic: Supertrend + Pivot Points (5-min)

Book section 2.2. **Indicators**: Supertrend (ATR length 7, per "set the
ATR range to 7") and Standard Pivot Points (only R1/S1), 5-minute chart.

- BUY: price closes above R1 and stays above the Supertrend line → wait
  for a bullish candle (signal candle) → BUY above its high (breakout
  order, stop-loss below the Supertrend value). SELL is the mirror below
  S1.
- **Exit**: "target at the trader's discretion, OR exit when price
  closes below the Supertrend" — since the Supertrend line trails with
  price, that single flip is both the win and loss exit here. The bot
  classifies it as a target hit or stop-loss by comparing the exit price
  to entry, so it still slots into the usual accuracy reporting.

## Strategy 9 logic: VWAP + Standard Deviations (5-min)

Book section 2.3. **Indicators**: session VWAP (hlc3) with only the
2-standard-deviation upper/lower band, 5-minute chart.

- Price closes below the lower band (oversold) → a green reversal candle
  forms → BUY above its high (breakout order), stop-loss below its low.
  SELL is the mirror at the upper band.
- **Two targets**, same partial-booking shape as strategy 1: **Target 1
  at the VWAP line** (book half, move stop to breakeven), **Target 2 at
  the opposite band** (close the rest). Preferred minimum 1:2 R:R.

## Strategy 10 logic: RSI + Volume Oscillator (5-min)

Book section 2.4. **Indicators**: RSI(14) and Volume Oscillator(5, 10) —
a fast/slow SMA crossover of volume, expressed as a % difference,
oscillating roughly ±30% per the write-up's own observation.

- BUY entry is **immediate** (no breakout wait, unlike strategies 7-9)
  when RSI is at/below 30 **and** the Volume Oscillator is at/below -30%
  on the same candle — both in their oversold zone in tandem. Stop-loss
  at the most recent confirmed swing low. SELL is the exact mirror
  (RSI≥70, Volume Oscillator ≥30%, stop at swing high).
- **Target**: the write-up's own "conservative Risk:Reward ratio" of 1:2
  (`TARGET_RR_10`).
- **Needs real volume**: like strategy 3's VWAP, this needs actual traded
  volume — `^NSEI` reports zero on yfinance, so the Volume Oscillator
  sits at 0 and this strategy will rarely fire on the index ticker (the
  bot logs a one-time warning). Point `SYMBOL` at a stock/futures ticker
  with real volume for this one to be meaningful.

## Strategy 11 logic: Pullback + Pivot Points (5-min)

Book section 2.5. **Indicators**: Standard Pivot Points (P, R1, R2, S1,
S2), 5-minute chart.

- Price pulls back to a pivot level (either holding it without breaking,
  or retesting it just after breaking through — both resolve the same
  way here) and a bullish candle closes back above the level → BUY,
  **immediate entry** at that candle's close. Stop-loss at its low. SELL
  is the mirror.
- **Target**: the very next pivot level above (long) / below (short)
  entry — the write-up notes this often works out near 1:4, though it's
  whatever the next level actually is. Falls back to a fixed 1:2 R:R
  (`TARGET_RR_11`) only when there's no further level left in the day's
  pivot ladder.

## Strategy 12 logic: Double RSI (5-min + hourly)

Book section 2.6. **Indicators**: RSI(14) on the 5-minute chart (the
"first RSI") plus RSI(14) computed on 1-hour bars and held constant
across each hour's 5-minute candles (the "second RSI") — filters out
noise the fast RSI alone would react to.

- BUY: **immediate entry** when the 5-min RSI is below 30 **and** the
  hourly RSI is above 50, together on the same candle. Stop-loss at that
  candle's low. SELL is the mirror (5-min RSI above 70, hourly RSI below
  50).
- **Exit**: "the take profit point is at the pivot of the first RSI" —
  the trade closes once the 5-min RSI pivots back through the level that
  triggered entry (back above 30 for a BUY, back below 70 for a SELL), a
  hard stop-loss at the signal candle's low/high protecting it before
  that happens. Classified as a target hit or stop-loss by comparing
  exit price to entry, same convention as strategy 8's Supertrend exit.

## Strategy 13 logic: CPR with Trend Following (5-min)

Book section 2.7. **Indicators**: daily Pivot Points plus the Central
Pivot Range (CPR: top/bottom central pivot), and its width relative to
ATR(14) — narrow (≤ `CPR_NARROW_ATR_MULT_13` × ATR) vs wide.

- **Wide CPR** (range-bound day): mean-reversion at pivot levels, same
  shape as strategy 11 — a reversal candle holds/reclaims a touched
  level, **immediate entry**, stop-loss at that candle's low/high, target
  at the next pivot level (or 1:2 R:R fallback).
- **Narrow CPR** (trending day): breakout mode, same shape as strategy
  4 — a candle's close crosses a pivot level it was previously on the
  other side of, **immediate entry**, stop-loss at that candle's
  low/high. "Trail it until market reverses" isn't mechanical, so a
  fixed 1:2 R:R (`TARGET_RR_13`) is used as the target.

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
Configurable in `.env`: `REWARD_TARGET1` / `REWARD_TARGET2` (strategies
1 & 9's partial/final targets), `REWARD_TARGET` (every other strategy's
single target), `PENALTY_STOPLOSS` (all thirteen). Strategy 4's time-exit
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
`MARKET_CLOSE`, per-strategy `STRATEGY1_ENABLED` through
`STRATEGY13_ENABLED` toggles, each strategy's own indicator settings
(`BAR_MINUTES`, `SAR_START/STEP/MAX` for strategy 1; `BAR_MINUTES_2`,
`BB_LENGTH`, `BB_MULT`, `PIVOT_LEFT/RIGHT` for strategy 2; `BAR_MINUTES_3`,
`VWAP_RECENT_WINDOW`, `VWAP_TARGET_BAND`, `RSI_OVERSOLD/OVERBOUGHT` for
strategy 3; `BAR_MINUTES_4`, `EMA_LENGTH`, `TREND_LOOKBACK`, `RANGE_BARS`,
`ATR_LENGTH`, `CONSOLIDATION_MAX_ATR_MULT`, `TARGET_RR`, `TIME_EXIT_BARS`
for strategy 4; `BAR_MINUTES_5`, `EMA_LENGTH_5`, `FIRST_HOUR_END`,
`TARGET_RR_5` for strategy 5; `BAR_MINUTES_6`, `EMA_FAST_6`, `EMA_SLOW_6`,
`TARGET_RR_6`, `MARTINGALE_MAX_MULTIPLIER` for strategy 6;
`BAR_MINUTES_7`, `SMA_LENGTH_7`, `PIVOT_LEFT/RIGHT_7`,
`MA_SLOPE_LOOKBACK_7`, `TARGET_RR_7` for strategy 7; `BAR_MINUTES_8`,
`ATR_LENGTH_8`, `SUPERTREND_MULT_8` for strategy 8; `BAR_MINUTES_9`,
`VWAP_BAND_MULT_9` for strategy 9; `BAR_MINUTES_10`, `VOL_OSC_FAST_10`,
`VOL_OSC_SLOW_10`, `PIVOT_LEFT/RIGHT_10`, `TARGET_RR_10` for strategy 10;
`BAR_MINUTES_11`, `TARGET_RR_11` for strategy 11; `BAR_MINUTES_12` for
strategy 12; `BAR_MINUTES_13`, `ATR_LENGTH_13`, `CPR_NARROW_ATR_MULT_13`,
`TARGET_RR_13` for strategy 13), and the reward/penalty values.

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
| `indicators.py` | Heiken Ashi, Parabolic SAR, RSI, Bollinger Bands, pivot detection, session VWAP, EMA/ATR/trend/range, SMA, Supertrend, daily pivots/CPR, Volume Oscillator, Fibonacci levels, double RSI — pure functions |
| `data_feed.py` | Pulls + resamples Yahoo Finance data into N-minute bars |
| `strategy.py` | Strategy 1 state machine (setup/entry/target1/target2/SL) |
| `strategy_rsi_bb.py` | Strategy 2 state machine (divergence/immediate entry/target/SL) |
| `strategy3.py` | Strategy 3 state machine (VWAP bounce/immediate entry/target/SL) |
| `strategy4.py` | Strategy 4 state machine (breakout entry/target/SL/time-exit) |
| `strategy5.py` | Strategy 5 state machine (EMA extension setup/entry/target/SL, first-hour only) |
| `strategy6.py` | Strategy 6 state machine (EMA(5,14) mean-reversion setup/entry/target/SL) |
| `strategy7.py` | Strategy 7 state machine (Fibonacci pullback setup/breakout entry/target/SL) |
| `strategy8.py` | Strategy 8 state machine (Supertrend+R1/S1 setup/breakout entry/trend-flip exit) |
| `strategy9.py` | Strategy 9 state machine (VWAP-band reversal setup/breakout entry/target1/target2/SL) |
| `strategy10.py` | Strategy 10 state machine (RSI+VolOsc immediate entry/target/SL) |
| `strategy11.py` | Strategy 11 state machine (pivot pullback immediate entry/target/SL) |
| `strategy12.py` | Strategy 12 state machine (double-RSI immediate entry/RSI-pivot exit) |
| `strategy13.py` | Strategy 13 state machine (CPR narrow/wide immediate entry/target/SL) |
| `telegram_bot.py` | Telegram sendMessage wrapper + message formatting for all thirteen strategies |
| `main.py` | Polling loop for all thirteen strategies, market-hours guard, state persistence, reward scoring, Martingale sizing, end-of-day report |
| `send_test_message.py` | One-off Telegram connectivity check |
| `.env.example` | Copy to `.env` and fill in your settings |
| `tests/test_dryrun.py` | Synthetic (no network) check of strategy 1's logic |
| `tests/test_dryrun_bb.py` | Synthetic (no network) check of strategy 2's logic |
| `tests/test_dryrun_vwap.py` | Synthetic (no network) check of strategy 3's logic |
| `tests/test_dryrun_consolidation.py` | Synthetic (no network) check of strategy 4's logic |
| `tests/test_dryrun_ma.py` | Synthetic (no network) check of strategy 5's logic |
| `tests/test_dryrun_meanrev.py` | Synthetic (no network) check of strategy 6's logic + Martingale sizing |
| `tests/test_dryrun_ma_fib.py` | Synthetic (no network) check of strategy 7's logic |
| `tests/test_dryrun_supertrend.py` | Synthetic (no network) check of strategy 8's logic |
| `tests/test_dryrun_vwap_std.py` | Synthetic (no network) check of strategy 9's logic |
| `tests/test_dryrun_rsi_volosc.py` | Synthetic (no network) check of strategy 10's logic |
| `tests/test_dryrun_pivot_pullback.py` | Synthetic (no network) check of strategy 11's logic |
| `tests/test_dryrun_double_rsi.py` | Synthetic (no network) check of strategy 12's logic |
| `tests/test_dryrun_cpr.py` | Synthetic (no network) check of strategy 13's logic (both narrow and wide CPR modes) |
| `tests/test_dryrun_report.py` | Synthetic (no network) check of the end-of-day report's formatting/analysis |

## Disclaimer

This is a mechanical translation of a discretionary strategy description
into rules, for educational/informational purposes. It is not investment
advice, and past strategy performance (including the example trades in
the original write-up) does not guarantee future results. You are
responsible for validating any signal before acting on it and for all
trading decisions and outcomes.
