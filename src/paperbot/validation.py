"""Walk-forward (rolling out-of-sample) evaluation with FROZEN parameters.

Strategy parameters are never fitted here: each chronological window is
scored out-of-sample with only the warmup history that preceded it, and is
compared against buy-and-hold (with round-trip costs) and the implicit
no-trade baseline of 0%. Results are research diagnostics, NOT evidence of
future profitability.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from statistics import mean, median
from .backtest import backtest, TestTrade
from .config import Settings
from .models import Candle


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


@dataclass
class WindowResult:
    index: int
    start_ms: int
    end_ms: int
    start_utc: str
    end_utc: str
    bars: int
    trades: list[TestTrade]
    net_return_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    profit_factor: float | None
    buy_hold_return_pct: float
    lock_triggered: bool
    still_open: bool


@dataclass
class WalkForwardResult:
    windows: list[WindowResult]
    total_trades: int
    mean_window_return_pct: float
    median_window_return_pct: float
    windows_beating_buy_hold: int
    windows_profitable: int
    warnings: list[str]

    def summary(self) -> dict:
        result = asdict(self)
        for w, src in zip(result["windows"], self.windows):
            w["number_of_trades"] = len(src.trades)
            del w["trades"]
        return result


def walk_forward(bars: list[Candle], cfg: Settings, n_windows: int = 4,
                 min_window_bars: int = 100) -> WalkForwardResult:
    """Split history into n chronological, non-overlapping test windows.

    Each window's backtest sees exactly cfg.min_bars of warmup history before
    its first tradable bar, so signals never read ahead of the window. Every
    window restarts from cfg.starting_balance: windows are independent
    out-of-sample samples, not a compounded account path.
    """
    cfg.validate()
    if n_windows < 2:
        raise ValueError("Walk-forward needs at least 2 windows")
    warmup = cfg.min_bars
    usable = len(bars) - warmup
    window_len = usable // n_windows
    if window_len < min_window_bars:
        raise ValueError(
            f"Not enough data: {len(bars)} bars gives {window_len} bars/window; "
            f"need >= {min_window_bars} per window after {warmup} warmup bars")
    windows: list[WindowResult] = []
    for k in range(n_windows):
        seg_start = warmup + k * window_len
        seg_end = seg_start + window_len
        segment = bars[seg_start:seg_end]
        result = backtest(bars[seg_start - warmup:seg_end], cfg)
        # Buy-and-hold pays entry at the window's first open and exits at its
        # last close, charged fees and slippage both ways.
        entry = segment[0].open * (1 + cfg.fee_rate + cfg.slippage_rate)
        exit_ = segment[-1].close * (1 - cfg.fee_rate - cfg.slippage_rate)
        windows.append(WindowResult(
            index=k, start_ms=segment[0].timestamp, end_ms=segment[-1].timestamp,
            start_utc=_iso(segment[0].timestamp), end_utc=_iso(segment[-1].timestamp),
            bars=len(segment), trades=result.trades,
            net_return_pct=result.net_return_pct,
            max_drawdown_pct=result.max_drawdown_pct,
            win_rate_pct=result.win_rate_pct, profit_factor=result.profit_factor,
            buy_hold_return_pct=(exit_ / entry - 1) * 100,
            lock_triggered=result.lock_triggered, still_open=result.still_open))
    dropped = usable - n_windows * window_len
    total_trades = sum(len(w.trades) for w in windows)
    returns = [w.net_return_pct for w in windows]
    warnings = ["Frozen-parameter walk-forward on historical candles: an "
                "approximation and not evidence of future profitability."]
    if total_trades < 30:
        warnings.append(f"Small sample: only {total_trades} closed trades across "
                        f"{n_windows} windows; statistics are unreliable.")
    if dropped:
        warnings.append(f"{dropped} most-recent bars dropped to keep windows equal.")
    if any(w.still_open for w in windows):
        warnings.append("Some windows ended with an open position (marked at last close).")
    if any(w.lock_triggered for w in windows):
        warnings.append("Drawdown lock triggered inside at least one window.")
    return WalkForwardResult(
        windows=windows, total_trades=total_trades,
        mean_window_return_pct=mean(returns),
        median_window_return_pct=median(returns),
        windows_beating_buy_hold=sum(
            1 for w in windows if w.net_return_pct > w.buy_hold_return_pct),
        windows_profitable=sum(1 for w in windows if w.net_return_pct > 0),
        warnings=warnings)
