"""Research Lab engine: live forward PAPER trading for the five new
strategies. Simulated fills only. Reuses the public market-data layer, perp
math and the live tick pipeline (TickerBook/LiveValuator/feed). Adds the
per-strategy $30 equity-floor exit+lock on top of the lab-level $50 trailing
drawdown. Auto-entry is OFF unless PAPERBOT_RESEARCH_AUTO_ENTRY=1.
"""
from __future__ import annotations
import json
import sqlite3
import threading
import time
from pathlib import Path
from paperbot.models import Candle
from paperbot.strategy import atr as atr_series, ema
from ..marketdata import MarketData, shared_marketdata
from ..perp import (ContractSpec, ExitEvent, check_exit, funding_cost,
                    plan_entry, realized_pnl, trail_stop, unrealized_pnl)
from ..lab.live import LiveStatePublisher, LiveValuator, TickerBook
from .config import STRATEGIES, ResearchSettings
from .governor import ResearchGovernor
from .store import ResearchStore

FUNDING_INTERVAL_MS = 8 * 3_600_000
CANDLE_LIMIT = 220


def main_db_instruments(main_db_path: str) -> list[dict]:
    p = Path(main_db_path)
    if not p.exists():
        return []
    conn = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(
            "SELECT i.* FROM instruments i JOIN universe u USING(coingecko_id) "
            "WHERE i.eligible=1 ORDER BY u.rank")]
    finally:
        conn.close()


