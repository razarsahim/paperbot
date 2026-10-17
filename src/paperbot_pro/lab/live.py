"""Tick-driven live valuation for the Extreme Lab.

Single source of truth: the engine process holds the TickerBook (fed by the
public WebSocket), values positions with the mark price, lets the governor
ratchet/check the persistent high-water mark on every valuation, and
publishes a throttled, atomically-written JSON snapshot for the API to
stream. High-frequency ticks never touch SQLite — only accounting events
(closes, funding, lockouts) and the governor's HWM do.
"""
from __future__ import annotations
import json
import os
import time
from ..perp import unrealized_pnl
from .config import LabSettings
from .governor import LabGovernor
from .store import LabStore


class TickerBook:
    """Latest ticker per symbol with Bybit-style snapshot/delta semantics:
    deltas carry only changed fields and merge over the retained snapshot;
    out-of-order exchange timestamps are rejected."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._book: dict[str, dict] = {}
        self._local_at: dict[str, float] = {}

    def apply(self, symbol: str, fields: dict, ts_ms: int, kind: str) -> bool:
        current = self._book.get(symbol)
        if current is not None and ts_ms < current["ts_ms"]:
            return False  # out-of-order: keep the newer state
        parsed = {}
        for key, value in fields.items():
            try:
                parsed[key] = float(value)
            except (TypeError, ValueError):
                parsed[key] = value
        if kind == "snapshot" or current is None:
            merged = parsed
        else:
            merged = {**current, **parsed}
        merged["ts_ms"] = ts_ms
        self._book[symbol] = merged
        self._local_at[symbol] = self.clock()
        return True

    def get(self, symbol: str) -> dict | None:
        return self._book.get(symbol)

    def age_seconds(self, symbol: str) -> float | None:
        at = self._local_at.get(symbol)
        return None if at is None else self.clock() - at

    def symbols(self) -> list[str]:
        return list(self._book)


class LiveValuator:
    """Marks open positions against the book, maintains the persistent HWM
    via the governor (which locks atomically on breach), and reports
    distances to stop/liquidation. Never fabricates a missing mark."""
    def __init__(self, store: LabStore, cfg: LabSettings, governor: LabGovernor):
        self.db = store
        self.cfg = cfg
        self.governor = governor

    def value(self, book: TickerBook, now_ms: int) -> dict:
        positions_out = []
        unrealized_total = 0.0
        complete = True
        newest_exchange_ts = None
        for pos in self.db.open_positions():
            ticker = book.get(self._book_symbol(pos["symbol"]))
            mark = ticker.get("markPrice") if ticker else None
            if ticker is not None and ticker["ts_ms"] > (newest_exchange_ts or 0):
                newest_exchange_ts = ticker["ts_ms"]
            if mark is None:
                complete = False
                upnl = pct = None
            else:
                upnl = unrealized_pnl(pos["side"], pos["entry_price"], mark, pos["qty"])
                pct = upnl / pos["margin_usd"] * 100 if pos["margin_usd"] else None
                unrealized_total += upnl
            def dist(level):
                if mark is None or level is None or mark <= 0:
                    return None
                return abs(mark - level) / mark * 100
            positions_out.append({
                "id": pos["id"], "strategy": pos["strategy"], "symbol": pos["symbol"],
                "side": pos["side"], "leverage": pos["leverage"], "qty": pos["qty"],
                "entry_price": pos["entry_price"], "mark_price": mark,
                "last_price": ticker.get("lastPrice") if ticker else None,
                "bid": ticker.get("bid1Price") if ticker else None,
                "ask": ticker.get("ask1Price") if ticker else None,
                "notional_usd": (mark * pos["qty"]) if mark is not None else pos["notional_usd"],
                "margin_usd": pos["margin_usd"], "stop": pos["stop"],
                "liq_price_est": pos["liq_price_est"],
                "funding_paid_usd": pos["funding_paid_usd"],
                "unrealized_pnl_usd": upnl, "unrealized_pct_on_margin": pct,
                "stop_distance_pct": dist(pos["stop"]),
                "liq_distance_pct": dist(pos["liq_price_est"]),
                "exchange_ts_ms": ticker["ts_ms"] if ticker else None,
            })
        cash = self.db.total_cash()
        margin_used = sum(p["margin_usd"] for p in positions_out)
        equity = cash + margin_used + unrealized_total
        realized = sum(r["realized_pnl_usd"]
                       for r in self.db.strategy_ledger().values())
        if complete and positions_out or not positions_out:
            hwm = self.governor.update_hwm(equity, now_ms)
        else:
            # incomplete marks: do not ratchet/lock on a partial valuation
            peak = float(self.db.get("peak_equity", self.cfg.starting_capital_usd))
            hwm = {"peak_equity": peak,
                   "threshold": peak - self.cfg.trailing_drawdown_usd,
                   "breached": False, "locked": bool(self.db.get("lab_locked")),
                   "excess_loss_usd": 0.0}
        return {
            "ts_ms": now_ms,
            "exchange_ts_ms": newest_exchange_ts,
            "breached": hwm["breached"],
            "locked": bool(self.db.get("lab_locked")),
            "positions": positions_out,
            "capital": {
                "initial_usd": self.cfg.starting_capital_usd,
                "equity_usd": equity, "cash_usd": cash,
                "margin_used_usd": margin_used,
                "unrealized_usd": unrealized_total,
                "realized_usd": realized,
                "peak_equity_usd": hwm["peak_equity"],
                "threshold_usd": hwm["threshold"],
                "remaining_allowance_usd": max(0.0, equity - hwm["threshold"]),
                "complete": complete,
            },
        }

    @staticmethod
    def _book_symbol(unified: str) -> str:
        """ccxt unified linear perp ('BCH/USDT:USDT') -> Bybit topic id ('BCHUSDT')."""
        return unified.split(":")[0].replace("/", "")


class LiveStatePublisher:
    """Throttled atomic JSON snapshots (write temp + rename): readers never
    see a torn file, and ticks faster than min_interval_s coalesce."""
    def __init__(self, path: str, min_interval_s: float = 0.25, clock=time.monotonic):
        self.path = path
        self.min_interval_s = min_interval_s
        self.clock = clock
        self._last_pub = -1e18

    def publish(self, state: dict) -> bool:
        now = self.clock()
        if now - self._last_pub < self.min_interval_s:
            return False
        self._last_pub = now
        payload = dict(state)
        payload["published_at_ms"] = int(time.time() * 1000)
        tmp = f"{self.path}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload))
        os.replace(tmp, self.path)
        return True
