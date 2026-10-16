from __future__ import annotations
import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: str, starting_balance: float, symbol: str):
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=15000")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS position (
                id INTEGER PRIMARY KEY CHECK(id=1), entry_ms INTEGER NOT NULL,
                entry_price REAL NOT NULL, qty REAL NOT NULL, entry_fee REAL NOT NULL,
                stop REAL NOT NULL, initial_stop REAL NOT NULL, target REAL NOT NULL,
                initial_r REAL NOT NULL, signal_bar_ms INTEGER NOT NULL,
                reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_ms INTEGER NOT NULL, exit_ms INTEGER NOT NULL,
                symbol TEXT NOT NULL, entry_price REAL NOT NULL,
                exit_price REAL NOT NULL, qty REAL NOT NULL,
                entry_fee REAL NOT NULL, exit_fee REAL NOT NULL,
                net_pnl REAL NOT NULL, exit_reason TEXT NOT NULL,
                signal_reason TEXT NOT NULL);
        """)
        if self.get("balance") is None:
            with self.conn:
                self.set("balance", starting_balance)
                self.set("initial_balance", starting_balance)
                self.set("peak_equity", starting_balance)
                self.set("symbol", symbol)
                self.set("locked_total", False)
        elif self.get("symbol") != symbol:
            raise ValueError("Existing DB uses another market. Use a separate --db path.")

    def get(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row[0])

    def set(self, key: str, value):
        self.conn.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    def position(self):
        row = self.conn.execute("SELECT * FROM position WHERE id=1").fetchone()
        return dict(row) if row else None

    def trades(self, limit=1000):
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))]

    def close(self):
        self.conn.close()
