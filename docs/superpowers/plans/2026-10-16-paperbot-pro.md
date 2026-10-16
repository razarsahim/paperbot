# PaperBot Pro Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline execution chosen by the user: "proceed incrementally"). Steps use checkbox syntax.

**Goal:** Upgrade crypto-paper-bot into PaperBot Pro: a multi-asset (top-20), simulated 10x isolated-margin perpetual PAPER-trading system with a FastAPI read-only backend and a Next.js trading-terminal dashboard — zero real-money execution paths.

**Architecture:** The existing `src/paperbot` spot engine, its SQLite DB, and its 40 tests are frozen and untouched; the live `paperbot run` process keeps running against `state/paper.sqlite`. A new `src/paperbot_pro` package owns its own DB (`state/paperbot_pro.sqlite`), a CoinGecko-ranked universe resolved to exchange perp instruments via ccxt PUBLIC endpoints, a deterministic perp simulator + risk governor (TDD core), a scanner that separates signal → approval → simulated execution with full audit logging, and a read-only FastAPI (`127.0.0.1:8777`) with SSE. A Next.js 15 + TypeScript + Tailwind + shadcn/ui + lightweight-charts app lives in `web/`, typed against the API contract; anything not backed by a real endpoint is badged DEMO.

**Tech Stack:** Python 3.12, ccxt (public only), FastAPI, uvicorn, httpx, sqlite3 WAL; Next.js 15, TypeScript, Tailwind, shadcn/ui, lucide-react, lightweight-charts.

**Spec:** The user's PaperBot Pro prompt of 2026-10-16 (sections 1–8), recorded in this file's Global Constraints; it SUPERSEDES the old CLAUDE.md scope (BTC/GBP-spot-only, no-leverage) — simulated derivatives are now in scope, real-money execution remains permanently out of scope.

## Global Constraints

- PAPER ONLY: no order-placement calls, no API keys/credentials, no private endpoints, no deposits/withdrawals, no real funds — grep-clean of `create_order|apiKey|secret`.
- All market data via public/read-only endpoints; bounded call rates; caches with freshness stamps.
- Virtual portfolio $1,000 = $900 core sleeve + $100 hype sleeve (separate accounting).
- 10x isolated leverage simulation only; if real contract metadata (maint-margin, fees, tick/lot) is unavailable → asset NOT ELIGIBLE, never invent a market.
- Core: ≤0.5% total-equity planned risk/trade, ≤3 open positions, ≤1.5% combined planned stop risk, 2% daily loss lockout (sticky to next UTC day), 5% total drawdown pause-for-review.
- Hype sleeve: WATCH-ONLY until perp-market support verified; own per-trade (0.25%) and cumulative ($30) loss caps; never cross-funded from core.
- Never widen a stop, never average down, no re-entry same symbol same bar, duplicate-entry prevention, state survives restart/midnight/outage.
- No stale/incomplete-candle signals; default to no trade on any data doubt.
- Automatic paper entries DISABLED until a validation report artifact exists (`state/validation_report.json`), and the engine refuses auto-entry without it.
- Every displayed number is engine-sourced or visibly badged DEMO; performance is never claimed predictive (existing results: −2.69%, PF 0.16, 0/3 WF windows — reported as-is).
- API binds 127.0.0.1 only, read-only DB connections (`mode=ro`), CORS restricted to localhost:3000.
- Dashboard: dark premium default + light mode, responsive, skeletons, empty states, accessible contrast.

## Review Focus

1. A coin ranked top-20 whose perp market lacks maintenance-margin metadata → must list as NOT ELIGIBLE with reason, scanner must skip (test in Task C2).
2. Mark price gaps through both stop and liquidation between polls → liquidation (worse) wins; margin wiped, never negative balance beyond margin+fees (test in Task E1).
3. Restart with open simulated perp across a funding timestamp → funding applied once, not duplicated or skipped (test in Task E2).
4. CoinGecko rate-limit/outage mid-refresh → previous universe retained with stale stamp, no partial overwrite (test in Task C1).
5. Two same-bar signals on correlated assets when 1 slot remains → combined-risk cap enforced deterministically, both decisions logged (test in Task E3).

---

## API Contract (frozen before frontend work)

Base `http://127.0.0.1:8777`. All GET, read-only. Key routes:
`/api/health`, `/api/overview`, `/api/universe`, `/api/positions`, `/api/trades?limit&symbol&sleeve`, `/api/trades/{id}`, `/api/signals?limit`, `/api/analytics`, `/api/hype`, `/api/audit?limit`, `/api/settings`, `/api/candles?symbol&tf=5m|15m|1h|4h|1d&limit`, `/api/export/trades.csv`, `/api/events` (SSE: `overview`, `heartbeat`). Shapes are documented in `src/paperbot_pro/api.py` response models and mirrored in `web/src/lib/types.ts`.

