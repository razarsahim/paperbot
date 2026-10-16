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
- [ ] A2 CLAUDE.md scope rewrite (new authority; preserve all no-real-money rails). Commit.
- [ ] A3 Scaffold `web/` via agent against the frozen API contract with typed mock fallbacks badged DEMO; `npm run build` must pass.

### Phase B (read-only bridge to EXISTING engine)
- [ ] B1 FastAPI app exposing legacy spot engine data (overview.legacy, legacy trades/equity) from `state/paper.sqlite` `mode=ro` + `/api/health` + SSE heartbeat; TestClient tests; commit.

### Phase C (top-20 universe + market data + scanner)
- [ ] C1 universe.py TDD with recorded CoinGecko fixtures: stablecoin category exclusion, wrapped dedup (e.g. WBTC/WETH/stETH collapse), top-20 selection, retained-on-failure refresh, membership diff log.
- [ ] C2 instrument resolution TDD: ccxt market dicts (fixtures) → eligible iff linear perp with maint-margin + fees + precision; NOT_ELIGIBLE reasons recorded.
- [ ] C3 marketdata.py with TTL cache + staleness; scanner signal generation on closed candles only; signals + rejections persisted. Live smoke `propaper universe && propaper scan-once`.

### Phase D (hype radar, watch-only)
- [ ] D1 hype module: trending/new-pool ingestion (CoinGecko trending + GeckoTerminal new pools public), scoring with evidence list, hard WATCH_ONLY status without verified perp market; $100 sleeve ledger reserved; API + UI wiring.

### Phase E (perp simulator + risk governor + gated automation)
- [ ] E1 perp.py TDD: isolated-margin entry (fees, slippage), liquidation estimate `liq = entry*(1 - 1/L + mmr)` long / `entry*(1 + 1/L - mmr)` short (approximation, documented), gap-through-stop fills at observed price, liquidation-beats-stop when both gapped, margin-bounded loss.
- [ ] E2 funding application idempotency across restarts (funding_events keyed by position+funding_ts).
- [ ] E3 risk.py TDD: 0.5% sizing incl. fees/slippage, 3-slot cap, 1.5% combined planned risk, sticky daily 2% / total 5% locks, sleeve isolation, margin availability, dup-entry prevention.
- [ ] E4 engine loop: scan → approve → simulate; auto-entry refuses without `state/validation_report.json`; pause status prominent in /api/overview.
- [ ] E5 validation.py: per-market + combined walk-forward with perp costs on real downloaded candles; writes the report artifact with honest warnings.

### Phase F (integration, security, E2E)
- [ ] F1 Full pytest suite (existing 40 preserved + new), `npm run build`, API+web boot smoke, security grep (no credentials/order calls), README-Pro run instructions, built-vs-pending report.

Each task: failing test → implement → full suite → commit (TDD per superpowers:test-driven-development).