class ResearchEngine:
    def __init__(self, store: ResearchStore, cfg: ResearchSettings,
                 market: MarketData | None = None, instruments_provider=None):
        self.db = store
        self.cfg = cfg
        self.market = market
        self.instruments_provider = (instruments_provider or
                                     (lambda: main_db_instruments(cfg.main_db_path)))
        self.governor = ResearchGovernor(store, cfg)
        self.live_book = None
        self.live_valuator = None
        self.live_publisher = None
        self.live_feed = None
        self.live_lock = threading.Lock()
        self._live_pos_cache: dict[str, dict] = {}

    # ---------------- accounting ----------------
    def equity(self, marks: dict[str, float]) -> float:
        total = self.db.total_cash()
        for p in self.db.open_positions():
            total += p["margin_usd"]
            m = marks.get(p["symbol"])
            if m is not None:
                total += unrealized_pnl(p["side"], p["entry_price"], m, p["qty"])
        return total

    def strategy_equity(self, marks: dict[str, float]) -> dict[str, float]:
        """Per-strategy net equity = its cash + its positions' margin + uPnL."""
        eq = {s.key: self.db.strategy_ledger()[s.key]["cash_usd"] for s in STRATEGIES}
        for p in self.db.open_positions():
            eq[p["strategy"]] += p["margin_usd"]
            m = marks.get(p["symbol"])
            if m is not None:
                eq[p["strategy"]] += unrealized_pnl(p["side"], p["entry_price"], m, p["qty"])
        return eq

    def _adjust(self, strategy, delta, realized=0.0):
        self.db.conn.execute(
            "UPDATE strategies SET cash_usd = cash_usd + ?, realized_pnl_usd = realized_pnl_usd + ? "
            "WHERE key=?", (delta, realized, strategy))

    def open_from_plan(self, inst, plan, strategy, cluster, rationale, snapshot, bar_ts, now_ms):
        with self.db.conn:
            self.db.conn.execute(
                """INSERT INTO positions(strategy, symbol, side, leverage, qty, entry_price,
                   margin_usd, notional_usd, stop, initial_stop, target, liq_price_est,
                   entry_fee_usd, funding_paid_usd, planned_risk_usd, mfe_price, mae_price,
                   opened_ms, signal_bar_ms, rationale, indicator_snapshot, exchange,
                   taker_fee, corr_cluster)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?,?)""",
                (strategy, inst["symbol"], plan.side, plan.leverage, plan.qty, plan.entry_price,
                 plan.margin_usd, plan.notional_usd, plan.stop, plan.stop, plan.target,
                 plan.liq_price_est, plan.entry_fee_usd, plan.planned_risk_usd,
                 plan.entry_price, plan.entry_price, now_ms, bar_ts, rationale,
                 json.dumps(snapshot) if snapshot else None, inst["exchange"],
                 inst["taker_fee"], cluster))
            self._adjust(strategy, -(plan.margin_usd + plan.entry_fee_usd))
        self.db.audit("info", "trade",
                      f"[{strategy}] SIMULATED OPEN {plan.side} {inst['symbol']} qty "
                      f"{plan.qty} @ {plan.entry_price:.6g}, stop {plan.stop:.6g}, no target, "
                      f"margin ${plan.margin_usd:.2f}", ts_ms=now_ms)
        self._refresh_live_cache()

    def close_position(self, pos, event, now_ms):
        credit = 0.0 if event.reason == "LIQUIDATION" else (
            pos["margin_usd"] + event.pnl_usd + pos["entry_fee_usd"] + pos["funding_paid_usd"])
        sign = 1 if pos["side"] == "long" else -1
        entry = pos["entry_price"]
        mfe = (sign * (pos["mfe_price"] - entry) / entry * 100) if pos.get("mfe_price") else None
        mae = (sign * (pos["mae_price"] - entry) / entry * 100) if pos.get("mae_price") else None
        with self.db.conn:
            # Idempotency guard (see lab engine): only book + credit if THIS
            # call removed the row, so a double-close can't double-credit.
            if self.db.conn.execute("DELETE FROM positions WHERE id=?",
                                    (pos["id"],)).rowcount == 0:
                return
            self.db.conn.execute(
                """INSERT INTO trades(strategy, symbol, side, leverage, qty, entry_price,
                   exit_price, stop_initial, stop_final, target, margin_usd, notional_usd,
                   entry_fee_usd, exit_fee_usd, funding_usd, net_pnl_usd, mfe_pct, mae_pct,
                   entry_ms, exit_ms, exit_reason, rationale, indicator_snapshot)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pos["strategy"], pos["symbol"], pos["side"], pos["leverage"], pos["qty"],
                 entry, event.exit_price, pos["initial_stop"], pos["stop"], pos["target"],
                 pos["margin_usd"], pos["notional_usd"], pos["entry_fee_usd"], event.exit_fee_usd,
                 pos["funding_paid_usd"], event.pnl_usd, mfe, mae, pos["opened_ms"], now_ms,
                 event.reason, pos["rationale"],
                 pos.get("indicator_snapshot") if isinstance(pos.get("indicator_snapshot"), str)
                 else json.dumps(pos.get("indicator_snapshot"))))
            self._adjust(pos["strategy"], credit, realized=event.pnl_usd)
        self.db.set(f"research_last_exit:{pos['symbol']}", now_ms)
        self.db.audit("warning" if event.pnl_usd < 0 else "info", "trade",
                      f"[{pos['strategy']}] SIMULATED EXIT ({event.reason}) {pos['symbol']} @ "
                      f"{event.exit_price:.6g}; net P&L {event.pnl_usd:+.2f}", ts_ms=now_ms)
        self._refresh_live_cache()

    def apply_funding_due(self, pos, now_ms, rate, mark):
        if rate is None:
            return 0
        row = self.db.conn.execute(
            "SELECT MAX(funding_ts_ms) FROM funding_events WHERE position_id=?",
            (pos["id"],)).fetchone()
        anchor = row[0] if row and row[0] is not None else pos["opened_ms"]
        boundary = (anchor // FUNDING_INTERVAL_MS + 1) * FUNDING_INTERVAL_MS
        applied = 0
        while boundary <= now_ms:
            amount = funding_cost(pos["side"], rate, mark, pos["qty"])
            with self.db.conn:
                if self.db.conn.execute("INSERT OR IGNORE INTO funding_events VALUES(?,?,?,?)",
                                        (pos["id"], boundary, rate, amount)).rowcount:
                    self._adjust(pos["strategy"], -amount)
                    self.db.conn.execute(
                        "UPDATE positions SET funding_paid_usd = funding_paid_usd + ? WHERE id=?",
                        (amount, pos["id"]))
                    applied += 1
            boundary += FUNDING_INTERVAL_MS
        if applied:
            pos.update(self.db.position(pos["symbol"]) or {})
        return applied

    # ---------------- exits ----------------
    def _force_exit(self, pos, observed, now_ms, label):
        event = check_exit(pos, observed, self.cfg, pos["taker_fee"])
        if event is None:
            sign = 1 if pos["side"] == "long" else -1
            fill = observed * (1 - sign * self.cfg.slippage_rate)
            exit_fee = abs(fill * pos["qty"] * pos["taker_fee"])
            pnl = realized_pnl(pos["side"], pos["entry_price"], fill, pos["qty"],
                               pos["entry_fee_usd"], exit_fee, pos["funding_paid_usd"])
            event = ExitEvent(label, fill, pnl, exit_fee)
        self.close_position(pos, event, now_ms)

    def _lock_breached_strategies(self, marks, now_ms, summary):
        eq = self.strategy_equity(marks)
        for key in self.governor.strategy_equity_breaches(eq):
            if self.db.strategy_ledger()[key]["locked"]:
                continue
            self.governor.lock_strategy(
                key, f"equity ${eq[key]:.2f} <= ${self.cfg.strategy_lock_floor_usd:.0f} floor "
                     "($20 cumulative loss)", now_ms)
            for pos in [p for p in self.db.open_positions() if p["strategy"] == key]:
                mark = marks.get(pos["symbol"])
                if mark is not None:
                    self._force_exit(pos, mark, now_ms, "STRATEGY LOCK EXIT")
                    summary["closed"] += 1
                else:
                    self.db.audit("error", "risk",
                                  f"[{key}] lock exit DEFERRED: {pos['symbol']} unverifiable",
                                  ts_ms=now_ms)

    def _emergency_exit_all(self, marks, now_ms, summary):
        for pos in self.db.open_positions():
            mark = marks.get(pos["symbol"])
            if mark is None:
                self.db.audit("error", "risk",
                              f"EMERGENCY EXIT DEFERRED: {pos['symbol']} unverifiable, will retry",
                              ts_ms=now_ms)
                continue
            self._force_exit(pos, mark, now_ms, "EMERGENCY (lab trailing drawdown)")
            summary["closed"] += 1

    # ---------------- live tick path (reuses LiveValuator) ----------------
    def start_live_components(self, publisher_clock=None):
        self.live_book = TickerBook()
        self.live_valuator = LiveValuator(self.db, self.cfg, self.governor)
        kwargs = {"min_interval_s": self.cfg.live_publish_interval_s}
        if publisher_clock is not None:
            kwargs["clock"] = publisher_clock
        self.live_publisher = LiveStatePublisher(self.cfg.live_state_path, **kwargs)
        self._refresh_live_cache()

    def start_live_feed(self):
        from ..lab.feed import BybitTickerFeed
        symbols = [LiveValuator._book_symbol(p["symbol"]) for p in self.db.open_positions()]
        for inst in self.instruments_provider():
            if inst.get("exchange") == "bybit":
                symbols.append(LiveValuator._book_symbol(inst["symbol"]))
        symbols = list(dict.fromkeys(symbols))[:self.cfg.ws_max_topics]
        self.live_feed = BybitTickerFeed(symbols, self.on_live_ticker, url=self.cfg.ws_url)
        self.live_feed.start()

    def _refresh_live_cache(self):
        self._live_pos_cache = {LiveValuator._book_symbol(p["symbol"]): p
                                for p in self.db.open_positions()}

    def on_live_ticker(self, symbol, fields, ts_ms, kind):
        if self.live_book is None or not self.live_book.apply(symbol, fields, ts_ms, kind):
            return
        with self.live_lock:
            now_ms = int(time.time() * 1000)
            cached = self._live_pos_cache.get(symbol)
            pos = self.db.position(cached["symbol"]) if cached else None
            if pos is not None:
                tk = self.live_book.get(symbol)
                observed = (tk.get("bid1Price") if pos["side"] == "long" else
                            tk.get("ask1Price")) or tk.get("lastPrice")
                if observed is not None:
                    ev = check_exit(pos, float(observed), self.cfg, pos["taker_fee"])
                    if ev is not None:
                        self.close_position(pos, ev, now_ms)
            marks = self._marks_from_book()
            self._lock_breached_strategies(marks, now_ms, {"closed": 0})
            state = self.live_valuator.value(self.live_book, now_ms)
            if state["locked"] and self.db.open_positions():
                self._emergency_exit_all(marks, now_ms, {"closed": 0})
                state = self.live_valuator.value(self.live_book, now_ms)
            self.live_publisher.publish(state)

    def _marks_from_book(self):
        marks = {}
        for p in self.db.open_positions():
            tk = self.live_book.get(LiveValuator._book_symbol(p["symbol"]))
            if tk and tk.get("markPrice") is not None:
                marks[p["symbol"]] = tk["markPrice"]
        return marks

    # ---------------- gate ----------------
    def auto_entry_allowed(self) -> tuple[bool, str]:
        if not self.cfg.auto_entry:
            return False, "auto-entry disabled (PAPERBOT_RESEARCH_AUTO_ENTRY)"
        return True, ""

    # ---------------- scan cycle ----------------
    def run_cycle(self, now_ms=None) -> dict:
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        market = self.market or shared_marketdata(self.cfg)
        summary = {"scanned": 0, "signals": 0, "opened": 0, "closed": 0,
                   "errors": 0, "quotes_ok": 0}
        marks = dict(self.db.get("marks", {}) or {})
        from .strategies import evaluate_all
        # pass 1: monitor every open position
        for pos in self.db.open_positions():
            try:
                ticker, tick_age = market.ticker(pos["exchange"], pos["symbol"])
            except Exception as exc:
                summary["errors"] += 1
                self.db.audit("error", "risk",
                              f"POSITION UNMONITORED: {pos['symbol']} unverifiable "
                              f"({type(exc).__name__})", ts_ms=now_ms)
                continue
            bid, ask = ticker.get("bid"), ticker.get("ask")
            last = ticker.get("last") or (bid and ask and (bid + ask) / 2)
            if last is None:
                summary["errors"] += 1
                continue
            summary["quotes_ok"] += 1
            marks[pos["symbol"]] = float(last)
            try:
                f, _ = market.funding_rate(pos["exchange"], pos["symbol"])
                rate = f.get("fundingRate") if f else None
            except Exception:
                rate = None
            self.apply_funding_due(pos, now_ms, rate, float(last))
            observed = float(bid if pos["side"] == "long" and bid else
                             ask if pos["side"] == "short" and ask else last)
            sign = 1 if pos["side"] == "long" else -1
            with self.db.conn:
                self.db.conn.execute(
                    "UPDATE positions SET mfe_price=CASE WHEN ?*?>?*mfe_price THEN ? ELSE mfe_price END, "
                    "mae_price=CASE WHEN ?*?<?*mae_price THEN ? ELSE mae_price END WHERE id=?",
                    (sign, observed, sign, observed, sign, observed, sign, observed, pos["id"]))
            pos = self.db.position(pos["symbol"])
            ev = check_exit(pos, observed, self.cfg, pos["taker_fee"])
            if ev is not None:
                self.close_position(pos, ev, now_ms)
                summary["closed"] += 1
        # pass 1b: per-strategy equity-floor locks + exits
        self._lock_breached_strategies(marks, now_ms, summary)
        # pass 1c: lab-level breach -> emergency exit
        equity_now = self.equity(marks)
        hwm = self.governor.update_hwm(equity_now, now_ms)
        if self.db.get("lab_locked") and self.db.open_positions():
            self._emergency_exit_all(marks, now_ms, summary)
            equity_now = self.equity(marks)
            hwm = self.governor.update_hwm(equity_now, now_ms)
        # pass 2: strategy scan for new entries
        for inst in self.instruments_provider():
            symbol, exchange = inst["symbol"], inst["exchange"]
            try:
                raw, candle_age = market.candles(exchange, symbol, self.cfg.candle_timeframe, CANDLE_LIMIT)
                ticker, tick_age = market.ticker(exchange, symbol)
            except Exception as exc:
                summary["errors"] += 1
                self.db.audit("warning", "data",
                              f"{symbol}: market data unavailable, skipped ({type(exc).__name__})",
                              ts_ms=now_ms)
                continue
            bars = [Candle(int(x[0]), *[float(v) for v in x[1:6]]) for x in raw]
            closed = [b for b in bars if b.timestamp + self.cfg.timeframe_ms <= now_ms]
            bid, ask = ticker.get("bid"), ticker.get("ask")
            last = ticker.get("last") or (bid and ask and (bid + ask) / 2)
            if not closed or last is None:
                continue
            summary["quotes_ok"] += 1
            marks[symbol] = float(last)
            if self.db.position(symbol) is not None:
                continue
            summary["scanned"] += 1
            context = self._context(market, exchange, symbol)
            evals = evaluate_all(closed, self.cfg, context)
            spread_pct = ((ask - bid) / ask) if (bid and ask and ask > 0) else None
            latest_bar = closed[-1].timestamp
            for sdef in STRATEGIES:
                sig = evals[sdef.key]
                if sig.action is None:
                    continue
                seen_key = f"research_seen:{sdef.key}:{symbol}"
                if self.db.get(seen_key) == latest_bar:
                    continue
                self.db.set(seen_key, latest_bar)
                summary["signals"] += 1
                last_exit = self.db.get(f"research_last_exit:{symbol}")
                if last_exit is not None and latest_bar + self.cfg.timeframe_ms <= last_exit:
                    self.db.log_signal(now_ms, sdef.key, symbol, sig.action, False,
                                       "re-entry cooldown", sig.reason)
                    continue
                allowed, reason = self.auto_entry_allowed()
                if not allowed:
                    self.db.log_signal(now_ms, sdef.key, symbol, sig.action, False, reason, sig.reason)
                    continue
                if tick_age > self.cfg.price_fresh_seconds:
                    self.db.log_signal(now_ms, sdef.key, symbol, sig.action, False,
                                       f"quote stale ({tick_age:.0f}s)", sig.reason)
                    continue
                entry_quote = ask if sig.action == "long" else bid
                if entry_quote is None or spread_pct is None:
                    self.db.log_signal(now_ms, sdef.key, symbol, sig.action, False,
                                       "quote missing bid/ask side", sig.reason)
                    continue
                if spread_pct > self.cfg.max_spread_pct:
                    self.db.log_signal(now_ms, sdef.key, symbol, sig.action, False,
                                       f"spread {spread_pct:.4%} too wide", sig.reason)
                    continue
                spec = ContractSpec(symbol, inst["taker_fee"], inst["maint_margin_rate"],
                                    inst["tick_size"], inst["lot_size"])
                ledger = self.db.strategy_ledger()[sdef.key]
                plan = plan_entry(sig.action, float(entry_quote), sig.atr, spec, self.cfg,
                                  equity=self.equity(marks), available_margin=ledger["cash_usd"],
                                  risk_budget_usd=self.cfg.max_risk_per_trade_usd, with_target=False)
                if not plan.ok:
                    self.db.log_signal(now_ms, sdef.key, symbol, sig.action, False, plan.reason, sig.reason)
                    continue
                cluster = symbol.split("/")[0]
                planned = {"strategy": sdef.key, "symbol": symbol,
                           "planned_risk_usd": plan.planned_risk_usd, "margin_usd": plan.margin_usd,
                           "entry_fee_usd": plan.entry_fee_usd, "corr_cluster": cluster}
                verdict = self.governor.approve(planned, now_ms, log=True, action=sig.action)
                if verdict.approved:
                    self.open_from_plan(inst, plan, sdef.key, cluster, sig.reason,
                                        sig.indicators, latest_bar, now_ms)
                    summary["opened"] += 1
                    break
        # pass 3: equity snapshot (honest gap if no quotes while holding)
        positions = self.db.open_positions()
        if positions and summary["quotes_ok"] == 0:
            self.db.audit("warning", "data",
                          "equity snapshot skipped: no fresh quotes this cycle", ts_ms=now_ms)
        else:
            equity_now = self.equity(marks)
            hwm = self.governor.update_hwm(equity_now, now_ms)
            margin_used = sum(p["margin_usd"] for p in self.db.open_positions())
            self.db.record_equity(now_ms, equity_now, self.db.total_cash(), margin_used,
                                  equity_now - self.db.total_cash() - margin_used,
                                  hwm["peak_equity"], hwm["threshold"])
        self.db.set("marks", marks)
        self.db.set("last_scan_ms", now_ms)
        return summary

    def _context(self, market, exchange, symbol) -> dict:
        try:
            funding, _ = market.funding_rate(exchange, symbol)
            rate = funding.get("fundingRate") if funding else None
        except Exception:
            rate = None
        ctx = {"funding_rate": rate, "orderbook": None,
               "htf_trend_4h": "up", "htf_trend_1h": "up"}
        for attr, key, tf in (("htf_trend", "htf_trend_4h", "4h"),
                              ("htf_trend", "htf_trend_1h", "1h")):
            fn = getattr(market, attr, None)
            if fn is not None:
                try:
                    ctx[key] = fn(exchange, symbol, tf)
                except Exception:
                    pass
        ob = getattr(market, "orderbook", None)
        if ob is not None:
            try:
                book, _ = ob(exchange, symbol)
                ctx["orderbook"] = book
            except Exception:
                ctx["orderbook"] = None
        return ctx
