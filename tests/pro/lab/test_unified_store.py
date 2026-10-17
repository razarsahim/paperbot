"""Unified store: research-cohort columns + cohort-aware strategy status,
with a migration-safe idempotent ALTER so an existing 5-sleeve DB (which
lacks these columns) gains them on first write-open without data loss."""
import sqlite3
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.store import LabStore


def make(tmp_path, **kw):
    cfg = replace(LabSettings(), db_path=str(tmp_path / "lab.sqlite"), **kw)
    return LabStore(cfg.db_path, cfg), cfg


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_fresh_store_has_research_cohort_columns(tmp_path):
    store, _ = make(tmp_path)
    assert {"locked", "lock_reason"} <= _cols(store.conn, "strategies")
    assert "corr_cluster" in _cols(store.conn, "positions")


def test_strategy_status_extreme_cohort_has_no_floor(tmp_path):
    store, _ = make(tmp_path)
    # extreme sleeve drained well below $30: still 'ok' — no per-strategy floor
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=5 WHERE key='breakout'")
    assert store.strategy_status("breakout")["level"] == "ok"


def test_strategy_status_research_cohort_warns_and_locks_by_floor(tmp_path):
    store, _ = make(tmp_path)
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=45 WHERE key='regime_trend'")
    assert store.strategy_status("regime_trend")["level"] == "ok"
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=38 WHERE key='regime_trend'")
    assert store.strategy_status("regime_trend")["level"] == "warning"
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=29 WHERE key='regime_trend'")
    st = store.strategy_status("regime_trend")
    assert st["level"] == "locked"
    assert st["remaining_allowance_usd"] == pytest.approx(0.0)


def test_locked_flag_forces_locked_regardless_of_cash(tmp_path):
    store, _ = make(tmp_path)
    with store.conn:
        store.conn.execute("UPDATE strategies SET locked=1, lock_reason='x' WHERE key='trend_pullback'")
    assert store.strategy_status("trend_pullback")["level"] == "locked"


def test_migration_safe_alter_on_old_schema_db(tmp_path):
    """An existing DB whose strategies/positions predate the research columns
    must gain them on open, preserving existing rows."""
    path = str(tmp_path / "old.sqlite")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE strategies (key TEXT PRIMARY KEY, name TEXT NOT NULL,
            allocation_usd REAL NOT NULL, cash_usd REAL NOT NULL,
            realized_pnl_usd REAL NOT NULL DEFAULT 0);
        CREATE TABLE positions (id INTEGER PRIMARY KEY AUTOINCREMENT, strategy TEXT,
            symbol TEXT UNIQUE, side TEXT, leverage REAL, qty REAL, entry_price REAL,
            margin_usd REAL, notional_usd REAL, stop REAL, initial_stop REAL, target REAL,
            liq_price_est REAL, entry_fee_usd REAL, funding_paid_usd REAL DEFAULT 0,
            planned_risk_usd REAL, mfe_price REAL, mae_price REAL, opened_ms INTEGER,
            signal_bar_ms INTEGER, rationale TEXT, indicator_snapshot TEXT, exchange TEXT,
            taker_fee REAL);
    """)
    conn.execute("INSERT INTO strategies VALUES('trend','Trend Rider',50,29.17,2.82)")
    conn.execute("INSERT INTO kv VALUES('initialized','true')")
    conn.commit()
    conn.close()

    cfg = replace(LabSettings(), db_path=path)
    store = LabStore(path, cfg)
    assert {"locked", "lock_reason"} <= _cols(store.conn, "strategies")
    assert "corr_cluster" in _cols(store.conn, "positions")
    row = store.strategy_ledger()["trend"]
    assert row["cash_usd"] == pytest.approx(29.17)   # preserved
    assert row["realized_pnl_usd"] == pytest.approx(2.82)
    assert row["locked"] == 0                          # new column defaulted
