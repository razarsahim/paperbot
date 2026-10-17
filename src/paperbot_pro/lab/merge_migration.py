"""Atomic, idempotent consolidation of the Research Lab into the Extreme Lab.

The Research Lab's five strategies become a second cohort inside the single
$500 Extreme Lab. This moves the research sleeves' ledgers, journals and any
open positions into the Extreme DB; it never invents capital and never treats
the transferred capital as trading profit.

HWM rebase (mathematically justified): for the whole period the two labs ran,
the combined equity at time t equals extreme_equity(t) + research_equity(t).
Research equity is a constant through its history (it is read once at the
moment of consolidation), so the combined curve is the Extreme curve shifted by
that constant: the peak and threshold shift by the same amount and the $50
trailing distance is preserved exactly.

PAPER ONLY. One transaction; either the whole merge lands or none of it does.
"""
from __future__ import annotations
import os
import shutil
import sqlite3
import tempfile
import time

from ..perp import unrealized_pnl

_MERGED_FLAG = "research_merged"


def plan_merge(extreme_db_path: str, research_db_path: str) -> dict:
    """Dry-run the merge on throwaway COPIES of both DBs and return a
    before/after reconciliation. Mutates nothing live. Used by
    `propaper merge-labs` (no --apply) to preview the exact consolidation."""
    from dataclasses import replace
    from .config import LabSettings
    from .store import LabStore
    from ..reconcile import reconcile_lab

    tmp = tempfile.mkdtemp(prefix="merge_dryrun_")
    try:
        ex_copy = os.path.join(tmp, "extreme.sqlite")
        re_copy = os.path.join(tmp, "research.sqlite")
        # WAL-consistent copies via the backup API — NOT shutil.copy, which
        # would grab a stale main-file snapshot and miss committed WAL frames.
        for src, dst in ((extreme_db_path, ex_copy), (research_db_path, re_copy)):
            s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
            d = sqlite3.connect(dst)
            with d:
                s.backup(d)
            s.close()
            d.close()
        cfg = replace(LabSettings(), db_path=ex_copy)
        lab = LabStore(ex_copy, cfg)
        led0 = lab.strategy_ledger()
        before = {"strategies": len(led0), "total_cash": lab.total_cash(),
                  "realized": sum(s["realized_pnl_usd"] for s in led0.values()),
                  "peak_equity": lab.get("peak_equity"),
                  "positions": [p["symbol"] for p in lab.open_positions()]}
        report = merge_research_into_lab(lab, re_copy)
        rec = reconcile_lab(lab, cfg)
        led1 = lab.strategy_ledger()
        after = {"strategies": len(led1), "total_cash": lab.total_cash(),
                 "realized": sum(s["realized_pnl_usd"] for s in led1.values()),
                 "peak_equity": lab.get("peak_equity"),
                 "threshold": lab.get("peak_equity") - 50.0,
                 "positions": [p["symbol"] for p in lab.open_positions()],
                 "reconciles": rec["ok"],
                 "discrepancies": rec["discrepancies"]}
        lab.close()
        return {"dry_run": True, "before": before, "after": after, "report": report}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _research_snapshot(path: str) -> dict:
    """Read everything we need from the Research DB, read-only."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        strategies = [dict(r) for r in conn.execute("SELECT * FROM strategies ORDER BY key")]
        positions = [dict(r) for r in conn.execute("SELECT * FROM positions ORDER BY id")]
        trades = [dict(r) for r in conn.execute("SELECT * FROM trades ORDER BY id")]
        signals = [dict(r) for r in conn.execute("SELECT * FROM signals ORDER BY id")]
        marks = {}
        row = conn.execute("SELECT value FROM kv WHERE key='marks'").fetchone()
        if row:
            import json
            marks = json.loads(row[0])
        total_cash = float(conn.execute(
            "SELECT COALESCE(SUM(cash_usd),0) FROM strategies").fetchone()[0])
        # research equity at consolidation = cash + open margin + open uPnL
        equity = total_cash
        for p in positions:
            equity += p["margin_usd"]
            m = marks.get(p["symbol"])
            if m is not None:
                equity += unrealized_pnl(p["side"], p["entry_price"], m, p["qty"])
        return {"strategies": strategies, "positions": positions, "trades": trades,
                "signals": signals, "total_cash": total_cash, "equity": equity}
    finally:
        conn.close()


def merge_research_into_lab(lab_store, research_db_path: str,
                            now_ms: int | None = None) -> dict:
    """Merge the Research Lab at `research_db_path` into `lab_store` (an open
    Extreme LabStore). Idempotent: a second call is a no-op. Returns a
    reconciliation report."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    db = lab_store.conn

    if lab_store.get(_MERGED_FLAG):
        led = lab_store.strategy_ledger()
        return {"already_merged": True,
                "strategies": len(led),
                "realized_pnl_after": sum(s["realized_pnl_usd"] for s in led.values()),
                "peak_equity": lab_store.get("peak_equity")}

    snap = _research_snapshot(research_db_path)
    research_equity = snap["equity"]
    old_peak = float(lab_store.get("peak_equity"))
    new_peak = old_peak + research_equity

    with db:  # single atomic transaction
        # 1. research sleeves -> strategies (preserve real balances/locks)
        for s in snap["strategies"]:
            db.execute(
                "INSERT OR IGNORE INTO strategies(key,name,allocation_usd,cash_usd,"
                "realized_pnl_usd,locked,lock_reason) VALUES(?,?,?,?,?,?,?)",
                (s["key"], s["name"], s["allocation_usd"], s["cash_usd"],
                 s["realized_pnl_usd"], s.get("locked", 0) or 0, s.get("lock_reason")))

        # 2. research open positions -> positions (preserve stop/margin/funding/cluster)
        for p in snap["positions"]:
            db.execute(
                "INSERT OR IGNORE INTO positions(strategy,symbol,side,leverage,qty,entry_price,"
                "margin_usd,notional_usd,stop,initial_stop,target,liq_price_est,entry_fee_usd,"
                "funding_paid_usd,planned_risk_usd,mfe_price,mae_price,opened_ms,signal_bar_ms,"
                "rationale,indicator_snapshot,exchange,taker_fee,corr_cluster) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p["strategy"], p["symbol"], p["side"], p["leverage"], p["qty"], p["entry_price"],
                 p["margin_usd"], p["notional_usd"], p["stop"], p["initial_stop"], p["target"],
                 p["liq_price_est"], p["entry_fee_usd"], p.get("funding_paid_usd", 0) or 0,
                 p["planned_risk_usd"], p.get("mfe_price"), p.get("mae_price"), p["opened_ms"],
                 p["signal_bar_ms"], p["rationale"], p.get("indicator_snapshot"), p["exchange"],
                 p["taker_fee"], p.get("corr_cluster", "") or ""))

        # 3. research trade journal -> trades (historical performance preserved)
        for t in snap["trades"]:
            db.execute(
                "INSERT INTO trades(strategy,symbol,side,leverage,qty,entry_price,exit_price,"
                "stop_initial,stop_final,target,margin_usd,notional_usd,entry_fee_usd,exit_fee_usd,"
                "funding_usd,net_pnl_usd,mfe_pct,mae_pct,entry_ms,exit_ms,exit_reason,rationale,"
                "indicator_snapshot) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (t["strategy"], t["symbol"], t["side"], t["leverage"], t["qty"], t["entry_price"],
                 t["exit_price"], t["stop_initial"], t["stop_final"], t["target"], t["margin_usd"],
                 t["notional_usd"], t["entry_fee_usd"], t["exit_fee_usd"], t["funding_usd"],
                 t["net_pnl_usd"], t.get("mfe_pct"), t.get("mae_pct"), t["entry_ms"], t["exit_ms"],
                 t["exit_reason"], t["rationale"], t.get("indicator_snapshot")))

        # 4. research signal journal -> signals
        for s in snap["signals"]:
            db.execute(
                "INSERT INTO signals(ts_ms,strategy,symbol,action,approved,reject_reason,details) "
                "VALUES(?,?,?,?,?,?,?)",
                (s["ts_ms"], s["strategy"], s["symbol"], s["action"], s["approved"],
                 s.get("reject_reason"), s["details"]))

        # 5. rebase the historical equity curve by +research_equity so the
        #    combined curve is continuous (research was a constant +equity).
        db.execute(
            "UPDATE equity_history SET equity_usd = equity_usd + ?, cash_usd = cash_usd + ?, "
            "peak_equity_usd = peak_equity_usd + ?, threshold_usd = threshold_usd + ?",
            (research_equity, research_equity, research_equity, research_equity))

        # 6. ratchet the live HWM by the same constant; preserve the old value
        import json
        db.execute("INSERT INTO kv(key,value) VALUES('peak_equity',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(new_peak),))
        db.execute("INSERT INTO kv(key,value) VALUES('peak_equity_pre_merge',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(old_peak),))
        db.execute("INSERT INTO kv(key,value) VALUES(?,?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (_MERGED_FLAG, json.dumps(True)))
        db.execute("INSERT INTO kv(key,value) VALUES('research_merged_at_ms',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(now_ms),))

        # 7. audit trail (capital transfer, explicitly NOT profit)
        db.execute(
            "INSERT INTO audit_log(ts_ms,level,category,message) VALUES(?,?,?,?)",
            (now_ms, "warning", "accounting",
             f"RESEARCH LAB MERGED into Extreme Lab: {len(snap['strategies'])} sleeves, "
             f"${research_equity:.2f} capital TRANSFERRED (not profit). HWM {old_peak:.4f} "
             f"-> {new_peak:.4f}; threshold {old_peak - 50:.4f} -> {new_peak - 50:.4f}. "
             f"Trailing distance $50 preserved. Equity history rebased +{research_equity:.2f}."))

    led = lab_store.strategy_ledger()
    return {"already_merged": False,
            "strategies": len(led),
            "capital_transferred_usd": research_equity,
            "realized_pnl_after": sum(s["realized_pnl_usd"] for s in led.values()),
            "peak_equity_before": old_peak,
            "peak_equity": new_peak,
            "threshold": new_peak - 50.0,
            "total_cash_after": lab_store.total_cash()}
