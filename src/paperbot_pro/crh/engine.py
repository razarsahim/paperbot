"""Event-driven CRH replay that reproduces the live LabEngine cycle exactly.

The live engine runs one cycle per minute (at minute + 5 s). Per cycle it:
  0. (replay harness) checks stops/liquidation on the just-completed 1m bar
     the way WebSocket ticks would have;
  1. monitors every open position on the current quote (funding at 8h
     boundaries, MFE/MAE, stop/liquidation);
  2. applies per-strategy loss locks (none for the deployed CRH sleeve);
  3. for every universe instrument: trails the stop of an open position on
     the latest CLOSED signal candle, or evaluates the signal on the last
     199 closed candles and, if it fires, sizes/approves/opens an entry;
  4. marks equity, ratchets the high-water mark, locks on a trailing-drawdown
     breach and emergency-exits at observed quotes.

Signals can only change when a signal candle closes, and steps 0/1/4 only
matter while a position is open. So this engine walks the timeline by signal
candle and drops to 1-minute resolution only while positions are open. Every
formula is imported from perp.py / the deployed evaluator, never re-derived;
tests prove trade-for-trade equivalence with the original minute loop.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import numpy as np

from paperbot.models import Candle
from paperbot.strategy import atr as atr_series
from ..perp import (ContractSpec, ExitEvent, check_exit, funding_cost, plan_entry,
                    realized_pnl, trail_stop, unrealized_pnl)
from .config import CRHConfig

MIN_MS = 60_000


# ----------------------------------------------------------------- data model
@dataclass
class SymbolFrame:
    """Everything the engine needs for one instrument. Arrays are ascending."""
    symbol: str                     # ccxt id, e.g. "ZEC/USDT:USDT"
    spec: ContractSpec
    sig_ts: np.ndarray              # signal-timeframe bar open times (int64 ms)
    sig_ohlcv: np.ndarray           # (n, 5) float64 open, high, low, close, volume
    m1_ts: np.ndarray               # 1m bar open times
    m1_ohlc: np.ndarray             # (n, 4) open, high, low, close
    funding: list[tuple[int, float]] = field(default_factory=list)   # settled (ts, rate)
    # quotes: t -> (bid, ask, quote_ts); None when not loaded / unavailable
    quotes: Callable[[int], tuple[float, float, int] | None] | None = None

    def m1_index(self) -> dict[int, int]:
        if not hasattr(self, "_m1_idx"):
            self._m1_idx = {int(t): i for i, t in enumerate(self.m1_ts)}
        return self._m1_idx


class FrameProvider:
    """What the engine asks the data layer for."""
    def universe(self, day: str) -> list[str]:           # ccxt symbols, rank order
        raise NotImplementedError

    def frame(self, symbol: str) -> SymbolFrame | None:  # None => not eligible / no data
        raise NotImplementedError


# ------------------------------------------------------------- signal (baseline)
def crh_signal(window: list[Candle], cfg: CRHConfig, volatility: float):
    """Parameterised copy of lab.strategies._crash_reversal. With baseline
    parameters it is byte-for-byte the deployed logic (tests assert this)."""
    W = cfg.crash_window_bars
    if len(window) < W + 2:
        return None, "insufficient history", {}
    last = window[-1]
    ref = window[-(W + 1)].close
    drop_pct = (last.close / ref - 1) * 100
    body = abs(last.close - last.open)
    lower_wick = min(last.open, last.close) - last.low
    reversal = last.close > last.open and lower_wick > body
    ind = {"drop_24h_pct": round(drop_pct, 2), "reversal_candle": reversal}
    if drop_pct <= cfg.crash_drop_pct and (reversal or not cfg.require_hammer):
        return "long", f"{drop_pct:.1f}% {W}-bar drop with hammer reversal candle", ind
    if drop_pct <= cfg.crash_drop_pct:
        return None, f"{drop_pct:.1f}% drop but no reversal candle yet", ind
    return None, "no crash signature", ind


def prescan(frame: SymbolFrame, cfg: CRHConfig, t0: int, t1: int) -> list[dict]:
    """Vectorised candidate detection on the signal timeframe: every closed
    candle inside [t0, t1) whose drop + hammer conditions hold. No ATR here;
    the exact evaluator runs at these hours only."""
    W = cfg.crash_window_bars
    ts, o = frame.sig_ts, frame.sig_ohlcv
    tf = cfg.timeframe_ms
    n = len(ts)
    if n < W + 2:
        return []
    close, opn, low = o[:, 3], o[:, 0], o[:, 2]
    drop = np.full(n, np.nan)
    drop[W:] = (close[W:] / close[:-W] - 1.0) * 100.0
    body = np.abs(close - opn)
    lower_wick = np.minimum(opn, close) - low
    hammer = (close > opn) & (lower_wick > body)
    cond = drop <= cfg.crash_drop_pct
    if cfg.require_hammer:
        cond &= hammer
    idx = np.arange(n)
    # the engine needs >= min_bars closed bars and the candle must close in-window
    cond &= (idx + 1 >= max(cfg.min_bars, W + 2)) & (ts + tf >= t0) & (ts + tf < t1)
    out = []
    for i in np.nonzero(cond)[0]:
        out.append({"bar_ts": int(ts[i]), "close_ts": int(ts[i] + tf),
                    "drop_pct": float(drop[i]), "hammer": bool(hammer[i])})
    return out


def near_misses(frame: SymbolFrame, cfg: CRHConfig, t0: int, t1: int) -> list[dict]:
    """Closed candles where the drop condition held but the hammer did not."""
    W = cfg.crash_window_bars
    ts, o = frame.sig_ts, frame.sig_ohlcv
    n = len(ts)
    if n < W + 2:
        return []
    close, opn, low = o[:, 3], o[:, 0], o[:, 2]
    drop = np.full(n, np.nan)
    drop[W:] = (close[W:] / close[:-W] - 1.0) * 100.0
    hammer = (close > opn) & ((np.minimum(opn, close) - low) > np.abs(close - opn))
    tf = cfg.timeframe_ms
    cond = (drop <= cfg.crash_drop_pct) & ~hammer & (ts + tf >= t0) & (ts + tf < t1)
    return [{"bar_ts": int(ts[i]), "close_ts": int(ts[i] + tf), "drop_pct": float(drop[i])}
            for i in np.nonzero(cond)[0]]


# ------------------------------------------------------------------ the engine
@dataclass
class Position:
    id: int
    symbol: str
    side: str
    leverage: float
    qty: float
    entry_price: float
    margin_usd: float
    notional_usd: float
    stop: float
    initial_stop: float
    liq_price_est: float
    entry_fee_usd: float
    planned_risk_usd: float
    opened_ms: int
    signal_bar_ms: int
    rationale: str
    indicator_snapshot: dict
    taker_fee: float
    funding_paid_usd: float = 0.0
    mfe_price: float = 0.0
    mae_price: float = 0.0
    last_funding_ms: int | None = None
    target: None = None

    def as_dict(self) -> dict:
        return {"id": self.id, "symbol": self.symbol, "side": self.side, "leverage": self.leverage,
                "qty": self.qty, "entry_price": self.entry_price, "margin_usd": self.margin_usd,
                "notional_usd": self.notional_usd, "stop": self.stop,
                "initial_stop": self.initial_stop, "target": None,
                "liq_price_est": self.liq_price_est, "entry_fee_usd": self.entry_fee_usd,
                "funding_paid_usd": self.funding_paid_usd,
                "planned_risk_usd": self.planned_risk_usd, "mfe_price": self.mfe_price,
                "mae_price": self.mae_price, "opened_ms": self.opened_ms,
                "signal_bar_ms": self.signal_bar_ms, "rationale": self.rationale,
                "strategy": "crash_reversal"}


class CRHReplay:
    def __init__(self, cfg: CRHConfig, provider: FrameProvider, t0: int, t1: int,
                 progress: Callable[[str, float], None] | None = None,
                 cancelled: Callable[[], bool] | None = None):
        cfg.validate()
        self.cfg, self.provider, self.t0, self.t1 = cfg, provider, t0, t1
        self.progress = progress or (lambda stage, frac: None)
        self.cancelled = cancelled or (lambda: False)
        self.cash = cfg.starting_capital_usd
        self.positions: dict[str, Position] = {}
        self.trades: list[dict] = []
        self.signals: list[dict] = []
        self.risk_events: list[dict] = []
        self.warnings: list[str] = []
        self.equity_curve: list[list] = []       # [t, equity, cash, margin, unreal, peak, threshold]
        self.funding_events: list[dict] = []
        self.peak = cfg.starting_capital_usd
        self.locked = False
        self.lock_reason = None
        self.strategy_locked = False
        self.last_exit: dict[str, int] = {}
        self.seen: dict[str, int] = {}
        self.marks: dict[str, float] = {}
        self._next_id = 1
        self._frames: dict[str, SymbolFrame | None] = {}
        self._candidates: dict[str, dict[int, dict]] = {}   # symbol -> close_ts -> cand
        self.unmonitored = 0
        self.max_ts_served = 0
        self.n_cycles = 0

    # ------------------------------------------------------------ helpers
    def _frame(self, symbol: str) -> SymbolFrame | None:
        if symbol not in self._frames:
            self._frames[symbol] = self.provider.frame(symbol)
        return self._frames[symbol]

    def _day(self, t: int) -> str:
        return datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d")

    def _closed_window(self, fr: SymbolFrame, t: int) -> list[Candle]:
        """The signal candles a live scan at time t would call 'closed': the
        last (candle_limit - 1) bars whose close <= t (the engine fetches
        candle_limit bars, the newest of which is the forming bar)."""
        tf = self.cfg.timeframe_ms
        n_closed = self.cfg.candle_limit - (1 if self.cfg.signal_timeframe == "1h" else 0)
        j = int(np.searchsorted(fr.sig_ts, t - tf, side="right"))   # bars with ts <= t - tf
        lo = max(0, j - n_closed)
        rows = fr.sig_ohlcv[lo:j]
        tss = fr.sig_ts[lo:j]
        if j:
            self.max_ts_served = max(self.max_ts_served, int(tss[-1] + tf))
        return [Candle(int(tss[k]), *map(float, rows[k])) for k in range(len(tss))]

    def _last_trade(self, fr: SymbolFrame, t: int) -> float | None:
        j = int(np.searchsorted(fr.m1_ts, t - t % MIN_MS, side="left")) - 1
        if j < 0:
            return None
        self.max_ts_served = max(self.max_ts_served, int(fr.m1_ts[j]) + MIN_MS)
        return float(fr.m1_ohlc[j, 3])

    def _quote(self, fr: SymbolFrame, t: int):
        """(bid, ask, age_s) as of t, or None when the live engine would have
        had no usable ticker."""
        if self.cfg.fidelity == "approximate":
            i = fr.m1_index().get(t - t % MIN_MS)
            if i is None:
                return None
            mid = float(fr.m1_ohlc[i, 0])                 # first print of the minute
            hs = self.cfg.approx_half_spread
            return mid * (1 - hs), mid * (1 + hs), 0.0
        if fr.quotes is None:
            return None
        q = fr.quotes(t)
        if q is None:
            return None
        bid, ask, qts = q
        if qts > t:
            raise AssertionError(f"look-ahead: quote {qts} > now {t}")
        self.max_ts_served = max(self.max_ts_served, int(qts))
        return bid, ask, (t - qts) / 1000.0

    def _half_spread(self, fr: SymbolFrame, t: int) -> float:
        q = self._quote(fr, t)
        return 0.0 if q is None else (q[1] - q[0]) / 2.0

    def _funding_rate(self, fr: SymbolFrame, t: int) -> float | None:
        rate = None
        for ts, r in fr.funding:            # small list; latest settled <= t
            if ts <= t:
                rate = r
            else:
                break
        return rate

    def _equity(self) -> tuple[float, float, float]:
        margin = sum(p.margin_usd for p in self.positions.values())
        unreal = 0.0
        for p in self.positions.values():
            m = self.marks.get(p.symbol)
            if m is not None:
                unreal += unrealized_pnl(p.side, p.entry_price, m, p.qty)
        return self.cash + margin + unreal, margin, unreal

    def _audit(self, t: int, level: str, msg: str):
        self.risk_events.append({"ts_ms": t, "level": level, "category": "risk", "message": msg})

    def _log_signal(self, t: int, symbol: str, approved: bool, reason: str | None, details: str):
        self.signals.append({"ts_ms": t, "strategy": "crash_reversal", "symbol": symbol,
                             "action": "long", "approved": approved, "reject_reason": reason,
                             "details": details})

    # ------------------------------------------------------- position lifecycle
    def _close(self, pos: Position, event: ExitEvent, t: int):
        if pos.symbol not in self.positions:
            return
        credit = 0.0 if event.reason == "LIQUIDATION" else (
            pos.margin_usd + event.pnl_usd + pos.entry_fee_usd + pos.funding_paid_usd)
        sign = 1 if pos.side == "long" else -1
        e = pos.entry_price
        self.trades.append({
            "id": pos.id, "strategy": "crash_reversal", "symbol": pos.symbol, "side": pos.side,
            "leverage": pos.leverage, "qty": pos.qty, "entry_price": e,
            "exit_price": event.exit_price, "stop_initial": pos.initial_stop,
            "stop_final": pos.stop, "target": None, "margin_usd": pos.margin_usd,
            "notional_usd": pos.notional_usd, "entry_fee_usd": pos.entry_fee_usd,
            "exit_fee_usd": event.exit_fee_usd, "funding_usd": pos.funding_paid_usd,
            "net_pnl_usd": event.pnl_usd,
            "mfe_pct": sign * (pos.mfe_price - e) / e * 100 if pos.mfe_price else None,
            "mae_pct": sign * (pos.mae_price - e) / e * 100 if pos.mae_price else None,
            "entry_ms": pos.opened_ms, "exit_ms": t, "exit_reason": event.reason,
            "rationale": pos.rationale, "indicator_snapshot": pos.indicator_snapshot,
            "signal_bar_ms": pos.signal_bar_ms})
        del self.positions[pos.symbol]
        self.cash += credit
        self.last_exit[pos.symbol] = t
        self._audit(t, "warning" if event.pnl_usd < 0 else "info",
                    f"SIMULATED EXIT ({event.reason}) {pos.symbol} @ {event.exit_price:.6g}; "
                    f"net P&L {event.pnl_usd:+.2f}")

    def _force_exit(self, pos: Position, observed: float, t: int, label: str):
        event = check_exit(pos.as_dict(), observed, self.cfg, pos.taker_fee)
        if event is None:
            sign = 1 if pos.side == "long" else -1
            fill = observed * (1 - sign * self.cfg.slippage_rate)
            exit_fee = abs(fill * pos.qty * pos.taker_fee)
            pnl = realized_pnl(pos.side, pos.entry_price, fill, pos.qty, pos.entry_fee_usd,
                               exit_fee, pos.funding_paid_usd)
            event = ExitEvent(label, fill, pnl, exit_fee)
        self._close(pos, event, t)

    def _apply_funding(self, pos: Position, t: int, rate: float | None, mark: float):
        if rate is None:
            return
        anchor = pos.last_funding_ms if pos.last_funding_ms is not None else pos.opened_ms
        fi = self.cfg.funding_interval_ms
        boundary = (anchor // fi + 1) * fi
        while boundary <= t:
            amount = funding_cost(pos.side, rate, mark, pos.qty)
            self.cash -= amount
            pos.funding_paid_usd += amount
            pos.last_funding_ms = boundary
            self.funding_events.append({"position_id": pos.id, "symbol": pos.symbol,
                                        "funding_ts_ms": boundary, "rate": rate,
                                        "amount_usd": amount})
            boundary += fi

    # ------------------------------------------------------------ cycle steps
    def _tick_path(self, minute_start: int):
        """Stop/liquidation checks over the completed 1m bar [minute_start, +60s)."""
        bar_end = minute_start + MIN_MS
        for pos in list(self.positions.values()):
            fr = self._frame(pos.symbol)
            i = fr.m1_index().get(minute_start)
            if i is None or pos.opened_ms >= bar_end:
                continue
            self.max_ts_served = max(self.max_ts_served, bar_end)
            o, h, l = (float(x) for x in fr.m1_ohlc[i, :3])
            hs = self._half_spread(fr, minute_start + self.cfg.cycle_offset_ms)
            if pos.side == "long":
                first, worst = o - hs, l - hs
                if worst <= pos.liq_price_est:
                    observed = worst
                elif first <= pos.stop:
                    observed = first
                elif worst <= pos.stop:
                    observed = pos.stop
                else:
                    continue
            else:
                first, worst = o + hs, h + hs
                if worst >= pos.liq_price_est:
                    observed = worst
                elif first >= pos.stop:
                    observed = first
                elif worst >= pos.stop:
                    observed = pos.stop
                else:
                    continue
            event = check_exit(pos.as_dict(), observed, self.cfg, pos.taker_fee)
            if event is not None:
                self._close(pos, event, bar_end)

    def _monitor(self, t: int):
        for pos in list(self.positions.values()):
            fr = self._frame(pos.symbol)
            q = self._quote(fr, t)
            last = self._last_trade(fr, t)
            if q is None or last is None:
                self.unmonitored += 1
                continue
            bid, ask, age = q
            self.marks[pos.symbol] = last
            self._apply_funding(pos, t, self._funding_rate(fr, t), last)
            observed = bid if pos.side == "long" else ask
            sign = 1 if pos.side == "long" else -1
            if sign * observed > sign * pos.mfe_price:
                pos.mfe_price = observed
            if sign * observed < sign * pos.mae_price:
                pos.mae_price = observed
            event = check_exit(pos.as_dict(), observed, self.cfg, pos.taker_fee)
            if event is not None:
                self._close(pos, event, t)

    def _loss_trigger(self, t: int):
        trig = self.cfg.strategy_loss_trigger_usd
        if trig is None or self.strategy_locked:
            return
        equity, _, _ = self._equity()
        floor = self.cfg.starting_capital_usd - trig
        if equity <= floor:
            self.strategy_locked = True
            self._audit(t, "error", f"STRATEGY LOCKED: equity ${equity:.2f} <= ${floor:.2f} "
                                    f"floor (${trig:.0f} cumulative loss)")
            for pos in list(self.positions.values()):
                m = self.marks.get(pos.symbol)
                if m is not None:
                    self._force_exit(pos, float(m), t, "STRATEGY LOCK EXIT")

    def _scan(self, t: int, boundary: bool):
        cfg = self.cfg
        for symbol in self.provider.universe(self._day(t)):
            fr = self._frame(symbol)
            if fr is None:
                continue
            pos = self.positions.get(symbol)
            if pos is not None:
                if boundary:
                    closed = self._closed_window(fr, t)
                    if closed:
                        cur_atr = atr_series(closed, cfg.atr_period)[-1]
                        if cur_atr and cur_atr > 0:
                            pos.stop = trail_stop(pos.side, pos.stop, closed[-1].close, cur_atr,
                                                  cfg.trail_atr_multiplier)
                continue
            if not boundary:
                continue
            cands = self._candidates.get(symbol)
            if cands is None:
                cands = {c["close_ts"]: c for c in prescan(fr, cfg, self.t0, self.t1)}
                self._candidates[symbol] = cands
            latest_close = t - t % cfg.timeframe_ms
            if latest_close not in cands:
                continue
            closed = self._closed_window(fr, t)
            if len(closed) < cfg.min_bars:
                continue
            vol = atr_series(closed, cfg.atr_period)[-1]
            if not vol or vol <= 0:
                continue
            action, reason, ind = crh_signal(closed, cfg, vol)
            if action is None:       # cannot happen for a prescan candidate, kept for safety
                continue
            latest_bar = closed[-1].timestamp
            if self.seen.get(symbol) == latest_bar:
                continue
            self.seen[symbol] = latest_bar
            last_exit = self.last_exit.get(symbol)
            if last_exit is not None and latest_bar + cfg.timeframe_ms <= last_exit:
                self._log_signal(t, symbol, False, "re-entry cooldown", reason)
                continue
            q = self._quote(fr, t)
            if q is None:
                self.warnings.append(f"{symbol} @ {t}: no quote at signal time; the live "
                                     "engine would have skipped this scan (no entry)")
                self._log_signal(t, symbol, False, "market data unavailable at signal time", reason)
                continue
            bid, ask, age = q
            if age > cfg.price_fresh_seconds:
                self._log_signal(t, symbol, False, f"quote stale ({age:.0f}s)", reason)
                continue
            spread_pct = (ask - bid) / ask if ask > 0 else None
            if spread_pct is None:
                self._log_signal(t, symbol, False, "quote missing bid/ask side", reason)
                continue
            if spread_pct > cfg.max_spread_pct:
                self._log_signal(t, symbol, False, f"spread {spread_pct:.4%} too wide", reason)
                continue
            equity, _, _ = self._equity()
            plan = plan_entry("long", float(ask), vol, fr.spec, cfg, equity=equity,
                              available_margin=self.cash, risk_budget_usd=cfg.risk_per_trade_usd,
                              with_target=False)
            if not plan.ok:
                self._log_signal(t, symbol, False, plan.reason, reason)
                continue
            verdict = self._approve(symbol, plan)
            details = f"risk ${plan.planned_risk_usd:.2f}, margin ${plan.margin_usd:.2f}"
            if verdict is not None:
                self._log_signal(t, symbol, False, verdict, details)
                continue
            self._log_signal(t, symbol, True, None, details)
            pos = Position(self._next_id, symbol, "long", plan.leverage, plan.qty,
                           plan.entry_price, plan.margin_usd, plan.notional_usd, plan.stop,
                           plan.stop, plan.liq_price_est, plan.entry_fee_usd,
                           plan.planned_risk_usd, t, latest_bar, reason,
                           {**ind, "atr": vol, "drop_pct": ind.get("drop_24h_pct"),
                            "signal_close_ts": latest_close}, fr.spec.taker_fee,
                           mfe_price=plan.entry_price, mae_price=plan.entry_price)
            self._next_id += 1
            self.positions[symbol] = pos
            self.cash -= plan.margin_usd + plan.entry_fee_usd
            # the live scan marks every instrument it scans BEFORE evaluating it,
            # so a brand-new position already carries a mark this cycle
            last = self._last_trade(fr, t)
            if last is not None:
                self.marks[symbol] = last
            self._audit(t, "info", f"SIMULATED OPEN long {symbol} qty {plan.qty} @ "
                                   f"{plan.entry_price:.6g}, stop {plan.stop:.6g}, liq est "
                                   f"{plan.liq_price_est:.6g}, margin ${plan.margin_usd:.2f}")

    def _approve(self, symbol: str, plan) -> str | None:
        cfg = self.cfg
        if self.locked:
            return "Lab locked (trailing drawdown): manual reset required"
        if plan.planned_risk_usd > cfg.risk_per_trade_usd + 1e-9:
            return (f"planned risk ${plan.planned_risk_usd:.2f} exceeds the "
                    f"${cfg.risk_per_trade_usd:.0f} per-trade cap for this sleeve")
        if self.strategy_locked:
            return "crash_reversal is locked (equity floor / cumulative loss)"
        if symbol in self.positions:
            return f"{symbol} already open: no duplicates/averaging"
        if len(self.positions) >= cfg.max_open_positions:
            return f"position limit reached ({cfg.max_open_positions})"
        combined = sum(p.planned_risk_usd for p in self.positions.values()) + plan.planned_risk_usd
        if combined > cfg.max_combined_risk_usd + 1e-9:
            return (f"combined planned risk ${combined:.2f} exceeds the "
                    f"${cfg.max_combined_risk_usd:.0f} cap")
        needed = plan.margin_usd + plan.entry_fee_usd
        if needed > self.cash + 1e-9:
            return (f"insufficient strategy cash: need ${needed:.2f}, crash_reversal has "
                    f"${self.cash:.2f}")
        return None

    def _mark_and_lock(self, t: int):
        equity, margin, unreal = self._equity()
        self.peak = max(self.peak, equity)
        threshold = self.peak - self.cfg.trailing_drawdown_usd
        if equity <= threshold and not self.locked:
            self.locked = True
            self.lock_reason = (f"TRAILING DRAWDOWN BREACH: net equity {equity:.2f} <= threshold "
                                f"{threshold:.2f} (peak {self.peak:.2f} - "
                                f"{self.cfg.trailing_drawdown_usd:.0f})")
            self._audit(t, "error", self.lock_reason + " — all strategies locked; emergency "
                                    "exits will be attempted; manual reset required")
        if self.locked and self.positions:
            for pos in list(self.positions.values()):
                fr = self._frame(pos.symbol)
                q = self._quote(fr, t)
                if q is None:
                    self._audit(t, "error", f"EMERGENCY EXIT DEFERRED: {pos.symbol} has no "
                                            "quote; will retry")
                    continue
                observed = q[0] if pos.side == "long" else q[1]
                self._force_exit(pos, float(observed), t, "EMERGENCY (trailing drawdown)")
            equity, margin, unreal = self._equity()
            self.peak = max(self.peak, equity)
            threshold = self.peak - self.cfg.trailing_drawdown_usd
        self.equity_curve.append([t, equity, self.cash, margin, unreal, self.peak, threshold])

    def _cycle(self, M: int, boundary: bool):
        t = M + self.cfg.cycle_offset_ms
        if M > self.t0:
            self._tick_path(M - MIN_MS)
        self._monitor(t)
        self._loss_trigger(t)
        self._scan(t, boundary)
        self._mark_and_lock(t)
        self.n_cycles += 1

    # ------------------------------------------------------------------ run
    def run(self) -> dict:
        started = time.time()
        tf = self.cfg.timeframe_ms
        M = self.t0
        total = max(1, self.t1 - self.t0)
        last_report = -1.0
        while M < self.t1:
            boundary = (M % tf == 0)
            if self.positions or boundary:
                self._cycle(M, boundary)
            if self.cancelled():
                raise RuntimeError("cancelled")
            frac = (M - self.t0) / total
            if frac - last_report >= 0.02:
                self.progress("replay", frac)
                last_report = frac
            M += MIN_MS
        # final minute's price path, then mark-to-market the survivors
        self._tick_path(self.t1 - MIN_MS)
        open_at_end = []
        for pos in self.positions.values():
            fr = self._frame(pos.symbol)
            last = self._last_trade(fr, self.t1)
            self.marks[pos.symbol] = last if last is not None else self.marks.get(pos.symbol)
            d = pos.as_dict()
            d["mark"] = last
            d["unrealized_pnl_usd"] = (unrealized_pnl(pos.side, pos.entry_price, last, pos.qty)
                                       if last is not None else None)
            open_at_end.append(d)
        equity, margin, unreal = self._equity()
        self.equity_curve.append([self.t1, equity, self.cash, margin, unreal, self.peak,
                                  self.peak - self.cfg.trailing_drawdown_usd])
        self.progress("replay", 1.0)
        return {
            "label": "HISTORICAL BACKTEST — not live paper; not predictive",
            "config": self.cfg.__dict__.copy(),
            "config_fingerprint": self.cfg.fingerprint(),
            "fidelity": self.cfg.fidelity,
            "window_utc": {"start_ms": self.t0, "end_ms_exclusive": self.t1},
            "cycles": self.n_cycles, "elapsed_s": round(time.time() - started, 2),
            "trades": self.trades, "open_at_end": open_at_end, "signals": self.signals,
            "risk_events": self.risk_events, "funding_events": self.funding_events,
            "equity_curve": self.equity_curve,
            "final_cash": self.cash, "final_equity": equity, "peak_equity": self.peak,
            "locked": self.locked, "lock_reason": self.lock_reason,
            "strategy_locked": self.strategy_locked,
            "unmonitored_cycles": self.unmonitored,
            "warnings": self.warnings,
            "leakage_check": {"max_data_ts_served": self.max_ts_served,
                              "final_now": self.t1,
                              "ok": self.max_ts_served <= self.t1},
        }
