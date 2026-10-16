from __future__ import annotations
from datetime import datetime, timezone
from .config import Settings
from .models import Candle, Quote
from .store import Store
from .strategy import evaluate


class PaperEngine:
    """Only modifies virtual SQLite balances. Deliberately contains NO order API."""
    def __init__(self, store: Store, settings: Settings):
        settings.validate()
        self.db = store
        self.cfg = settings

    def equity(self, bid: float) -> float:
        pos = self.db.position()
        return float(self.db.get("balance")) + (float(pos["qty"]) * bid if pos else 0)

    def _lockouts(self, equity: float, now_ms: int) -> list[str]:
        today = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
        notices = []
        with self.db.conn:
            if self.db.get("utc_day") != today:
                self.db.set("utc_day", today)
                self.db.set("day_start_equity", equity)
                self.db.set("locked_daily", False)
            peak = max(float(self.db.get("peak_equity")), equity)
            self.db.set("peak_equity", peak)
            if equity <= peak * (1 - self.cfg.max_total_drawdown):
                self.db.set("locked_total", True)
            if self.db.get("locked_total"):
                notices.append("TOTAL DRAWDOWN LOCK: manual review required; no new positions")
            # Sticky for the rest of the UTC day even if equity later recovers.
            if equity <= float(self.db.get("day_start_equity")) * (1 - self.cfg.max_daily_drawdown):
                self.db.set("locked_daily", True)
            if self.db.get("locked_daily"):
                notices.append("DAILY DRAWDOWN LOCK: no entries until next UTC day")
        return notices

    def _exit(self, bid: float, now_ms: int, reason: str) -> str:
        pos = self.db.position()
        assert pos is not None
        fill = bid * (1 - self.cfg.slippage_rate)
        proceeds = pos["qty"] * fill
        exit_fee = proceeds * self.cfg.fee_rate
        pnl = proceeds - exit_fee - (pos["qty"] * pos["entry_price"] + pos["entry_fee"])
        with self.db.conn:
            self.db.set("balance", self.db.get("balance") + proceeds - exit_fee)
            self.db.conn.execute("""INSERT INTO trades(
                entry_ms,exit_ms,symbol,entry_price,exit_price,qty,entry_fee,exit_fee,
                net_pnl,exit_reason,signal_reason)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (
                    pos["entry_ms"], now_ms, self.cfg.symbol, pos["entry_price"], fill,
                    pos["qty"], pos["entry_fee"], exit_fee, pnl, reason, pos["reason"]
                ))
            self.db.conn.execute("DELETE FROM position WHERE id=1")
        return f"SIMULATED EXIT ({reason}) @ {fill:.2f}; net P&L {pnl:+.2f}"

    def _enter(self, ask: float, atr_value: float, now_ms: int, bar_ms: int, reason: str) -> str:
        fill = ask * (1 + self.cfg.slippage_rate)
        stop = fill - self.cfg.atr_stop_multiplier * atr_value
        if stop <= 0:
            return "SKIP: invalid ATR-derived stop"
        # Conservatively budget planned stop loss inclusive of both fees and adverse slippage.
        per_unit_loss = fill * (1 + self.cfg.fee_rate) - stop * (1 - self.cfg.slippage_rate) * (1 - self.cfg.fee_rate)
        if per_unit_loss <= 0:
            return "SKIP: invalid planned loss"
        balance = float(self.db.get("balance"))
        risk_budget = self.equity(ask) * self.cfg.risk_per_trade
        qty = min(risk_budget / per_unit_loss, balance / (fill * (1 + self.cfg.fee_rate)))
        if qty <= 0 or qty * fill < 1:
            return "SKIP: insufficient simulation balance"
        fee = qty * fill * self.cfg.fee_rate
        target = fill + self.cfg.reward_risk * (fill - stop)
        with self.db.conn:
            self.db.set("balance", balance - qty * fill - fee)
            self.db.conn.execute("""INSERT INTO position(
                id, entry_ms, entry_price, qty, entry_fee, stop, initial_stop, target,
                initial_r, signal_bar_ms, reason) VALUES(1,?,?,?,?,?,?,?,?,?,?)""", (
                    now_ms, fill, qty, fee, stop, stop, target, fill - stop, bar_ms, reason
                ))
        return f"SIMULATED BUY {qty:.8f} @ {fill:.2f}; stop {stop:.2f}; target {target:.2f}"

    def tick(self, closed_bars: list[Candle], quote: Quote, now_ms: int) -> list[str]:
        """Process quote and only the newest fully closed 1h candle.

        Stop/target monitoring always runs even when candle data is delayed. A new
        trade cannot open on old signals. On restarts, last_bar ensures no replay.
        Caller must keep this process single-instance (CLI uses an exclusive lock).
        """
        if not (0 < quote.bid <= quote.ask):
            raise ValueError("Invalid public market quote")
        spread_too_wide = (quote.ask - quote.bid) / quote.ask > self.cfg.max_spread_pct
        if now_ms - quote.observed_ms > self.cfg.price_fresh_seconds * 1000 or quote.observed_ms > now_ms + 5000:
            raise ValueError("Stale or future-dated quote")
        events = []
        if spread_too_wide:
            events.append("WIDE SPREAD: new entries disabled; existing paper exits use bid")
        exited_this_tick = False
        pos = self.db.position()
        if pos is not None:
            if quote.bid <= pos["stop"]:
                events.append(self._exit(quote.bid, now_ms, "STOP (gap/slippage possible)"))
                exited_this_tick = True
            elif quote.bid >= pos["target"]:
                events.append(self._exit(quote.bid, now_ms, "TARGET"))
                exited_this_tick = True
        equity_now = self.equity(quote.bid)
        locks = self._lockouts(equity_now, now_ms)
        events.extend(locks)
        pos_after_exits = self.db.position()
        with self.db.conn:
            self.db.record_equity(now_ms, quote.bid, equity_now, float(self.db.get("balance")),
                                  pos_after_exits["qty"] if pos_after_exits else 0.0)
        if len(closed_bars) < self.cfg.min_bars:
            events.append("NO SIGNAL: insufficient historical data")
            return events
        for b in closed_bars[-60:]:
            b.validate()
        for a, b in zip(closed_bars[-60:-1], closed_bars[-59:]):
            if b.timestamp - a.timestamp != self.cfg.timeframe_ms:
                events.append("NO SIGNAL: missing or irregular candles")
                return events
        bar = closed_bars[-1]
        close_ms = bar.timestamp + self.cfg.timeframe_ms
        if now_ms < close_ms:
            events.append("NO SIGNAL: supplied candle is still open")
            return events
        if self.db.get("last_bar_ms", -1) >= bar.timestamp:
            return events
        with self.db.conn:
            self.db.set("last_bar_ms", bar.timestamp)  # mark even if not eligible
        # Tighten stops only after a fully closed bar. Never widen the stop.
        pos = self.db.position()
        if pos:
            signal = evaluate(closed_bars)
            if signal.atr > 0 and bar.close >= pos["entry_price"] + pos["initial_r"]:
                tighter = max(pos["stop"], bar.close - self.cfg.atr_stop_multiplier * signal.atr,
                              pos["entry_price"])
                if tighter > pos["stop"]:
                    with self.db.conn:
                        self.db.conn.execute("UPDATE position SET stop=? WHERE id=1 AND stop<?", (tighter, tighter))
                    events.append(f"STOP TIGHTENED (never widened) to {tighter:.2f}")
            return events
        if now_ms - close_ms > self.cfg.entry_window_minutes * 60_000:
            events.append("NO SIGNAL: bar too old to enter responsibly")
            return events
        if locks or exited_this_tick or spread_too_wide:
            return events
        signal = evaluate(closed_bars)
        if signal.buy:
            events.append(self._enter(quote.ask, signal.atr, now_ms, bar.timestamp, signal.reason))
        else:
            events.append(f"HOLD: {signal.reason}")
        return events
