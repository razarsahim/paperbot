# Consolidation Plan — Merge all 10 strategies into one Extreme Lab

**Branch:** `merge-ten-strategies` (off `financial-audit`)
**Backups:** `backups/2026-10-17-premerge/` — all 4 DBs, WAL-consistent, `integrity_check=ok`, `fk_violations=0`
**Status:** AWAITING APPROVAL. No running DB mutated, no engine restarted, no balance altered.
**Hard constraint:** PAPER ONLY. No real orders, credentials, or funds — ever.

## 1. Inspection findings

| | Extreme Lab | Research Lab |
|---|---|---|
| DB | `state/extreme_lab.sqlite` | `state/research_lab.sqlite` |
| Strategies | 5 (breakout, launch_sniper, squeeze, trend, crash_reversal) | 5 (regime_trend, volatility_breakout, trend_pullback, range_reversion, orderflow_imbalance) |
| Allocation | $250 | $250 |
| Cash | $179.6947 | $250.0000 |
| Realized P&L | +$2.8193 (Trend Rider) | $0.0000 |
| Open positions | BNB short (margin $49.19), XMR long (margin $23.50) | none |
| Completed trades | 4 | 0 |
| Signals journal | 13 | 12 |
| Peak (HWM) | $274.5584 (corrected) | $250.0000 |
| Threshold | $224.5584 | $200.0000 |

**Decisive fact:** Research Lab equity is **flat $250 across all 100 snapshots** (0 trades, 0 positions, 0 realized). It has never deviated from its initial capital.

**Running processes (NOT to be disturbed without approval):** `propaper lab-run` (PID 84160), `propaper research-run` (PID 81967), `propaper api` (PID 81939), `next-server` (PID 70460), legacy `propaper run` (PID 47046).

## 2. Recommended approach: atomic consolidation into the Extreme Lab DB + one unified engine

**Why atomic consolidation, not shared-ledger-with-router:** Because Research is pristine, migrating it carries no trade/position/P&L reconciliation risk — we copy 5 strategy rows ($50/$50/$0 each) + the 12 signals, and retire the research engine/DB (frozen as a backup). A shared-ledger router would keep two live DBs and two write paths permanently — more moving parts, more double-write surface, for no benefit. One DB + one engine + one governor is simpler to keep financially correct and matches the requested "one unified Extreme Lab experience."

## 3. Exact pre/post reconciliation

| Field | Extreme | Research | **Combined (post-merge)** |
|---|---|---|---|
| Allocation | $250.00 | $250.00 | **$500.00** |
| Cash | $179.6947 | $250.0000 | **$429.6947** |
| Realized P&L | +$2.8193 | $0.0000 | **+$2.8193** |
| Open margin | $72.69 | $0.00 | **$72.69** |
| Peak (HWM) | $274.5584 | $250.0000 | **$524.5584** |
| Threshold | $224.5584 | $200.0000 | **$474.5584** |
| Open positions | 2 | 0 | **2** |
| Completed trades | 4 | 0 | **4** |
| Signals | 13 | 12 | **25** |

No capital created: combined allocation $500 = 10 × $50. Combined realized P&L is unchanged at +$2.8193 — the +$250 from Research is **transferred capital, not profit**.

## 4. HWM rebase — mathematically justified (exact, not estimated)

For the entire period Extreme was trading, Research equity was a **constant $250**. Therefore the true combined equity at any past time *t* is exactly:

```
combined_equity(t) = extreme_equity(t) + 250      (research was always +250)
```

A constant +$250 translation of the equity curve means:
- **combined_peak = extreme_peak + 250 = 274.5584 + 250 = $524.5584** (exact, reconstructed — not an estimate)
- The $50 trailing-drawdown **distance is preserved exactly** (a constant shift cannot change a drawdown distance).
- **combined_threshold = 524.5584 − 50 = $474.5584**

Neither-loosen-nor-tighten proof: pre-merge Extreme allowance = equity − threshold = 250.98 − 224.5584 = $26.42. Post-merge = 500.98 − 474.5584 = $26.42. **Identical.** The original corrected HWM ($274.5584) and its pre-correction audit value ($275.7629) are preserved verbatim in the merged DB's kv + audit log.

Historical Extreme `equity_history` snapshots will be rebased +250 so the combined curve is continuous (genuine, since Research truly sat at +250 throughout) — with an audit row marking the consolidation point so the +250 is never read as a trading gain.

## 5. Unified risk model (per-strategy, preserving both cohorts)

