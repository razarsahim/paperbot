# Crypto PaperBot — BTC/GBP, no leverage

**Paper trading only.** This bot cannot place real orders. It has no API-key handling or exchange trade methods. It reads public spot market data, applies an illustrative, unvalidated strategy, simulates entries/exits, stores simulated positions and trades in SQLite, and shows a local dashboard.

This project is an engineering prototype, not a profitable/validated strategy or financial advice. A strategy that works on synthetic data or historical candles may lose money immediately in new market conditions. **Do not connect real funds to it.**

## What is included

- Virtual initial **£1,000** portfolio in **BTC/GBP** (not USDT), read-only Kraken spot data by default.
- 1-hour, bar-close EMA20/50 pullback-reclaim strategy; ATR-based predefined stops and 2:1 illustrative target.
- 0.5% maximum planned risk budget per trade including modeled entry/exit fees and stop slippage; may take zero positions.
- One long-only spot position at a time; no borrowing, no leverage, no averaging down.
- Stops never widen, optional tightening on completed candles; stop and target checked on each public ticker poll (not exchange-native orders).
- Daily 2% lock on NEW entries until the next UTC day; permanent 5% peak-to-equity drawdown lock on new entries until the database is manually reset after review. Existing positions still receive stop/target checks.
- Last processed bar and portfolio state persisted across restarts; single-process lock for CLI.
- Backtesting with next-bar-open signals, simulated costs, gap handling and stop-first interpretation when stop and target are hit on the same bar.
- Local, **read-only** Streamlit dashboard and offline automated tests.

## Fast start on macOS using Claude Code

Requirements: Python 3.10+, internet only for the live public data mode.

```bash
cd crypto-paper-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m pytest -q
paperbot backtest --csv data/synthetic_demo_btc_gbp.csv
```

**Synthetic example warning:** the `data/synthetic_demo_btc_gbp.csv` file is computer-generated demonstration candles, NOT Bitcoin price history, and its backtest returns have no financial meaning.

Before paper-running, download **real** public spot data to do an initial historical check (exchange history is limited; Kraken often has only about 720 recent hourly bars):

```bash
paperbot fetch-history --csv data/real_kraken_btc_gbp.csv
paperbot backtest --csv data/real_kraken_btc_gbp.csv
paperbot walkforward --csv data/real_kraken_btc_gbp.csv --windows 3
```

`walkforward` runs a frozen-parameter rolling out-of-sample evaluation:
chronological non-overlapping windows, each scored with only pre-window
history, compared against cost-adjusted buy-and-hold and the no-trade
baseline, labelled with dates and data provenance. With only ~30 days of
Kraken history the sample is far too small to conclude anything.

The downloaded file gets a `.metadata.json` companion with its provenance. Because ~30 days of data is far too short for strong validation, treat this as a **smoke test**, not evidence that the method is profitable. Do not optimize based on the synthetic example or repeatedly tweak indicators until a small backtest looks good.

To take one public Kraken BTC/GBP market snapshot and simulate any eligible activity:

```bash
paperbot once
paperbot status
```

To keep it fully autonomous **while your computer or server is on**:

```bash
paperbot run
```

Open a separate terminal, activate the same venv, then:

```bash
streamlit run dashboard.py
```

Open http://localhost:8501 and **keep it private**. Dashboard is not authenticated.

The first `paperbot once` can produce **no trade**: a strategy signal must coincide with the latest newly closed hourly candle and a tight entry-time window. This is intentional; no trades is often the correct result. The script needs internet to download public data; if Kraken rejects the symbol in your region or a call fails, fail safely without simulated orders. The developer test environment cannot verify your connection to Kraken.

## Run using Docker (optional)

```bash
docker compose up --build -d
docker compose logs -f paper-engine
```

Dashboard: http://localhost:8501. Data persisted in `./state/`. Docker Compose `env_file.required` needs a modern Docker Compose; if yours is older, copy `.env.example` to `.env` first.

```bash
cp .env.example .env
```

Never expose port 8501 on a public interface; no authentication is implemented. Stop bot with `docker compose stop paper-engine`.

## How signals and fills work

A LONG simulation is considered when, on a **fully closed hourly candle**, EMA20 > EMA50 and the previous close was at/below its EMA20 while the latest close finishes above EMA20. The strategy is only an educational hypothesis and **has not been validated on live exchange data**.

