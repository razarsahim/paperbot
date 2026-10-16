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

## Phase 1 — Market-data and model validation (not yet built)

- [ ] Verify Kraken BTC/GBP live public access in the user's environment.
- [ ] Obtain at least a year of accurately sourced historical BTC/GBP spot prices from an authorized data provider. Kraken's default OHLC endpoint cannot provide arbitrary years of hourly history.
- [ ] Validate timezone normalization, missing candles, public quote timestamps and spread/fees by exchange.
- [ ] Keep strategy parameters frozen on a test set. Run chronological out-of-sample and walk-forward testing; compare with buy-and-hold and a no-trade baseline.
- [ ] Document number of trades, sample size, costs, maximum drawdown, win rate, profit factor and net expectancy. If unconvincing, leave bot running only as a simulator.

## Phase 2 — Reliability and reporting (not yet built)

- [ ] Persist mark-to-market equity and price history; calculate equity-based metrics properly.
- [ ] Build replayable, idempotent event processing for outages and stale exchange feeds.
- [ ] Add alerts for feed failures, total drawdown lock, and positions whose stops weren't observed.
- [ ] Add integration tests for market outages, gap scenarios, repeated ticks, concurrent access and restart timing.
- [ ] Improve tick-level fill simulation, bid/ask spreads, conservative gap handling and realistic platform fees.

## Phase 3 — Paper deployment, observation, and decision (not yet built)

- [ ] Deploy the read-only bot on a private always-on server if desired; run only one engine process per DB.
- [ ] Observe several months of forward paper results without tuning on the same evaluation window.
- [ ] Audit the results against actual public market data and a simple hold benchmark.
- [ ] Independently review whether continuing paper simulation has educational value.

**Non-goal:** this project intentionally has no path to placing live orders. Do not add API keys, futures, leverage, deposits, withdrawals or private trading endpoints to this codebase.
