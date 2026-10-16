# Claude Code project instructions

Build and refine a **research and paper-trading** Python system, NOT a real trading bot.

## Hard constraints
- Never add `create_order`, `create_market_order`, `create_limit_order`, exchange API key handling, private balances, futures, swaps, shorting, leverage, exchange credentials, deposits or withdrawals.
- No live-money execution, even behind an environment flag. If asked, explain that a separate regulated/safety review and new project scope would be needed.
- Keep BTC/GBP spot, virtual £1,000 portfolio, deterministic indicators and fully auditable signal rules.
- Default to no trades when feeds are stale, irregular, empty, suspect or unavailable.
- Never widen a stop-loss, add to a losing position, or permit new entries after lockouts.
- Treat all performance claims as unproven; do not optimize synthetic fixture to imply profitability.
- Backtests must use ONLY previous-bar signals, model costs, gaps, and ambiguous intrabar sequences conservatively.

## Developer commands
- Install: `python3 -m pip install -e '.[dev]'`
- Tests: `python3 -m pytest -q`
- Offline example: `paperbot backtest --csv data/synthetic_demo_btc_gbp.csv`
- Live PUBLIC market data history: `paperbot fetch-history --csv data/real_kraken_btc_gbp.csv`
- Public read-only data tick: `paperbot once`
- Local read-only dashboard: `streamlit run dashboard.py`

## Improvement priorities
1. Deep test/audit of same-candle order handling, partial fills and spread assumptions.
2. Walk-forward train/validation/test splits and out-of-sample reports using REAL downloaded historical spot OHLCV, clearly labelled by date and exchange.
3. Persist price/equity snapshots for accurate dashboard equity chart and true intraday drawdown.
4. Public market data fallback, health checks, circuit breakers and alerting without hiding failures.
5. Exchange trading hours / downtime and resilient network handling.
6. Realistic measured maker/taker fees, signal timing, bid/ask spread, and slippage.
7. Maintain strict tests, review changes with diffs, and never claim simulated returns predict future performance.

Any strategy change requires a new backtest and independent out-of-sample validation. Ask for clarification only when a missing input is truly necessary.
