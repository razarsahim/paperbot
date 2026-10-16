# Implementation plan and acceptance checklist

## Phase 0 — Runnable safety-first MVP (included)

- [x] GBP-denominated virtual BTC spot cash account and long-only position
- [x] No futures, leverage, shorting, exchange keys, real-order methods or real-money execution
- [x] Public Kraken spot price/candle adapter via CCXT
- [x] No-look-ahead hourly EMA20/50 reclaim strategy; ATR stop and fixed target
- [x] Risk sizing accounting for assumed fees and modeled stop slippage
- [x] Maximum one position, no averaging down, never widen stops
- [x] Entry lockouts after daily 2% / cumulative 5% simulated drawdown
- [x] Public candle history fetch and CSV-backed historical backtest
- [x] Persistent virtual positions, trade journal, duplicate-bar protection, local process lock
- [x] Local read-only Streamlit dashboard
- [x] Sample explicitly synthetic candle file and automated offline unit tests

**Definition of done for this phase:** unit tests pass; an actual Mac or server with network can fetch public BTC/GBP candles and run `paperbot once`; optional `paperbot run` operates only while the process stays active.

## Phase 1 — Market-data and model validation (partially built)

- [x] Verify Kraken BTC/GBP live public access in the user's environment (verified 2026-10-16: fetch-history saved 719 closed hourly candles; live snapshot returned fresh bid/ask).
- [ ] Obtain at least a year of accurately sourced historical BTC/GBP spot prices from an authorized data provider. Kraken's default OHLC endpoint cannot provide arbitrary years of hourly history.
- [ ] Validate timezone normalization, missing candles, public quote timestamps and spread/fees by exchange.
- [x] Keep strategy parameters frozen on a test set. `paperbot walkforward` runs chronological out-of-sample windows with cost-adjusted buy-and-hold and no-trade baselines. (Only ~30 days of data available so far: statistically meaningless; needs the year of history above.)
- [x] Document number of trades, sample size, costs, maximum drawdown, win rate, profit factor and net expectancy (walkforward report + dashboard statistics). Current short-sample results are unconvincing: keep the bot as a simulator.

## Phase 2 — Reliability and reporting (partially built)

- [x] Persist mark-to-market equity and price history (`equity_history` per tick); dashboard equity curve and peak drawdown are computed from it.
- [x] Idempotent tick processing for repeated snapshots and restarts (duplicate-bar guard, same-timestamp snapshot replacement; covered by adverse tests).
- [x] Add alerts for feed failures, drawdown locks, simulated entries/exits, and positions whose stops weren't observed (`MONITORING GAP`); JSONL log + optional webhook/desktop.
- [x] Add integration tests for market outages, flash-crash gaps, repeated ticks and restart timing (`tests/test_adverse.py`). Concurrent-access testing beyond the process lock remains open.
- [ ] Improve tick-level fill simulation, bid/ask spreads, conservative gap handling and realistic platform fees (spread model is still a crude max_spread/10 assumption).

## Phase 3 — Paper deployment, observation, and decision (not yet built)

- [ ] Deploy the read-only bot on a private always-on server if desired; run only one engine process per DB.
- [ ] Observe several months of forward paper results without tuning on the same evaluation window.
- [ ] Audit the results against actual public market data and a simple hold benchmark.
- [ ] Independently review whether continuing paper simulation has educational value.

**Non-goal:** this project intentionally has no path to placing live orders. Do not add API keys, futures, leverage, deposits, withdrawals or private trading endpoints to this codebase.
