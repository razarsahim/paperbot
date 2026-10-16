# Claude Code project instructions

Build and refine **PaperBot Pro**: a research and PAPER-TRADING system — never a real trading bot. Scope expanded on 2026-10-16 by explicit owner instruction: multi-asset top-20 universe and a **simulated** 10x isolated-margin perpetual engine are in scope; everything real-money remains permanently out of scope.

## Hard constraints (unchanged in spirit, updated in scope)
- Never add order-placement methods (`create_order`, `create_market_order`, …), exchange API keys/credentials, private endpoints, balances, deposits or withdrawals. All exchange access is PUBLIC read-only market data.
- No live-money execution, ever, even behind an environment flag. If asked, explain that a separate regulated/safety review and a new project would be required.
- Leverage, shorting and perpetual-futures mechanics exist ONLY inside the local simulator (`src/paperbot_pro`). If real contract metadata (maintenance margin, fees, precision) is unavailable for an asset, it is NOT ELIGIBLE — never invent a market.
- Virtual portfolio: $1,000 = $900 core sleeve + $100 hype sleeve (hype is WATCH-ONLY until perp support is verified). Legacy BTC/GBP £1,000 spot engine (`src/paperbot`) is frozen: do not modify it or its DB; the user's `paperbot run` process must not be restarted without explicit permission.
- Risk rails: ≤0.5% planned risk/trade (core), ≤3 open positions, ≤1.5% combined planned stop risk, sticky daily 2% lockout, 5% total-drawdown pause. Never widen a stop-loss, never average down, no entries during lockouts, duplicate-entry prevention, state must survive restarts/outages.
- Default to NO trade when feeds are stale, irregular, incomplete, suspect or unavailable. Signals only on fully closed candles.
- Automatic paper entries stay disabled until a validation report artifact exists; treat all performance as unproven (current evidence is NEGATIVE: −2.69%, PF 0.16, 0/3 walk-forward windows). Never optimize synthetic fixtures to imply profitability; report negative findings faithfully.
- Backtests/validation: previous-bar signals only, model fees, funding, slippage, gaps and liquidation conservatively.
- Dashboard/API are read-only, bind 127.0.0.1, no auth → never expose publicly; every displayed value is engine-sourced or visibly badged DEMO.

## Developer commands
- Install: `python3 -m pip install -e '.[dev,pro]'`
- Tests: `python3 -m pytest -q` (legacy 40 tests must always pass)
- Legacy spot engine: `paperbot once | run | backtest | walkforward` (see README)
- Pro API: `propaper api` (http://127.0.0.1:8777)
- Pro universe/scan: `propaper universe`, `propaper scan-once`, `propaper status`
- Dashboard: `cd web && npm run dev` (http://localhost:3000)

## Priorities
1. Correctness of the perp simulator and risk governor (TDD, adverse scenarios: gaps, liquidation, funding across restarts).
2. Honest data plumbing: freshness stamps, NOT ELIGIBLE reasons, audit log of every signal/rejection.
3. Validation before automation; distinct research/backtest/forward-paper views.
4. Reliability: outages, rate limits, cache integrity, restart idempotency.
5. Strict tests after every change; review diffs; never claim simulated returns predict future performance.

Plan of record: `docs/superpowers/plans/2026-10-16-paperbot-pro.md`.
