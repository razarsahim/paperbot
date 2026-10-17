"""Read-only financial reconciliation for the Extreme Lab and Research Lab.

The authoritative ledger identity (from the open/close/funding code):

    cash_usd == allocation
              + Σ(closed-trade net_pnl)                   # each already nets fees+funding
              − Σ(open: margin + entry_fee + funding_paid) # reserved, not in free cash

    strategy equity == cash_usd + Σ(open margin) + Σ(open unrealized)

This module reads the DB and reports discrepancies; it never mutates state.
Both labs share the same schema, so one function serves both.
"""
from __future__ import annotations

EPS = 1e-6
FUNDING_INTERVAL_MS = 8 * 3_600_000


def _reconcile(store, strategy_keys, allocation: float, trailing_dd: float,
               starting_capital: float) -> dict:
    discrepancies = []
    ledger = store.strategy_ledger()
    positions = store.open_positions()
    by_strategy_open: dict[str, list] = {}
    for p in positions:
        by_strategy_open.setdefault(p["strategy"], []).append(p)

    # ---- per-strategy cash identity ----
    for key in strategy_keys:
        led = ledger.get(key)
        if led is None:
            discrepancies.append({"strategy": key, "kind": "missing_ledger",
                                  "detail": f"strategy '{key}' has no ledger row",
                                  "impact_usd": None, "recommended_correction": None})
            continue
        closed_pnl = sum(t["net_pnl_usd"] for t in store.trades(limit=10**9, strategy=key))
        reserved = sum(p["margin_usd"] + p["entry_fee_usd"] + p["funding_paid_usd"]
                       for p in by_strategy_open.get(key, []))
        expected_cash = led["allocation_usd"] + closed_pnl - reserved
        diff = led["cash_usd"] - expected_cash
        if abs(diff) > 1e-4:
            discrepancies.append({
                "strategy": key, "kind": "cash_identity",
                "detail": (f"cash {led['cash_usd']:.4f} != allocation {led['allocation_usd']:.2f} "
                           f"+ realized {closed_pnl:.4f} - reserved {reserved:.4f}"),
                "expected": expected_cash, "actual": led["cash_usd"],
                "impact_usd": abs(diff),
                "recommended_correction": {"table": "strategies", "key": key,
                                           "cash_usd": round(expected_cash, 8)},
            })

    # ---- duplicate settlement detection (same symbol+entry_ms+qty+entry_price) ----
    seen: dict[tuple, list] = {}
    for t in store.trades(limit=10**9):
        sig = (t["symbol"], t["entry_ms"], round(t["qty"], 10), round(t["entry_price"], 8))
        seen.setdefault(sig, []).append(t["id"])
    for sig, ids in seen.items():
        if len(ids) > 1:
            discrepancies.append({
                "strategy": None, "kind": "duplicate_settlement",
                "detail": (f"{sig[0]} entry_ms={sig[1]} qty={sig[2]} appears in "
                           f"{len(ids)} trades (ids {ids}) — possible double-close"),
                "impact_usd": None,
                "recommended_correction": {"action": "review trades", "trade_ids": ids[1:]},
            })

    # ---- funding reconciliation: position.funding_paid vs funding_events ----
    for p in positions:
        row = store.conn.execute(
            "SELECT COALESCE(SUM(amount_usd),0) FROM funding_events WHERE position_id=?",
            (p["id"],)).fetchone()
        events_sum = float(row[0])
        if abs(p["funding_paid_usd"] - events_sum) > 1e-4:
            discrepancies.append({
                "strategy": p["strategy"], "kind": "funding_mismatch",
                "detail": (f"{p['symbol']} position funding_paid {p['funding_paid_usd']:.4f} != "
                           f"sum(funding_events) {events_sum:.4f}"),
                "impact_usd": abs(p["funding_paid_usd"] - events_sum),
                "recommended_correction": {"table": "positions", "id": p["id"],
                                           "funding_paid_usd": round(events_sum, 8)},
            })

    # ---- open-position sanity: margin>0, stop set, qty>0 ----
    for p in positions:
        if p["margin_usd"] <= 0 or p["qty"] <= 0 or p["stop"] <= 0:
            discrepancies.append({
                "strategy": p["strategy"], "kind": "invalid_open_position",
                "detail": f"{p['symbol']} has non-positive margin/qty/stop",
                "impact_usd": None, "recommended_correction": {"action": "manual review"}})

    # ---- portfolio-level ----
    marks = store.get("marks", {}) or {}
    from .perp import unrealized_pnl
    total_cash = store.total_cash()
    margin_used = sum(p["margin_usd"] for p in positions)
    unreal = 0.0
    for p in positions:
        m = marks.get(p["symbol"])
        if m is not None:
            unreal += unrealized_pnl(p["side"], p["entry_price"], m, p["qty"])
    equity = total_cash + margin_used + unreal
    peak = float(store.get("peak_equity", starting_capital))
    notes = []
    # HWM invariant: peak must be >= the max equity ever RECORDED (it ratchets
    # per cycle). Current live equity can exceed peak transiently between
    # cycles — that's expected, not a defect, so it is a note, not a breach.
    history = store.equity_history(10**9)
    hist_max = max((r["equity_usd"] for r in history), default=starting_capital)
    if peak < hist_max - 1e-4:
        discrepancies.append({
            "strategy": None, "kind": "hwm_not_ratcheted",
            "detail": f"peak_equity {peak:.4f} < max recorded equity {hist_max:.4f}",
            "impact_usd": hist_max - peak,
            "recommended_correction": {"table": "kv", "key": "peak_equity",
                                       "value": round(hist_max, 8)}})
    if peak < starting_capital - 1e-4:
        discrepancies.append({
            "strategy": None, "kind": "peak_below_initial",
            "detail": f"peak_equity {peak:.4f} < starting capital {starting_capital:.2f}",
            "impact_usd": starting_capital - peak, "recommended_correction": None})
    if peak < equity - 1e-4:
        notes.append(f"current equity {equity:.2f} exceeds peak {peak:.2f} "
                     "(HWM will ratchet next cycle; not a discrepancy)")

    return {
        "ok": len(discrepancies) == 0,
        "discrepancies": discrepancies,
        "notes": notes,
        "portfolio": {
            "cash_usd": total_cash, "margin_used_usd": margin_used,
            "unrealized_usd": unreal, "equity_usd": equity,
            "peak_equity_usd": peak, "threshold_usd": peak - trailing_dd,
            "open_positions": len(positions),
        },
    }


def reconcile_lab(store, cfg) -> dict:
    from .lab.config import STRATEGIES
    return _reconcile(store, [s.key for s in STRATEGIES],
                      cfg.allocation_per_strategy_usd, cfg.trailing_drawdown_usd,
                      cfg.starting_capital_usd)


def reconcile_research(store, cfg) -> dict:
    from .research.config import STRATEGIES
    return _reconcile(store, [s.key for s in STRATEGIES],
                      cfg.allocation_per_strategy_usd, cfg.trailing_drawdown_usd,
                      cfg.starting_capital_usd)