The unified engine applies **per-strategy** risk parameters keyed by cohort:

| Parameter | Original 5 (Extreme) | Incoming 5 (Research) |
|---|---|---|
| Allocation | $50 | $50 |
| Max planned per-trade risk | $5 (unchanged) | **$2 (preserved)** |
| Per-strategy warn floor | — (none, as today) | **$40** |
| Per-strategy lock floor | — (none, as today) | **$30 (= $20 cumulative loss)** |
| Negative-validation gate | as today | **preserved** |
| Correlation-cluster tag | — | **preserved** |

**Portfolio-level (shared governor), to confirm (§9 open parameters):**
- Trailing drawdown: **$50** distance from combined HWM $524.5584 (unchanged distance).
- Combined planned-risk ceiling: **keep $15** (NOT scaled up for 10 strategies — conservative).
- Max concurrent positions: **propose 4** (was Extreme 3 / Research 4). This is +1 vs the old Extreme cap — flagged for your confirmation; I can keep it at 3 if you prefer no loosening.
- No borrowing across strategies; no averaging down; no widening stops — enforced as today.
- Existing integrity lock, settlement-idempotency (settlements PK), and reconciliation monitor carry over unchanged and now cover all 10 strategies.

## 6. Dashboard (one unified Extreme Lab page)

- `/lab` renders all 10 strategies; `/api/lab` returns 10. `/research` → redirect to `/lab` (data preserved in-DB, not a separate portfolio).
- Per strategy: equity, cash, allocation, realized/unrealized P&L, net return %, 10× leverage, open positions, win rate, profit factor, trade count, remaining loss allowance, stop/trail rules, and status (active/paused/locked/data-stale).
- Sortable leaderboard (best↔worst). Portfolio equity + drawdown charts, per-strategy charts, fees/funding, entry/exit explanations.
- Real-time WebSocket/SSE P&L preserved. Backtests kept visually separate from forward paper results.

## 7. Profit-taking audit (§7)

**Status: NOT IMPLEMENTED (pending).** Confirmed: both engines open with `with_target=False` and exit the full position in one settlement; there is no partial-exit code path (recorded in `docs/PENDING-FEATURES.md`). The requested policy (close 50% at 2R, trail the rest, no fixed cap) is **not active and will not be silently claimed.** Proposed tested implementation (separate, after this merge): a partial-exit path that halves qty + releases proportional margin + realizes partial P&L exactly once (same settlements-PK idempotency, keyed per partial fill), forbids a second 2R take on the same leg, and extends the reconciliation identity for partially-closed positions. I will not touch running position exits.

## 8. Migration sequence (DESTRUCTIVE steps — gated on your approval)

Test-first throughout. Steps 1–6 are code (dormant, engines untouched). Steps 7–9 mutate the DB / restart; they run only after you approve.

1. Write failing tests for: unified per-strategy risk config, 10-strategy engine dispatch, the +250 HWM rebase function, combined reconciliation, research-strategy locks under the unified engine.
2. Move research strategy logic (strategies, indicators, validation gates, correlation clusters) into the lab engine behind a per-strategy cohort config.
3. Unified governor: per-strategy floors for the incoming 5 + portfolio trailing drawdown + shared concurrency.
4. One-shot migration script (idempotent, single transaction): copy 5 research strategy rows + 12 signals into `extreme_lab.sqlite`; set peak=$524.5584; rebase historical equity_history +250; write consolidation audit rows; preserve BNB/XMR untouched.
5. API: `/api/lab` → 10 strategies + leaderboard; retire `/api/research`.
6. Dashboard rebuild + browser QA.
7. **[approval gate]** Stop engines gracefully (BNB/XMR persist in DB), snapshot, run migration script on a copy first, diff-verify, then on live.
8. Restart the single unified engine; verify recovery of BNB/XMR (stop, funding, margin, monitoring) + all 10 strategies + HWM $524.5584 / threshold $474.5584.
9. Full suite + lint + build + `propaper audit-accounting`; confirm 10 independent strategies, no duplicated capital, locks work, no double-credit, live P&L accurate.

## 9. Open parameters — CONFIRMED by owner (2026-10-17)

1. **Max concurrent positions: 3** (no loosening — keep original Extreme cap).
2. **Combined planned-risk ceiling: $15** (conservative — not scaled for 10 strategies).
3. **`/research` route: redirect to `/lab`** (data preserved in-DB; no separate Research portfolio).
