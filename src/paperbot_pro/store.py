"""SQLite persistence for PaperBot Pro. Simulation state only — no credentials."""
from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path
from .config import ProSettings

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS universe (
    coingecko_id TEXT PRIMARY KEY, rank INTEGER NOT NULL, symbol TEXT NOT NULL,
    name TEXT NOT NULL, price_usd REAL, change_24h_pct REAL,
    market_cap_usd REAL, volume_24h_usd REAL, updated_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS universe_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
    added TEXT NOT NULL, removed TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS instruments (
    coingecko_id TEXT PRIMARY KEY, exchange TEXT, symbol TEXT,
    eligible INTEGER NOT NULL, reason TEXT, taker_fee REAL,
    maint_margin_rate REAL, tick_size REAL, lot_size REAL, updated_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL UNIQUE,
    side TEXT NOT NULL CHECK(side IN ('long','short')), leverage REAL NOT NULL,
    qty REAL NOT NULL, entry_price REAL NOT NULL, margin_usd REAL NOT NULL,
    notional_usd REAL NOT NULL, stop REAL NOT NULL, initial_stop REAL NOT NULL,
    target REAL NOT NULL, liq_price_est REAL NOT NULL,
    entry_fee_usd REAL NOT NULL, funding_paid_usd REAL NOT NULL DEFAULT 0,
    planned_risk_usd REAL NOT NULL, planned_risk_pct REAL NOT NULL,
    mfe_price REAL, mae_price REAL,
    sleeve TEXT NOT NULL CHECK(sleeve IN ('core','hype')),
    opened_ms INTEGER NOT NULL, signal_bar_ms INTEGER NOT NULL,
    rationale TEXT NOT NULL, indicator_snapshot TEXT);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, side TEXT NOT NULL,
    leverage REAL NOT NULL, qty REAL NOT NULL, entry_price REAL NOT NULL,
    exit_price REAL NOT NULL, stop_initial REAL NOT NULL, stop_final REAL NOT NULL,
    target REAL NOT NULL, margin_usd REAL NOT NULL, notional_usd REAL NOT NULL,
    entry_fee_usd REAL NOT NULL, exit_fee_usd REAL NOT NULL,
    funding_usd REAL NOT NULL, net_pnl_usd REAL NOT NULL,
    mfe_pct REAL, mae_pct REAL, entry_ms INTEGER NOT NULL, exit_ms INTEGER NOT NULL,
    exit_reason TEXT NOT NULL, rationale TEXT NOT NULL,
    indicator_snapshot TEXT, sleeve TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER NOT NULL,
    symbol TEXT NOT NULL, action TEXT NOT NULL, approved INTEGER NOT NULL,
    reject_reason TEXT, details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS funding_events (
    position_id INTEGER NOT NULL, funding_ts_ms INTEGER NOT NULL,
    rate REAL NOT NULL, amount_usd REAL NOT NULL,
    PRIMARY KEY (position_id, funding_ts_ms));
CREATE TABLE IF NOT EXISTS equity_history (
    ts_ms INTEGER PRIMARY KEY, equity_usd REAL NOT NULL, cash_core REAL NOT NULL,
    cash_hype REAL NOT NULL, margin_used_usd REAL NOT NULL, unrealized_usd REAL NOT NULL);
CREATE TABLE IF NOT EXISTS hype_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER NOT NULL,
    symbol TEXT NOT NULL, name TEXT NOT NULL, chain TEXT NOT NULL, contract TEXT,
    pool_age_hours REAL, liquidity_usd REAL, volume_24h_usd REAL,
    score REAL NOT NULL, flags TEXT NOT NULL, evidence TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('WATCH_ONLY','REJECTED','ELIGIBLE')),
    explanation TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER NOT NULL,
    level TEXT NOT NULL, category TEXT NOT NULL, message TEXT NOT NULL);
"""


class ProStore:
    def __init__(self, path: str, cfg: ProSettings):
        cfg.validate()
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the API serves reads from a threadpool;
        # CPython's sqlite3 is built serialized (threadsafety==3) so sharing
        # one connection across threads is safe.
        self.conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=15000")
        self.conn.executescript(SCHEMA)
        if self.get("cash_core") is None:
            self.set("cash_core", cfg.core_sleeve_usd)
            self.set("cash_hype", cfg.hype_sleeve_usd)
            self.set("initial_balance", cfg.starting_balance_usd)
            self.set("peak_equity", cfg.starting_balance_usd)
            self.set("locked_total", False)
            self.set("locked_daily", False)
            self.set("hype_cumulative_loss_usd", 0.0)

    # -- kv ------------------------------------------------------------
    def get(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row[0])

    def set(self, key: str, value):
        with self.conn:
            self.conn.execute(
                "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)))

    # -- logs ----------------------------------------------------------
    def audit(self, level: str, category: str, message: str, ts_ms: int | None = None):
        with self.conn:
            self.conn.execute(
                "INSERT INTO audit_log(ts_ms, level, category, message) VALUES(?,?,?,?)",
                (ts_ms if ts_ms is not None else int(time.time() * 1000), level, category, message))

    def audit_log(self, limit: int = 200):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]

    def log_signal(self, ts_ms: int, symbol: str, action: str, approved: bool,
                   reject_reason: str | None, details: str):
        with self.conn:
            self.conn.execute(
                "INSERT INTO signals(ts_ms, symbol, action, approved, reject_reason, details) "
                "VALUES(?,?,?,?,?,?)",
                (ts_ms, symbol, action, int(approved), reject_reason, details))

    def signals(self, limit: int = 200):
        rows = [dict(r) for r in self.conn.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,))]
        for row in rows:
            row["approved"] = bool(row["approved"])
        return rows

    # -- positions / trades / equity ------------------------------------
    def open_positions(self):
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM positions ORDER BY id")]
        for row in rows:
            if row.get("indicator_snapshot"):
                row["indicator_snapshot"] = json.loads(row["indicator_snapshot"])
        return rows

    def position(self, symbol: str):
        row = self.conn.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
        return dict(row) if row else None

    def trades(self, limit: int = 1000, symbol: str | None = None, sleeve: str | None = None):
        q, args = "SELECT * FROM trades", []
        clauses = []
        if symbol:
            clauses.append("symbol=?"); args.append(symbol)
        if sleeve:
            clauses.append("sleeve=?"); args.append(sleeve)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = [dict(r) for r in self.conn.execute(q, args)]
        for row in rows:
            if row.get("indicator_snapshot"):
                row["indicator_snapshot"] = json.loads(row["indicator_snapshot"])
        return rows

    def record_equity(self, ts_ms: int, equity_usd: float, cash_core: float,
                      cash_hype: float, margin_used_usd: float, unrealized_usd: float):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO equity_history VALUES(?,?,?,?,?,?)",
                (ts_ms, equity_usd, cash_core, cash_hype, margin_used_usd, unrealized_usd))

    def equity_history(self, limit: int = 100_000):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM (SELECT * FROM equity_history ORDER BY ts_ms DESC LIMIT ?) ORDER BY ts_ms",
            (limit,))]

    def close(self):
        self.conn.close()