## File Structure

- `src/paperbot_pro/__init__.py`
- `src/paperbot_pro/config.py` — frozen ProSettings dataclass + validation (sleeves, caps, leverage=10, exchange order ["bybit","okx","binanceusdm","krakenfutures"], scan cadence, API port)
- `src/paperbot_pro/store.py` — SQLite schema: kv, universe, universe_changes, instruments, positions, trades, signals, funding_events, equity_history, hype_tokens, audit_log
- `src/paperbot_pro/indicators.py` — rsi, macd (ema/atr imported from `paperbot.strategy`)
- `src/paperbot_pro/perp.py` — pure perp math: entry/exit fills, fees, funding, liquidation estimate, unrealized PnL (TDD core)
- `src/paperbot_pro/risk.py` — RiskGovernor: sizing, slots, combined risk, sleeve accounting, sticky locks (TDD core)
- `src/paperbot_pro/universe.py` — CoinGecko top-20 non-stablecoin (category-based exclusion + wrapped/synthetic dedup), instrument resolution, membership diffing
- `src/paperbot_pro/marketdata.py` — public OHLCV/ticker/funding with TTL cache, freshness, bounded rate
- `src/paperbot_pro/scanner.py` — generate_signals(bars, cfg) separate from approve(signal, governor) separate from execute_paper(...); every decision logged
- `src/paperbot_pro/engine.py` — orchestration loop + outage backoff; auto-entry gate on validation artifact
- `src/paperbot_pro/validation.py` — per-market + portfolio backtest/walk-forward with perp costs
- `src/paperbot_pro/api.py` — FastAPI read-only + SSE
- `src/paperbot_pro/cli.py` — `propaper api|universe|scan-once|run|validate|status`
- `tests/pro/test_perp.py`, `test_risk.py`, `test_store.py`, `test_universe.py`, `test_scanner.py`, `test_api.py` (offline; fixture JSON payloads in `tests/pro/fixtures/`)
- `web/` — Next.js app (src/app routes: overview, scanner, positions, history, analytics, hype, activity, settings; src/components/*, src/lib/api.ts, src/lib/types.ts)

## Phases → Tasks

### Phase A (audit, snapshot, plan, mock UI)
- [x] A1 Audit + DB backup (`backups/2026-10-16/paper.sqlite`, verified tables/counts) + this plan.
- [x] A2 CLAUDE.md scope rewrite (new authority; preserve all no-real-money rails). Commit.
- [x] A3 `web/` scaffolded via agent: Next.js 16 + shadcn + lightweight-charts, 9 pages, DEMO/LIVE-SIM badging; `npm run build` + eslint + all-routes-200 verified.

### Phase B (read-only bridge to EXISTING engine)
- [x] B1 FastAPI with legacy bridge (mode=ro), /api/health, SSE (+?limit for tests); TestClient tests; boot smoke against real DBs.

### Phase C (top-20 universe + market data + scanner)
- [x] C1 universe.py TDD: category-based exclusion, top-20, failure keeps previous, membership diff log.
- [x] C2 instrument resolution TDD: eligible only with real metadata (incl. tier-1 maintenance margin); NOT_ELIGIBLE reasons. Live: 16/20 eligible on bybit.
- [x] C3 marketdata TTL cache (stale-with-age on outage); closed-candle scanner (long + mirrored short, params frozen/reproducible). Live scan: 16 markets, 2 signals, 0 opened (gated).

### Phase D (hype radar, watch-only)
- [x] D1 hype.py: GeckoTerminal trending pools, deterministic evidence-based scoring, hard rejects, honeypot risk always disclosed, never ELIGIBLE. Live: 20 tokens, all WATCH_ONLY/REJECTED. (New-pool per-chain sweep beyond trending: pending.)

### Phase E (perp simulator + risk governor + gated automation)
- [x] E1 perp.py TDD (9 tests): sizing with costs, liq-first gaps, observed-price stop fills, target never better, margin-bounded loss.
- [x] E2 funding idempotent across restarts (funding_events PK; test proves single application).
- [x] E3 risk.py TDD (8 tests): all caps/locks/sleeves + every verdict logged.
- [x] E4 engine run_cycle with gates; pause reason in /api/overview; offline integration tests.
- [x] E5 validation.py + `propaper validate`; LIVE artifact: 16 markets, 265 trades, 5/16 profitable, mean −1.74% — NEGATIVE/UNPROVEN. (True multi-market portfolio-level concurrency simulation: pending; warned in report.)

### Phase F (integration, security, E2E)
- [x] F1 93 tests green (40 legacy preserved), web build green, live API E2E against populated DB, security grep clean, README-Pro added. Pending: visual browser review of live dashboard, multi-day soak of `propaper run`.

Each task: failing test → implement → full suite → commit (TDD per superpowers:test-driven-development).
