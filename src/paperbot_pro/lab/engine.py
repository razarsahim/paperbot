"""Extreme Lab engine: live forward PAPER trading on public data.

Simulated fills only. Entry requires, in order: a fresh completed-candle
strategy signal, the Lab auto-entry flag, fresh tight-spread quotes, a
solvent $-risk plan, and the LabGovernor's verdict (rails + trailing-HWM
lock). Open positions are monitored every cycle independent of signal
cadence; stops trail on completed candles and never widen. A trailing-
drawdown breach locks all strategies and emergency-exits positions using
real observed quotes — or honestly reports that it cannot, and retries.
"""
from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path
from paperbot.models import Candle
from paperbot.strategy import atr as atr_series
from ..marketdata import MarketData, shared_marketdata
from ..perp import (ContractSpec, ExitEvent, check_exit, funding_cost,
                    plan_entry, realized_pnl, trail_stop, unrealized_pnl)
from .config import STRATEGIES, LabSettings
from .governor import LabGovernor
from .store import LabStore

FUNDING_INTERVAL_MS = 8 * 3_600_000
CANDLE_LIMIT = 200


def main_db_instruments(main_db_path: str) -> list[dict]:
    """Read eligible instruments from the MAIN portfolio DB, read-only."""
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


class LabEngine:
    def __init__(self, store: LabStore, cfg: LabSettings,
                 market: MarketData | None = None, instruments_provider=None):
        self.db = store
        self.cfg = cfg
        self.market = market
        self.instruments_provider = (instruments_provider or
                                     (lambda: main_db_instruments(cfg.main_db_path)))
        self.governor = LabGovernor(store, cfg)

    # ---------------- accounting ----------------
    def equity(self, marks: dict[str, float]) -> float:
        total = self.db.total_cash()
        for pos in self.db.open_positions():
            total += pos["margin_usd"]
            mark = marks.get(pos["symbol"])
            if mark is not None:
                total += unrealized_pnl(pos["side"], pos["entry_price"], mark, pos["qty"])
        return total

    def _adjust_strategy_cash(self, strategy: str, delta: float, realized: float = 0.0):
        self.db.conn.execute(
            "UPDATE strategies SET cash_usd = cash_usd + ?, "
            "realized_pnl_usd = realized_pnl_usd + ? WHERE key=?",
            (delta, realized, strategy))

    def open_from_plan(self, inst: dict, plan, strategy: str, rationale: str,
                       snapshot: dict | None, bar_ts: int, now_ms: int) -> None:
        with self.db.conn:
            self.db.conn.execute(
                """INSERT INTO positions(strategy, symbol, side, leverage, qty, entry_price,
                   margin_usd, notional_usd, stop, initial_stop, target, liq_price_est,
                   entry_fee_usd, funding_paid_usd, planned_risk_usd, mfe_price, mae_price,
                   opened_ms, signal_bar_ms, rationale, indicator_snapshot, exchange, taker_fee)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?)""",
                (strategy, inst["symbol"], plan.side, plan.leverage, plan.qty,
                 plan.entry_price, plan.margin_usd, plan.notional_usd, plan.stop,
                 plan.stop, plan.target, plan.liq_price_est, plan.entry_fee_usd,
                 plan.planned_risk_usd, plan.entry_price, plan.entry_price,
                 now_ms, bar_ts, rationale,
                 json.dumps(snapshot) if snapshot else None,
                 inst["exchange"], inst["taker_fee"]))
            self._adjust_strategy_cash(strategy, -(plan.margin_usd + plan.entry_fee_usd))
        self.db.audit("info", "trade",
                      f"[{strategy}] SIMULATED OPEN {plan.side} {inst['symbol']} qty "
                      f"{plan.qty} @ {plan.entry_price:.6g}, stop {plan.stop:.6g}, "
                      f"no fixed target, liq est {plan.liq_price_est:.6g}, "
                      f"margin ${plan.margin_usd:.2f}", ts_ms=now_ms)

    def close_position(self, pos: dict, event: ExitEvent, now_ms: int) -> None:
        if event.reason == "LIQUIDATION":
            credit = 0.0
        else:
            credit = (pos["margin_usd"] + event.pnl_usd + pos["entry_fee_usd"]
                      + pos["funding_paid_usd"])
        sign = 1 if pos["side"] == "long" else -1
        entry = pos["entry_price"]
        mfe = (sign * (pos["mfe_price"] - entry) / entry * 100) if pos.get("mfe_price") else None
        mae = (sign * (pos["mae_price"] - entry) / entry * 100) if pos.get("mae_price") else None
        with self.db.conn:
            self.db.conn.execute(
                """INSERT INTO trades(strategy, symbol, side, leverage, qty, entry_price,
                   exit_price, stop_initial, stop_final, target, margin_usd, notional_usd,
                   entry_fee_usd, exit_fee_usd, funding_usd, net_pnl_usd, mfe_pct, mae_pct,
                   entry_ms, exit_ms, exit_reason, rationale, indicator_snapshot)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pos["strategy"], pos["symbol"], pos["side"], pos["leverage"], pos["qty"],
                 entry, event.exit_price, pos["initial_stop"], pos["stop"], pos["target"],
                 pos["margin_usd"], pos["notional_usd"], pos["entry_fee_usd"],
                 event.exit_fee_usd, pos["funding_paid_usd"], event.pnl_usd, mfe, mae,
                 pos["opened_ms"], now_ms, event.reason, pos["rationale"],
                 pos.get("indicator_snapshot") if isinstance(pos.get("indicator_snapshot"), str)
                 else json.dumps(pos.get("indicator_snapshot"))))
            self.db.conn.execute("DELETE FROM positions WHERE id=?", (pos["id"],))
            self._adjust_strategy_cash(pos["strategy"], credit, realized=event.pnl_usd)
        self.db.set(f"lab_last_exit:{pos['symbol']}", now_ms)
        self.db.audit("warning" if event.pnl_usd < 0 else "info", "trade",
                      f"[{pos['strategy']}] SIMULATED EXIT ({event.reason}) {pos['symbol']} "
                      f"@ {event.exit_price:.6g}; net P&L {event.pnl_usd:+.2f}", ts_ms=now_ms)

    def apply_funding_due(self, pos: dict, now_ms: int, rate: float | None,
                          mark: float) -> int:
        if rate is None:
            self.db.audit("warning", "data",
                          f"funding rate unavailable for {pos['symbol']}; not applied",
                          ts_ms=now_ms)
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
                inserted = self.db.conn.execute(
                    "INSERT OR IGNORE INTO funding_events VALUES(?,?,?,?)",
                    (pos["id"], boundary, rate, amount)).rowcount
                if inserted:
                    self._adjust_strategy_cash(pos["strategy"], -amount)
                    self.db.conn.execute(
                        "UPDATE positions SET funding_paid_usd = funding_paid_usd + ? WHERE id=?",
                        (amount, pos["id"]))
                    applied += 1
            boundary += FUNDING_INTERVAL_MS
        if applied:
            pos.update(self.db.position(pos["symbol"]) or {})
        return applied

    # ---------------- emergency exits ----------------
    def _force_exit(self, pos: dict, observed: float, now_ms: int) -> None:
        event = check_exit(pos, observed, self.cfg, pos["taker_fee"])
        if event is None:  # no stop/liq crossed: forced exit at observed price
            sign = 1 if pos["side"] == "long" else -1
            fill = observed * (1 - sign * self.cfg.slippage_rate)
            exit_fee = abs(fill * pos["qty"] * pos["taker_fee"])
            pnl = realized_pnl(pos["side"], pos["entry_price"], fill, pos["qty"],
                               pos["entry_fee_usd"], exit_fee, pos["funding_paid_usd"])
            event = ExitEvent("EMERGENCY (trailing drawdown)", fill, pnl, exit_fee)
        self.close_position(pos, event, now_ms)

    def emergency_exit_all(self, market, now_ms: int, summary: dict) -> None:
        for pos in self.db.open_positions():
            try:
                ticker, _age = market.ticker(pos["exchange"], pos["symbol"])
                bid, ask = ticker.get("bid"), ticker.get("ask")
                observed = bid if pos["side"] == "long" and bid else \
                    ask if pos["side"] == "short" and ask else ticker.get("last")
                if observed is None:
                    raise ValueError("empty quote")
            except Exception as exc:
                self.db.audit("error", "risk",
                              f"EMERGENCY EXIT DEFERRED: {pos['symbol']} value and exit "
                              f"cannot be verified ({type(exc).__name__}); position retained, "
                              "will retry", ts_ms=now_ms)
                continue
            self._force_exit(pos, float(observed), now_ms)
            summary["closed"] += 1

    # ---------------- main cycle ----------------
    def run_cycle(self, now_ms: int | None = None) -> dict:
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        market = self.market or shared_marketdata(self.cfg)
        summary = {"scanned": 0, "signals": 0, "opened": 0, "closed": 0,
                   "errors": 0, "quotes_ok": 0}
        marks: dict[str, float] = dict(self.db.get("marks", {}) or {})
        # ---- pass 1: monitor EVERY open position ----
        for pos in self.db.open_positions():
            try:
                ticker, tick_age = market.ticker(pos["exchange"], pos["symbol"])
            except Exception as exc:
                summary["errors"] += 1
                self.db.audit("error", "risk",
                              f"POSITION UNMONITORED this tick: {pos['symbol']} current "
                              f"value cannot be verified ({type(exc).__name__})", ts_ms=now_ms)
                continue
            bid, ask = ticker.get("bid"), ticker.get("ask")
            last = ticker.get("last") or (bid and ask and (bid + ask) / 2)
            if last is None:
                summary["errors"] += 1
                self.db.audit("error", "risk",
                              f"POSITION UNMONITORED this tick: {pos['symbol']} quote empty",
                              ts_ms=now_ms)
                continue
            if tick_age > self.cfg.price_fresh_seconds:
                self.db.audit("warning", "data",
                              f"{pos['symbol']}: monitoring on STALE quote ({tick_age:.0f}s)",
                              ts_ms=now_ms)
            summary["quotes_ok"] += 1
            marks[pos["symbol"]] = float(last)
            try:
                funding, _ = market.funding_rate(pos["exchange"], pos["symbol"])
                rate = funding.get("fundingRate") if funding else None
            except Exception:
                rate = None
            self.apply_funding_due(pos, now_ms, rate, float(last))
            observed = float(bid if pos["side"] == "long" and bid else
                             ask if pos["side"] == "short" and ask else last)
            sign = 1 if pos["side"] == "long" else -1
            with self.db.conn:
                self.db.conn.execute(
                    "UPDATE positions SET mfe_price = CASE WHEN ?*? > ?*mfe_price THEN ? ELSE mfe_price END, "
                    "mae_price = CASE WHEN ?*? < ?*mae_price THEN ? ELSE mae_price END WHERE id=?",
                    (sign, observed, sign, observed, sign, observed, sign, observed, pos["id"]))
            pos = self.db.position(pos["symbol"])
            event = check_exit(pos, observed, self.cfg, pos["taker_fee"])
            if event is not None:
                self.close_position(pos, event, now_ms)
                summary["closed"] += 1
        # ---- pass 2: strategy scan on completed candles ----
        for inst in self.instruments_provider():
            symbol, exchange = inst["symbol"], inst["exchange"]
            try:
                raw, candle_age = market.candles(exchange, symbol,
                                                 self.cfg.candle_timeframe, CANDLE_LIMIT)
                ticker, tick_age = market.ticker(exchange, symbol)
            except Exception as exc:
                summary["errors"] += 1
                self.db.audit("warning", "data",
                              f"{symbol}: market data unavailable, skipped "
                              f"({type(exc).__name__})", ts_ms=now_ms)
                continue
            bars = [Candle(int(x[0]), *[float(v) for v in x[1:6]]) for x in raw]
            closed = [b for b in bars if b.timestamp + self.cfg.timeframe_ms <= now_ms]
            bid, ask = ticker.get("bid"), ticker.get("ask")
            last = ticker.get("last") or (bid and ask and (bid + ask) / 2)
            if not closed or last is None:
                continue
            summary["quotes_ok"] += 1
            marks[symbol] = float(last)
            summary["scanned"] += 1
            # trail the stop of an open position on this symbol (completed bars)
            pos = self.db.position(symbol)
            if pos is not None:
                current_atr = atr_series(closed, 14)[-1]
                if current_atr and current_atr > 0:
                    new_stop = trail_stop(pos["side"], pos["stop"], closed[-1].close,
                                          current_atr, self.cfg.trail_atr_multiplier)
                    if new_stop != pos["stop"]:
                        with self.db.conn:
                            self.db.conn.execute(
                                "UPDATE positions SET stop=? WHERE id=?", (new_stop, pos["id"]))
                        self.db.audit("info", "trade",
                                      f"[{pos['strategy']}] trailing stop -> {new_stop:.6g} "
                                      f"({pos['symbol']}, never widened)", ts_ms=now_ms)
                continue  # one position per symbol: no fresh entries on it
            try:
                funding, _ = market.funding_rate(exchange, symbol)
                funding_rate = funding.get("fundingRate") if funding else None
            except Exception:
                funding_rate = None
            listing_age_days = (len(raw) / 24.0) if len(raw) < CANDLE_LIMIT else None
            context = {"funding_rate": funding_rate,
                       "listing_age_days": listing_age_days if listing_age_days is not None
                       else 9999}
            results = self.db.get("lab_opportunities", {}) or {}
            evaluations = __import__("paperbot_pro.lab.strategies",
                                     fromlist=["evaluate_all"]).evaluate_all(
                closed, self.cfg, context)
            results[symbol] = {k: {"action": s.action, "reason": s.reason}
                               for k, s in evaluations.items()}
            self.db.set("lab_opportunities", results)
            spread_pct = ((ask - bid) / ask) if (bid and ask and ask > 0) else None
            latest_bar = closed[-1].timestamp
            for strategy_def in STRATEGIES:
                signal = evaluations[strategy_def.key]
                if signal.action is None:
                    continue
                seen_key = f"lab_seen:{strategy_def.key}:{symbol}"
                if self.db.get(seen_key) == latest_bar:
                    continue
                self.db.set(seen_key, latest_bar)
                summary["signals"] += 1
                last_exit = self.db.get(f"lab_last_exit:{symbol}")
                if last_exit is not None and latest_bar + self.cfg.timeframe_ms <= last_exit:
                    self.db.log_signal(now_ms, strategy_def.key, symbol, signal.action,
                                       False, "re-entry cooldown", signal.reason)
                    continue
                if not self.cfg.auto_entry:
                    self.db.log_signal(now_ms, strategy_def.key, symbol, signal.action,
                                       False, "Lab auto-entry disabled (PAPERBOT_LAB_AUTO_ENTRY)",
                                       signal.reason)
                    continue
                if tick_age > self.cfg.price_fresh_seconds:
                    self.db.log_signal(now_ms, strategy_def.key, symbol, signal.action,
                                       False, f"quote stale ({tick_age:.0f}s)", signal.reason)
                    continue
                entry_quote = ask if signal.action == "long" else bid
                if entry_quote is None or spread_pct is None:
                    self.db.log_signal(now_ms, strategy_def.key, symbol, signal.action,
                                       False, "quote missing bid/ask side", signal.reason)
                    continue
                if spread_pct > self.cfg.max_spread_pct:
                    self.db.log_signal(now_ms, strategy_def.key, symbol, signal.action,
                                       False, f"spread {spread_pct:.4%} too wide", signal.reason)
                    continue
                spec = ContractSpec(symbol, inst["taker_fee"], inst["maint_margin_rate"],
                                    inst["tick_size"], inst["lot_size"])
                ledger = self.db.strategy_ledger()[strategy_def.key]
                plan = plan_entry(signal.action, float(entry_quote), signal.atr, spec,
                                  self.cfg, equity=self.equity(marks),
                                  available_margin=ledger["cash_usd"],
                                  risk_budget_usd=self.cfg.max_risk_per_trade_usd,
                                  with_target=False)
                if not plan.ok:
                    self.db.log_signal(now_ms, strategy_def.key, symbol, signal.action,
                                       False, plan.reason, signal.reason)
                    continue
                planned = {"symbol": symbol, "strategy": strategy_def.key,
                           "planned_risk_usd": plan.planned_risk_usd,
                           "margin_usd": plan.margin_usd,
                           "entry_fee_usd": plan.entry_fee_usd}
                verdict = self.governor.approve(planned, now_ms, log=True,
                                                action=signal.action)
                if verdict.approved:
                    self.open_from_plan(inst, plan, strategy_def.key, signal.reason,
                                        signal.indicators, latest_bar, now_ms)
                    summary["opened"] += 1
                    break  # one entry per symbol per cycle
        # ---- pass 3: equity, HWM, breach handling ----
        positions = self.db.open_positions()
        if positions and summary["quotes_ok"] == 0:
            self.db.audit("warning", "data",
                          "equity snapshot skipped: no fresh quotes; position values and "
                          "emergency exits cannot be verified this cycle", ts_ms=now_ms)
            if self.db.get("lab_locked"):
                self.emergency_exit_all(market, now_ms, summary)  # audits deferrals
        else:
            equity_now = self.equity(marks)
            state = self.governor.update_hwm(equity_now, now_ms)
            if self.db.get("lab_locked") and self.db.open_positions():
                self.emergency_exit_all(market, now_ms, summary)
                equity_now = self.equity(marks)
                state = self.governor.update_hwm(equity_now, now_ms)
            margin_used = sum(p["margin_usd"] for p in self.db.open_positions())
            self.db.record_equity(now_ms, equity_now, self.db.total_cash(), margin_used,
                                  equity_now - self.db.total_cash() - margin_used,
                                  state["peak_equity"], state["threshold"])
        self.db.set("marks", marks)
        self.db.set("last_scan_ms", now_ms)
        return summary