In `paperbot run`, new signals are considered only within 10 minutes of the candle closing; a missing/stale candle or invalid public quote means NO new position. Entries are simulated using the latest public `ask`, with additional assumed slippage and fees. Existing positions are tested against the latest public `bid` roughly once per minute. **A 1-minute polling interval does not guarantee stop fills**; actual execution could be substantially worse in a fast market. The exchange itself is never given any stop or order.

Backtesting uses previous-candle signals and the next bar's open; it simulates exits using hourly OHLC candles, including adverse gap fill and the conservative stop-first assumption where stop and target are both hit. Historical tick paths are unknown, so bar tests are approximations.

## Configuration

Optional environment variables, e.g.:

```bash
export PAPERBOT_STARTING_BALANCE=1000
export PAPERBOT_RISK_PER_TRADE=0.005
export PAPERBOT_MAX_DAILY_DRAWDOWN=0.02
export PAPERBOT_MAX_TOTAL_DRAWDOWN=0.05
export PAPERBOT_FEE_RATE=0.004
export PAPERBOT_SLIPPAGE_RATE=0.001
```

See `.env.example`. **The CLI does not auto-load `.env`;** `export` the values or use Docker Compose, which reads `.env`.

### Alerts and reliability

Every `paperbot once`/`run` tick appends noteworthy events (simulated
entries/exits, drawdown locks, wide spreads, feed failures/recovery) to
`state/alerts.jsonl`. Optionally set `PAPERBOT_WEBHOOK_URL` (a private
webhook you own; the JSON body includes `text`/`content` fields) and/or
`PAPERBOT_DESKTOP_NOTIFY=1` for macOS notifications. Alert delivery
failures are printed to stderr and never interrupt the engine.

During feed outages `paperbot run` backs off exponentially (capped at 15
minutes), alerts after 3 consecutive failures and again on recovery, and
never fabricates data. The engine persists per-tick mark-to-market equity
snapshots (`equity_history`), and after a restart or outage it emits a
`MONITORING GAP` event if an open position's stop went unobserved for more
than `PAPERBOT_MONITOR_GAP_SECONDS` (default 300) — a reminder that
realized losses can exceed the planned risk when nobody was watching.

`PAPERBOT_EXCHANGE` is restricted to public spot-data providers `kraken`, `coinbase` and `bitstamp`; verify `PAPERBOT_SYMBOL` really trades there. Use separate `--db` paths when changing the exchange/symbol. The database records the market symbol; other environment changes (fees, risk, start balance) don't rewrite previous simulated trades.

The supplied risk parameter is a **planned** loss limit, not a guarantee: overnight price gaps, spread widening, missed polls, liquidity and outages can cause larger realized losses even in the model. Lockouts prevent *new* simulated entries; they do not force-close an existing position.

## Stop / reset

Stop `paperbot run` with Ctrl+C (or stop the Docker service). The next start loads positions and portfolio from `state/paper.sqlite`. Never run multiple active processes against one DB; the CLI uses an exclusive local process lock. To reset a simulation **only after you decide to discard its history**, stop the engine and move the entire `state/` folder to a dated archive, then restart. Recreating the database begins a new virtual portfolio.

## Limits and next steps

- Live strategy execution and Kraken connectivity have **not been exercised in the build environment** (no internet and CCXT was not installed there); run `paperbot once` on your Mac to verify actual read-only market data.
- The dashboard shows a persisted mark-to-market equity curve, drawdown from the running peak, trade statistics and recent alerts; databases created by older versions fall back to realised-P&L-only charts until the updated engine runs.
- No live execution; adding live execution is expressly out of scope.
- No guaranteed uptime or high-availability failover. Cloud deployment, market data resilience, and realistic execution modelling require more engineering.
- Tests and a synthetic example are software checks, **not evidence of profitability**. Evaluate a representative out-of-sample history before drawing conclusions, and account for strategy overfitting.

## UK regulatory note

The FCA prohibits firms from marketing, distributing, or selling crypto derivatives such as crypto futures to UK retail customers (see FCA Handbook COBS 22.6). This software instead simulates unleveraged spot-market positions; it does not connect to a brokerage or implement derivatives.

## Continue development with Claude Fable

Install official Claude Code and run inside the project:

```bash
claude --model claude-fable-5-1
```

Paste: "Read README.md and CLAUDE.md, inspect the paper-trading engine, run the tests, identify critical correctness and security issues, then add walk-forward validation on real historical spot candles. Never add any real-order or futures execution. Preserve the existing strict risk controls and test all changes."
