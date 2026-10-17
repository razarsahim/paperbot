"""Fresh-start reset for the Extreme Lab.

Archives the current Extreme Lab (and the frozen Research archive) to a
verified, WAL-consistent snapshot plus a manifest, then reinitialises a clean
$500 / 10-sleeve forward-paper experiment IN PLACE. In-place (truncate + reseed
in one transaction) rather than deleting the file, so the schema and the
settlement / idempotency protections survive and no connection races on a
deleted inode.

It never invents closing trades or fills for old open positions — those live on
only in the archive. New entries are left PAUSED so the operator explicitly
enables the fresh experiment after verification.

PAPER ONLY. Mutates only the Extreme Lab DB; never the main or legacy engines.
"""
from __future__ import annotations
import json
import os
import shutil
import sqlite3
import tempfile

from .config import STRATEGIES

# every data table is cleared on reset; the schema (incl. settlements) stays
_DATA_TABLES = ("positions", "trades", "settlements", "funding_events",
                "signals", "equity_history", "audit_log")


def _summarize(conn) -> dict:
    conn.row_factory = sqlite3.Row
    led = [dict(r) for r in conn.execute("SELECT * FROM strategies")]
    peak_row = conn.execute("SELECT value FROM kv WHERE key='peak_equity'").fetchone()
    return {
        "strategies": len(led),
        "total_cash": sum(s["cash_usd"] for s in led),
        "total_allocation": sum(s["allocation_usd"] for s in led),
        "total_realized_pnl": sum(s["realized_pnl_usd"] for s in led),
        "peak_equity": json.loads(peak_row[0]) if peak_row else None,
        "open_positions": conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0],
        "position_symbols": [r[0] for r in conn.execute("SELECT symbol FROM positions")],
        "completed_trades": conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0],
        "settlements": conn.execute("SELECT COUNT(*) FROM settlements").fetchone()[0],
        "equity_history_rows": conn.execute("SELECT COUNT(*) FROM equity_history").fetchone()[0],
        "audit_rows": conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
    }


def _backup_verified(src_path: str, dst_path: str) -> dict:
    """WAL-consistent copy via the backup API, then integrity + fk verification."""
    s = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    d = sqlite3.connect(dst_path)
    with d:
        s.backup(d)
    s.close()
    d.close()
    v = sqlite3.connect(f"file:{dst_path}?mode=ro", uri=True)
    try:
        integrity = v.execute("PRAGMA integrity_check").fetchone()[0]
        fk = len(v.execute("PRAGMA foreign_key_check").fetchall())
    finally:
        v.close()
    return {"path": dst_path, "bytes": os.path.getsize(dst_path),
            "integrity_check": integrity, "fk_violations": fk}


def _fresh_target(cfg_starting: float, cfg_alloc: float, trailing_dd: float) -> dict:
    return {
        "total_cash": cfg_starting, "total_allocation": cfg_starting,
        "strategies": len(STRATEGIES), "allocation_per_strategy": cfg_alloc,
        "peak_equity": cfg_starting, "threshold": cfg_starting - trailing_dd,
        "open_positions": 0, "completed_trades": 0, "realized_pnl": 0.0,
        "entries_paused": True,
    }


