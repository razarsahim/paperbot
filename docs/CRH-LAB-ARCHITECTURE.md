# Crash Reversal Hunter (CRH) Trading Lab — architecture notes

Inspection date: 2026-10-19. Branch `crh-lab`. PAPER ONLY: no orders, keys or real money anywhere.

## What already existed (reused as-is)

| Piece | Where | Reused for |
|---|---|---|
| CRH signal evaluator (deployed baseline) | `src/paperbot_pro/lab/strategies.py::_crash_reversal` (`CRASH_WINDOW=24`, `CRASH_DROP_PCT=-8`, hammer = close>open and lower wick>body, ATR(14) from `paperbot.strategy.atr`) | Called unchanged by the fast engine at candidate hours. |
| Perp maths (sizing, liquidation estimate, stop/liq sequencing, trailing, funding, realised P&L) | `src/paperbot_pro/perp.py` | Imported unchanged: the fast engine never re-implements any formula. |
| Original minute-by-minute replay (`LabEngine` driven by `replay/runner.py`) | `src/paperbot_pro/replay/` | Kept as the **reference engine**; the fast engine is tested for trade-for-trade equivalence against it. |
| Archived Bybit public data adapters: REST klines/mark/funding/OI (`replay/fetch.py`), L2 ob200 archive sampler (`replay/orderbook.py`) | `src/paperbot_pro/replay/` | Wrapped by the new cache. |
| Prior results (7d, 30d, 24h, 48h, continuous Oct 15–19, top-50 Oct 17–19) | `research/*/` (committed) | Regression fixtures (where the local 1m/book data exists). |
| Dashboard design system, `lightweight-charts`, `StatTile`, tables, selects, chart theme | `web/src/components/` | The `/crh` page builds on them. |
| Live Extreme Lab engine + API (`/api/lab`), where CRH already runs forward-paper as the `crash_reversal` sleeve | `src/paperbot_pro/lab/`, `api.py` | Forward-paper view reads it read-only. Not restarted. |

## What was missing (built here)

- A CRH-only, **event-driven** replay: hourly signal events from a vectorised prescan; minute-resolution stop/liquidation/funding path only while positions are open. Module `src/paperbot_pro/crh/engine.py`.
- A persistent, versioned **historical data cache** (Parquet via pyarrow, already installed; no new DB engine): `src/paperbot_pro/crh/data.py`, directory `cache/` (git-ignored). Seeds itself from the existing `research/*/data` files so nothing is downloaded twice.
- **Point-in-time universe** (top 20/50/100 by CoinGecko market cap at 00:00 UTC, engine exclusions, Bybit perp mapping incl. `1000PEPEUSDT`-style contracts): `src/paperbot_pro/crh/universe.py`.
- Smart L2 loading: order-book day-files are fetched only for symbol-days a position or signal actually needs; an explicitly labelled **approximate** candle-only mode exists for when L2 is unavailable.
- Background job runner + FastAPI endpoints (`src/paperbot_pro/crh/api.py`, served by `propaper crh-api` on 127.0.0.1:8778 so the running dashboard API is not restarted) with progress, cancel, result reuse, comparison and JSON/CSV export.
- `/crh` dashboard page.

## Risk-lock finding (Step 5)

The "$50 sleeve fell below $30" observation is explained by cohort design, not a broken lock: the $30 equity floor applies **only to the research cohort** (`LabGovernor.strategy_equity_breaches` filters on `RESEARCH_KEYS`). Crash Reversal is in the **extreme** cohort, which by design has no per-strategy floor; it is protected only by the $5/$15/3-slot rails and the $50 trailing-drawdown lock. The CRH lab therefore exposes the loss trigger as an explicit, labelled setting (default: none, matching the deployed baseline). A separate, real defect remains in the research-cohort "locked" status (cash vs equity) and is out of scope here.
