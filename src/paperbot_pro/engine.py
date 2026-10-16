"""PaperBot Pro orchestration: scan -> approve -> SIMULATED execution.

Everything here mutates only the local SQLite simulation. Exits are always
monitored for open positions; new entries require, in order: a fresh closed
candle, a generated signal, a solvent plan, the auto-entry gate (settings
flag AND validation artifact), and the RiskGovernor's approval. Every
decision is persisted.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from paperbot.models import Candle
from .config import ProSettings
from .marketdata import MarketData, shared_marketdata
from .perp import (ContractSpec, PlannedEntry, check_exit, funding_cost,
                   plan_entry, unrealized_pnl)
from .risk import RiskGovernor
from .scanner import StrategyParams, generate_signal

FUNDING_INTERVAL_MS = 8 * 3_600_000  # 00:00 / 08:00 / 16:00 UTC


class ProEngine:
    def __init__(self, store, cfg: ProSettings, market: MarketData | None = None,
                 params: StrategyParams | None = None):
        self.db = store
        self.cfg = cfg
        self.market = market
        self.params = params or StrategyParams()
        self.governor = RiskGovernor(store, cfg)

    # ---------------- gating ----------------
    def auto_entry_allowed(self) -> tuple[bool, str]:
        from .validation import auto_entry_gate
        return auto_entry_gate(self.cfg)

    # ---------------- position lifecycle ----------------
    def open_from_plan(self, spec: ContractSpec, plan: PlannedEntry, rationale: str,
                       indicator_snapshot: dict | None, bar_ts: int, now_ms: int,
                       sleeve: str) -> None:
        cash_key = "cash_core" if sleeve == "core" else "cash_hype"
        cash = float(self.db.get(cash_key))
        equity_ref = float(self.db.get("initial_balance"))
        with self.db.conn:
            self.db.conn.execute(
                """INSERT INTO positions(symbol, side, leverage, qty, entry_price,
                   margin_usd, notional_usd, stop, initial_stop, target, liq_price_est,
                   entry_fee_usd, funding_paid_usd, planned_risk_usd, planned_risk_pct,
                   mfe_price, mae_price, sleeve, opened_ms, signal_bar_ms, rationale,
                   indicator_snapshot) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (spec.symbol, plan.side, plan.leverage, plan.qty, plan.entry_price,
                 plan.margin_usd, plan.notional_usd, plan.stop, plan.stop, plan.target,
                 plan.liq_price_est, plan.entry_fee_usd, 0.0, plan.planned_risk_usd,
                 plan.planned_risk_usd / equity_ref, plan.entry_price, plan.entry_price,
                 sleeve, now_ms, bar_ts, rationale,
                 json.dumps(indicator_snapshot) if indicator_snapshot else None))
            self.db.conn.execute(
                "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (cash_key, json.dumps(cash - plan.margin_usd - plan.entry_fee_usd)))
        self.db.audit("info", "trade",
                      f"SIMULATED OPEN {plan.side} {spec.symbol} qty {plan.qty} @ "
                      f"{plan.entry_price:.6g}, stop {plan.stop:.6g}, target {plan.target:.6g}, "
                      f"liq est {plan.liq_price_est:.6g}, margin ${plan.margin_usd:.2f}", ts_ms=now_ms)

    def close_position(self, pos: dict, event, now_ms: int) -> None:
        sleeve = pos["sleeve"]
        cash_key = "cash_core" if sleeve == "core" else "cash_hype"
        cash = float(self.db.get(cash_key))
        if event.reason == "LIQUIDATION":
            credit = 0.0  # isolated margin wiped; fees/funding already paid
        else:
            credit = (pos["margin_usd"] + event.pnl_usd + pos["entry_fee_usd"]
                      + pos["funding_paid_usd"])
        entry = pos["entry_price"]
        sign = 1 if pos["side"] == "long" else -1
        mfe = (sign * (pos["mfe_price"] - entry) / entry * 100) if pos.get("mfe_price") else None
        mae = (sign * (pos["mae_price"] - entry) / entry * 100) if pos.get("mae_price") else None
        with self.db.conn:
            self.db.conn.execute(
                """INSERT INTO trades(symbol, side, leverage, qty, entry_price, exit_price,
                   stop_initial, stop_final, target, margin_usd, notional_usd, entry_fee_usd,
                   exit_fee_usd, funding_usd, net_pnl_usd, mfe_pct, mae_pct, entry_ms, exit_ms,
                   exit_reason, rationale, indicator_snapshot, sleeve)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pos["symbol"], pos["side"], pos["leverage"], pos["qty"], entry,
                 event.exit_price, pos["initial_stop"], pos["stop"], pos["target"],
                 pos["margin_usd"], pos["notional_usd"], pos["entry_fee_usd"],
                 event.exit_fee_usd, pos["funding_paid_usd"], event.pnl_usd, mfe, mae,
                 pos["opened_ms"], now_ms, event.reason, pos["rationale"],
                 pos.get("indicator_snapshot") if isinstance(pos.get("indicator_snapshot"), str)
                 else json.dumps(pos.get("indicator_snapshot")), sleeve))
            self.db.conn.execute("DELETE FROM positions WHERE id=?", (pos["id"],))
            self.db.conn.execute(
                "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (cash_key, json.dumps(cash + credit)))
            if sleeve == "hype" and event.pnl_usd < 0:
                loss = float(self.db.get("hype_cumulative_loss_usd", 0.0)) - event.pnl_usd
                self.db.conn.execute(
                    "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("hype_cumulative_loss_usd", json.dumps(loss)))
        self.db.set(f"last_exit:{pos['symbol']}", now_ms)  # re-entry cooldown anchor
        self.db.audit("warning" if event.pnl_usd < 0 else "info", "trade",
                      f"SIMULATED EXIT ({event.reason}) {pos['symbol']} @ "
                      f"{event.exit_price:.6g}; net P&L {event.pnl_usd:+.2f}", ts_ms=now_ms)

    def apply_funding_due(self, pos: dict, now_ms: int, rate: float | None,
                          mark: float) -> int:
        """Apply funding for each 8h boundary since the position's OWN anchor
        (its latest applied funding event, else its open time). Outages and
        restarts therefore retro-charge every missed boundary exactly once —
        idempotent via the funding_events primary key. Uses the currently
        observed rate for all pending boundaries (approximation: historical
        per-boundary rates are not refetched)."""
        if rate is None:
            self.db.audit("warning", "data",
                          f"funding rate unavailable for {pos['symbol']}; "
                          "funding NOT applied this window", ts_ms=now_ms)
            return 0
        row = self.db.conn.execute(
            "SELECT MAX(funding_ts_ms) FROM funding_events WHERE position_id=?",
            (pos["id"],)).fetchone()
        anchor_ms = row[0] if row and row[0] is not None else pos["opened_ms"]
        first = (anchor_ms // FUNDING_INTERVAL_MS + 1) * FUNDING_INTERVAL_MS
        applied = 0
        boundary = first
        cash_key = "cash_core" if pos["sleeve"] == "core" else "cash_hype"
        while boundary <= now_ms:
            amount = funding_cost(pos["side"], rate, mark, pos["qty"])
            with self.db.conn:
                inserted = self.db.conn.execute(
                    "INSERT OR IGNORE INTO funding_events VALUES(?,?,?,?)",
                    (pos["id"], boundary, rate, amount)).rowcount
                if inserted:
                    cash = float(self.db.get(cash_key))
                    self.db.conn.execute(
                        "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (cash_key, json.dumps(cash - amount)))
                    self.db.conn.execute(
                        "UPDATE positions SET funding_paid_usd = funding_paid_usd + ? WHERE id=?",
                        (amount, pos["id"]))
                    applied += 1
            boundary += FUNDING_INTERVAL_MS
        if applied:
            pos.update(self.db.position(pos["symbol"]) or {})
        return applied

    # ---------------- scan cycle ----------------
    def equity(self, marks: dict[str, float]) -> float:
        total = float(self.db.get("cash_core")) + float(self.db.get("cash_hype"))
        for p in self.db.open_positions():
            total += p["margin_usd"]
            mark = marks.get(p["symbol"])
            if mark is not None:
                total += unrealized_pnl(p["side"], p["entry_price"], mark, p["qty"])
        return total

    def _manage_open_positions(self, market, now_ms: int,
                               marks: dict, summary: dict) -> None:
        """Monitor EVERY open position, independent of current universe
        membership or eligibility: a coin dropping out of the top-20 must
        never orphan its stop/liquidation monitoring (review finding C1)."""
        for pos in self.db.open_positions():
            meta = self.db.conn.execute(
                "SELECT exchange, taker_fee FROM instruments WHERE symbol=?",
                (pos["symbol"],)).fetchone()
            if meta is None:
                summary["errors"] += 1
                self.db.audit("error", "risk",
                              f"POSITION UNMONITORED: no instrument metadata for "
                              f"{pos['symbol']}; cannot price exits — manual attention needed",
                              ts_ms=now_ms)
                continue
            try:
                ticker, tick_age = market.ticker(meta["exchange"], pos["symbol"])
            except Exception as exc:
                summary["errors"] += 1
                self.db.audit("error", "risk",
                              f"POSITION UNMONITORED this tick: {pos['symbol']} quote failed "
                              f"({type(exc).__name__}: {exc})", ts_ms=now_ms)
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
                              f"{pos['symbol']}: exit checks using STALE quote "
                              f"({tick_age:.0f}s old)", ts_ms=now_ms)
            marks[pos["symbol"]] = float(last)
            try:
                funding, _ = market.funding_rate(meta["exchange"], pos["symbol"])
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
            event = check_exit(pos, observed, self.cfg, meta["taker_fee"])
            if event is not None:
                self.close_position(pos, event, now_ms)
                summary["closed"] += 1

    def run_cycle(self, now_ms: int | None = None) -> dict:
        """One bounded pass: manage ALL open positions first, then scan the
        eligible universe for new signals. Returns a summary."""
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        market = self.market or shared_marketdata(self.cfg)
        instruments = [dict(r) for r in self.db.conn.execute(
            "SELECT i.*, u.coingecko_id AS cg FROM instruments i "
            "JOIN universe u ON u.coingecko_id = i.coingecko_id "
            "WHERE i.eligible=1 ORDER BY u.rank")]
        marks: dict[str, float] = dict(self.db.get("marks", {}) or {})
        indicators: dict[str, dict] = {}
        sources_ok, sources_fail = 0, 0
        summary = {"scanned": 0, "signals": 0, "opened": 0, "closed": 0, "errors": 0}
        self._manage_open_positions(market, now_ms, marks, summary)
        for inst in instruments:
            symbol, exchange = inst["symbol"], inst["exchange"]
            try:
                raw, candle_age = market.candles(exchange, symbol, self.cfg.candle_timeframe, 200)
                ticker, tick_age = market.ticker(exchange, symbol)
                sources_ok += 1
            except Exception as exc:
                sources_fail += 1
                summary["errors"] += 1
                self.db.audit("error", "data",
                              f"{symbol}: market data unavailable, symbol skipped "
                              f"(open stop unmonitored this tick): {type(exc).__name__}: {exc}",
                              ts_ms=now_ms)
                continue
            bars = [Candle(int(x[0]), *[float(v) for v in x[1:6]]) for x in raw]
            closed = [b for b in bars if b.timestamp + self.cfg.timeframe_ms <= now_ms]
            bid = ticker.get("bid")
            ask = ticker.get("ask")
            last = ticker.get("last") or (bid and ask and (bid + ask) / 2)
            if not closed or last is None:
                summary["errors"] += 1
                self.db.audit("warning", "data", f"{symbol}: incomplete candle/quote data; skipped",
                              ts_ms=now_ms)
                continue
            marks[symbol] = float(last)
            spread_pct = ((ask - bid) / ask) if (bid and ask and ask > 0) else None
            # ------- signal generation on NEW closed bar only -------
            latest_bar = closed[-1].timestamp
            seen_key = f"last_signal_bar:{symbol}"
            signal = generate_signal(closed, self.params)
            indicators[inst["cg"]] = {
                "trend": "up" if signal.indicators.get("ema20", 0) > signal.indicators.get("ema50", 0)
                         else "down" if signal.indicators else "flat",
                "rsi": signal.indicators.get("rsi"),
                "atr_pct": (signal.atr / float(last) * 100) if signal.atr else None,
                "signal": signal.action, "mark_price": float(last),
                "funding_rate": None, "spread_pct": spread_pct * 100 if spread_pct else None,
                "data_age_s": candle_age,
            }
            summary["scanned"] += 1
            if signal.action is None or self.db.get(seen_key) == latest_bar:
                continue
            self.db.set(seen_key, latest_bar)
            summary["signals"] += 1
            last_exit = self.db.get(f"last_exit:{symbol}")
            if last_exit is not None and latest_bar + self.cfg.timeframe_ms <= last_exit:
                # Backtest parity: the signal bar was already in progress (or
                # closed) when the last exit happened — no same-bar revenge
                # re-entry; wait for a bar that closes after the exit.
                self.db.log_signal(now_ms, symbol, signal.action, False,
                                   "re-entry cooldown: signal bar closed before the last exit",
                                   signal.reason)
                continue
            if tick_age > self.cfg.price_fresh_seconds:
                self.db.log_signal(now_ms, symbol, signal.action, False,
                                   f"quote stale ({tick_age:.0f}s old): no entry on stale data",
                                   signal.reason)
                continue
            entry_quote = ask if signal.action == "long" else bid
            if entry_quote is None or spread_pct is None:
                self.db.log_signal(now_ms, symbol, signal.action, False,
                                   "quote missing bid/ask side: no entry", signal.reason)
                continue
            if spread_pct > self.cfg.max_spread_pct:
                self.db.log_signal(now_ms, symbol, signal.action, False,
                                   f"spread {spread_pct:.4%} too wide", signal.reason)
                continue
            allowed, gate_reason = self.auto_entry_allowed()
            if not allowed:
                self.db.log_signal(now_ms, symbol, signal.action, False,
                                   f"execution gated: {gate_reason}", signal.reason)
                continue
            spec = ContractSpec(symbol, inst["taker_fee"], inst["maint_margin_rate"],
                                inst["tick_size"], inst["lot_size"])
            equity_now = self.equity(marks)
            plan = plan_entry(signal.action, float(entry_quote),
                              signal.atr, spec, self.cfg, equity_now,
                              float(self.db.get("cash_core")), self.cfg.risk_per_trade)
            if not plan.ok:
                self.db.log_signal(now_ms, symbol, signal.action, False, plan.reason, signal.reason)
                continue
            planned = {"symbol": symbol, "planned_risk_usd": plan.planned_risk_usd,
                       "margin_usd": plan.margin_usd, "entry_fee_usd": plan.entry_fee_usd,
                       "sleeve": "core"}
            verdict = self.governor.approve(planned, equity_now, now_ms,
                                            symbol_action=(symbol, signal.action))
            if verdict.approved:
                self.open_from_plan(spec, plan, signal.reason, signal.indicators,
                                    latest_bar, now_ms, "core")
                summary["opened"] += 1
        # ------- portfolio bookkeeping -------
        equity_now = self.equity(marks)
        self.governor.update_locks(equity_now, now_ms)
        positions = self.db.open_positions()
        margin_used = sum(p["margin_usd"] for p in positions)
        unreal = equity_now - float(self.db.get("cash_core")) - float(self.db.get("cash_hype")) - margin_used
        self.db.record_equity(now_ms, equity_now, float(self.db.get("cash_core")),
                              float(self.db.get("cash_hype")), margin_used, unreal)
        self.db.set("marks", marks)
        self.db.set("asset_indicators", indicators)
        self.db.set("last_scan_ms", now_ms)
        self.db.set("data_sources", [
            {"name": "exchange market data", "ok": sources_fail == 0,
             "last_ok_ms": now_ms if sources_ok else None,
             "detail": f"{sources_ok} ok / {sources_fail} failed this cycle"}])
        return summary
