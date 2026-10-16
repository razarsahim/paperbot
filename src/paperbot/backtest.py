from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from statistics import mean
from .config import Settings
from .models import Candle
from .strategy import evaluate, atr


@dataclass
class TestTrade:
    entry_ts: int
    exit_ts: int
    entry_price: float
    exit_price: float
    qty: float
    net_pnl: float
    reason: str


@dataclass
class TestResult:
    initial_cash: float
    final_equity: float
    net_return_pct: float
    max_drawdown_pct: float
    trades: list[TestTrade]
    win_rate_pct: float
    profit_factor: float | None
    expectancy: float | None
    still_open: bool
    lock_triggered: bool

    def summary(self) -> dict:
        result = asdict(self)
        result["number_of_closed_trades"] = len(self.trades)
        result["trades"] = [asdict(t) for t in self.trades]
        return result


def backtest(bars: list[Candle], cfg: Settings) -> TestResult:
    """Single-pass, next-bar-open fills and conservative candle-based stop priority.

    Not a realistic substitute for ticks, order book, outage modeling or a live
    strategy. If both target and stop fall within one candle, STOP wins.
    """
    cfg.validate()
    if len(bars) < cfg.min_bars + 2:
        raise ValueError(f"Need at least {cfg.min_bars + 2} candles")
    for bar in bars:
        bar.validate()
    if any(b.timestamp - a.timestamp != cfg.timeframe_ms for a, b in zip(bars, bars[1:])):
        raise ValueError("Missing / irregular candles: cannot backtest")
    balance = cfg.starting_balance
    peak, max_dd = balance, 0.0
    position = None
    trades: list[TestTrade] = []
    day = ""
    day_start = balance
    locked = False
    for i in range(cfg.min_bars, len(bars)):
        bar = bars[i]
        new_day = datetime.fromtimestamp(bar.timestamp / 1000, timezone.utc).strftime("%Y-%m-%d")
        if new_day != day:
            day = new_day
            day_start = balance + (position["qty"] * bar.open if position else 0)
        exited = False
        if position:
            # Overnight gaps are filled no better than the new candle open.
            if bar.open <= position["stop"]:
                raw_exit, reason = bar.open, "STOP_GAP"
            elif bar.low <= position["stop"]:
                raw_exit, reason = position["stop"], "STOP"
            elif bar.open >= position["target"] or bar.high >= position["target"]:
                raw_exit, reason = position["target"], "TARGET"
            else:
                raw_exit, reason = None, ""
            if raw_exit is not None:
                exit_fill = raw_exit * (1 - cfg.slippage_rate - cfg.max_spread_pct / 10)
                proceeds = exit_fill * position["qty"]
                exit_fee = proceeds * cfg.fee_rate
                balance += proceeds - exit_fee
                pnl = proceeds - exit_fee - position["cost"]
                trades.append(TestTrade(position["entry_ts"], bar.timestamp, position["entry"],
                                        exit_fill, position["qty"], pnl, reason))
                position = None
                exited = True
        if position:
            # Trailing stop updates AFTER bar resolution; cannot alter this bar's exit.
            if bar.close >= position["entry"] + position["initial_r"]:
                latest_atr = atr(bars[:i + 1])[-1]
                if latest_atr:
                    position["stop"] = max(position["stop"], position["entry"],
                                           bar.close - cfg.atr_stop_multiplier * latest_atr)
        equity = balance + (position["qty"] * bar.close if position else 0)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        if equity <= peak * (1 - cfg.max_total_drawdown):
            locked = True
        daily_locked = equity <= day_start * (1 - cfg.max_daily_drawdown)
        if position or exited or locked or daily_locked:
            continue
        # Signal uses history through candle i-1 only. Never use bar[i]'s close.
        signal = evaluate(bars[:i])
        if not signal.buy:
            continue
        ask = bar.open * (1 + cfg.max_spread_pct / 10)
        fill = ask * (1 + cfg.slippage_rate)
        stop = fill - cfg.atr_stop_multiplier * signal.atr
        if stop <= 0:
            continue
        loss_per_unit = fill * (1 + cfg.fee_rate) - stop * (1 - cfg.slippage_rate) * (1 - cfg.fee_rate)
        if loss_per_unit <= 0:
            continue
        qty = min(equity * cfg.risk_per_trade / loss_per_unit,
                  balance / (fill * (1 + cfg.fee_rate)))
        if qty * fill < 1:
            continue
        cost = qty * fill * (1 + cfg.fee_rate)
        balance -= cost
        position = {"entry_ts": bar.timestamp, "entry": fill, "qty": qty,
                    "cost": cost, "stop": stop, "target": fill + cfg.reward_risk * (fill - stop),
                    "initial_r": fill - stop}
        # The entry happens at bar OPEN, and the newly entered position must be
        # evaluated against this candle's full intrabar low/high as well.
        # Rather than reading into the future when opening, the next loop would
        # miss this candle's risk; resolve same-candle exits conservatively here.
        if bar.low <= stop:
            raw_exit = min(bar.open, stop)
            exit_fill = raw_exit * (1 - cfg.slippage_rate - cfg.max_spread_pct / 10)
            proceeds = exit_fill * qty
            fee = proceeds * cfg.fee_rate
            balance += proceeds - fee
            trades.append(TestTrade(bar.timestamp, bar.timestamp, fill, exit_fill,
                                    qty, proceeds - fee - cost, "STOP_ENTRY_BAR"))
            position = None
        elif bar.high >= position["target"]:
            raw_exit = position["target"]
            exit_fill = raw_exit * (1 - cfg.slippage_rate - cfg.max_spread_pct / 10)
            proceeds = exit_fill * qty
            fee = proceeds * cfg.fee_rate
            balance += proceeds - fee
            trades.append(TestTrade(bar.timestamp, bar.timestamp, fill, exit_fill,
                                    qty, proceeds - fee - cost, "TARGET_ENTRY_BAR"))
            position = None
        # Entry-bar cost and possible entry-bar stop/target must count towards
        # equity drawdown; the first mark-to-market above predates entry.
        equity_after_entry_bar = balance + (position["qty"] * bar.close if position else 0)
        peak = max(peak, equity_after_entry_bar)
        max_dd = max(max_dd, (peak - equity_after_entry_bar) / peak)
        if equity_after_entry_bar <= peak * (1 - cfg.max_total_drawdown):
            locked = True
    final = balance + (position["qty"] * bars[-1].close if position else 0)
    peak = max(peak, final)
    max_dd = max(max_dd, (peak - final) / peak)
    winners = [t.net_pnl for t in trades if t.net_pnl > 0]
    losers = [t.net_pnl for t in trades if t.net_pnl < 0]
    pf = sum(winners) / abs(sum(losers)) if losers else None
    return TestResult(cfg.starting_balance, final, (final / cfg.starting_balance - 1) * 100,
                      max_dd * 100, trades, len(winners) / len(trades) * 100 if trades else 0,
                      pf, mean(t.net_pnl for t in trades) if trades else None,
                      position is not None, locked)