def reset_lab(lab_store, research_db_path: str, archive_dir: str,
              now_ms: int | None = None) -> dict:
    """Archive the current lab + research DBs to `archive_dir` (verified), write a
    manifest, then reinitialise `lab_store` to a clean $500 / 10-sleeve state in
    one transaction. Returns a report. The caller must have STOPPED the lab
    engine first (no competing writer)."""
    import time
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    cfg = lab_store.cfg
    os.makedirs(archive_dir, exist_ok=True)

    # --- 1. archive both DBs (WAL-consistent) and verify ---
    lab_db_path = cfg.db_path
    lab_backup = _backup_verified(lab_db_path, os.path.join(archive_dir, "extreme_lab.sqlite"))
    research_backup = None
    if research_db_path and os.path.exists(research_db_path):
        research_backup = _backup_verified(
            research_db_path, os.path.join(archive_dir, "research_lab.sqlite"))

    # --- 2. summarise the archived (old) state for the manifest ---
    arc = sqlite3.connect(f"file:{lab_backup['path']}?mode=ro", uri=True)
    old = _summarize(arc)
    arc.close()

    fresh = _fresh_target(cfg.starting_capital_usd, cfg.allocation_per_strategy_usd,
                          cfg.trailing_drawdown_usd)
    manifest = {"archived_at_ms": now_ms, "reason": "fresh-start forward-paper reset",
                "lab": old, "lab_backup": lab_backup, "research_backup": research_backup,
                "fresh": fresh, "paper_only": True}
    with open(os.path.join(archive_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # --- 3. reinitialise the live DB in place (one transaction) ---
    db = lab_store.conn
    with db:
        for table in _DATA_TABLES:
            db.execute(f"DELETE FROM {table}")
        db.execute("DELETE FROM strategies")
        db.execute("DELETE FROM kv")
        for s in STRATEGIES:
            db.execute(
                "INSERT INTO strategies(key,name,allocation_usd,cash_usd,realized_pnl_usd,locked) "
                "VALUES(?,?,?,?,0,0)",
                (s.key, s.name, cfg.allocation_per_strategy_usd, cfg.allocation_per_strategy_usd))
        for key, value in (("initialized", True),
                           ("initial_capital", cfg.starting_capital_usd),
                           ("peak_equity", cfg.starting_capital_usd),
                           ("lab_locked", False), ("lab_lock_reason", None),
                           ("lab_manual_pause", True),      # entries paused until explicit enable
                           ("breach_streak", 0)):
            db.execute("INSERT INTO kv(key,value) VALUES(?,?)", (key, json.dumps(value)))
        db.execute(
            "INSERT INTO audit_log(ts_ms,level,category,message) VALUES(?,?,?,?)",
            (now_ms, "warning", "accounting",
             f"FRESH START RESET: previous experiment archived to '{archive_dir}' "
             f"(peak {old['peak_equity']}, cash {old['total_cash']:.2f}, "
             f"{old['open_positions']} open position(s), {old['completed_trades']} trade(s)). "
             f"New clean portfolio: ${cfg.starting_capital_usd:.0f} across {len(STRATEGIES)} "
             f"sleeves, peak ${cfg.starting_capital_usd:.0f}, threshold "
             f"${cfg.starting_capital_usd - cfg.trailing_drawdown_usd:.0f}. Entries PAUSED. "
             "No closing trades invented for archived positions. PAPER ONLY."))

    return {"archived": True, "archive_dir": archive_dir, "manifest": manifest,
            "old": old, "fresh": fresh,
            "lab_backup": lab_backup, "research_backup": research_backup}


def plan_reset(lab_db_path: str, research_db_path: str) -> dict:
    """Dry-run: report the current state that WOULD be archived and the fresh
    target, operating on a throwaway copy. Mutates nothing live."""
    from dataclasses import replace
    from .config import LabSettings
    from .store import LabStore

    tmp = tempfile.mkdtemp(prefix="reset_dryrun_")
    try:
        copy = os.path.join(tmp, "extreme.sqlite")
        s = sqlite3.connect(f"file:{lab_db_path}?mode=ro", uri=True)
        d = sqlite3.connect(copy)
        with d:
            s.backup(d)
        s.close()
        d.close()
        conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        current = _summarize(conn)
        conn.close()
        cfg = LabSettings()
        fresh = _fresh_target(cfg.starting_capital_usd, cfg.allocation_per_strategy_usd,
                              cfg.trailing_drawdown_usd)
        return {"dry_run": True, "current": current, "fresh": fresh,
                "research_present": bool(research_db_path and os.path.exists(research_db_path))}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
