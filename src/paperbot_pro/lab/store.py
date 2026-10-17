"""Extreme Lab persistence: its own SQLite file, fully isolated from the
main portfolio's database. Simulation state only — no credentials."""
from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path
from .config import STRATEGIES, LabSettings

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS strategies (
    key TEXT PRIMARY KEY, name TEXT NOT NULL,
    allocation_usd REAL NOT NULL, cash_usd REAL NOT NULL,
    realized_pnl_usd REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, strategy TEXT NOT NULL,
    symbol TEXT NOT NULL UNIQUE, side TEXT NOT NULL CHECK(side IN ('long','short')),
    leverage REAL NOT NULL, qty REAL NOT NULL, entry_price REAL NOT NULL,
    margin_usd REAL NOT NULL, notional_usd REAL NOT NULL,
    stop REAL NOT NULL, initial_stop REAL NOT NULL,
    target REAL,                             -- NULL: no fixed take-profit cap
    liq_price_est REAL NOT NULL, entry_fee_usd REAL NOT NULL,
    funding_paid_usd REAL NOT NULL DEFAULT 0,
    planned_risk_usd REAL NOT NULL, mfe_price REAL, mae_price REAL,
    opened_ms INTEGER NOT NULL, signal_bar_ms INTEGER NOT NULL,
    rationale TEXT NOT NULL, indicator_snapshot TEXT,
    exchange TEXT NOT NULL, taker_fee REAL NOT NULL);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, strategy TEXT NOT NULL,
    symbol TEXT NOT NULL, side TEXT NOT NULL, leverage REAL NOT NULL,
    qty REAL NOT NULL, entry_price REAL NOT NULL, exit_price REAL NOT NULL,
    stop_initial REAL NOT NULL, stop_final REAL NOT NULL, target REAL,
    margin_usd REAL NOT NULL, notional_usd REAL NOT NULL,
    entry_fee_usd REAL NOT NULL, exit_fee_usd REAL NOT NULL,
    funding_usd REAL NOT NULL, net_pnl_usd REAL NOT NULL,
    mfe_pct REAL, mae_pct REAL, entry_ms INTEGER NOT NULL, exit_ms INTEGER NOT NULL,
    exit_reason TEXT NOT NULL, rationale TEXT NOT NULL, indicator_snapshot TEXT);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER NOT NULL,
    strategy TEXT NOT NULL, symbol TEXT NOT NULL, action TEXT NOT NULL,
    approved INTEGER NOT NULL, reject_reason TEXT, details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS funding_events (
    position_id INTEGER NOT NULL, funding_ts_ms INTEGER NOT NULL,
    rate REAL NOT NULL, amount_usd REAL NOT NULL,
    PRIMARY KEY (position_id, funding_ts_ms));
CREATE TABLE IF NOT EXISTS equity_history (
    ts_ms INTEGER PRIMARY KEY, equity_usd REAL NOT NULL, cash_usd REAL NOT NULL,
    margin_used_usd REAL NOT NULL, unrealized_usd REAL NOT NULL,
    peak_equity_usd REAL NOT NULL, threshold_usd REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER NOT NULL,
    level TEXT NOT NULL, category TEXT NOT NULL, message TEXT NOT NULL);
-- DB-level settlement idempotency: one row per settled position id. A second
-- settlement attempt (any connection/process) hits the PK and is rejected.
CREATE TABLE IF NOT EXISTS settlements (
    position_id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, settled_ms INTEGER NOT NULL,
    exit_reason TEXT NOT NULL);
"""


class LabStore:
    def __init__(self, path: str, cfg: LabSettings):
        cfg.validate()
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=15000")
        self.conn.executescript(SCHEMA)
        if self.get("initialized") is None:
            with self.conn:
                for s in STRATEGIES:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO strategies VALUES(?,?,?,?,0)",
                        (s.key, s.name, cfg.allocation_per_strategy_usd,
                         cfg.allocation_per_strategy_usd))
            self.set("initialized", True)
            self.set("initial_capital", cfg.starting_capital_usd)
            self.set("peak_equity", cfg.starting_capital_usd)
            self.set("lab_locked", False)
            self.set("lab_lock_reason", None)

    # -- kv ------------------------------------------------------------
    def get(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row[0])

    def set(self, key: str, value):
        with self.conn:
            self.conn.execute(
                "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)))

    # -- ledgers --------------------------------------------------------
    def strategy_ledger(self) -> dict[str, dict]:
        return {r["key"]: dict(r) for r in self.conn.execute("SELECT * FROM strategies")}

    def total_cash(self) -> float:
        return float(self.conn.execute(
            "SELECT COALESCE(SUM(cash_usd), 0) FROM strategies").fetchone()[0])

    def open_positions(self) -> list[dict]:
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM positions ORDER BY id")]
        for row in rows:
            if row.get("indicator_snapshot"):
                row["indicator_snapshot"] = json.loads(row["indicator_snapshot"])
        return rows

    def position(self, symbol: str):
        row = self.conn.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
        return dict(row) if row else None

    def trades(self, limit: int = 1000, strategy: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM trades", []
        if strategy:
            q += " WHERE strategy=?"
            args.append(strategy)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = [dict(r) for r in self.conn.execute(q, args)]
        for row in rows:
            if row.get("indicator_snapshot"):
                row["indicator_snapshot"] = json.loads(row["indicator_snapshot"])
        return rows

    # -- logs ----------------------------------------------------------
    def audit(self, level: str, category: str, message: str, ts_ms: int | None = None):
        with self.conn:
            self.conn.execute(
                "INSERT INTO audit_log(ts_ms, level, category, message) VALUES(?,?,?,?)",
                (ts_ms if ts_ms is not None else int(time.time() * 1000),
                 level, category, message))

    def audit_log(self, limit: int = 200):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]

    def log_signal(self, ts_ms: int, strategy: str, symbol: str, action: str,
                   approved: bool, reject_reason: str | None, details: str):
        with self.conn:
            self.conn.execute(
                "INSERT INTO signals(ts_ms, strategy, symbol, action, approved, reject_reason, details) "
                "VALUES(?,?,?,?,?,?,?)",
                (ts_ms, strategy, symbol, action, int(approved), reject_reason, details))

    def signals(self, limit: int = 200):
        rows = [dict(r) for r in self.conn.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,))]
        for row in rows:
            row["approved"] = bool(row["approved"])
        return rows

    def record_equity(self, ts_ms: int, equity: float, cash: float, margin: float,
                      unrealized: float, peak: float, threshold: float):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO equity_history VALUES(?,?,?,?,?,?,?)",
                              (ts_ms, equity, cash, margin, unrealized, peak, threshold))

    def equity_history(self, limit: int = 100_000):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM (SELECT * FROM equity_history ORDER BY ts_ms DESC LIMIT ?) ORDER BY ts_ms",
            (limit,))]

    def close(self):
        self.conn.close()
