"""Pure reporting helpers shared by the dashboard. Read-only: no orders."""
from __future__ import annotations
from statistics import mean


def trade_stats(trades: list[dict]) -> dict:
    """Realized-trade statistics. Diagnostics only, not performance claims."""
    pnls = [float(t["net_pnl"]) for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    hold_hours = [(t["exit_ms"] - t["entry_ms"]) / 3_600_000 for t in trades]
    return {
        "closed_trades": len(trades),
        "win_rate_pct": len(winners) / len(trades) * 100 if trades else None,
        "profit_factor": sum(winners) / abs(sum(losers)) if losers else None,
        "expectancy": mean(pnls) if pnls else None,
        "total_net_pnl": sum(pnls),
        "largest_win": max(pnls) if pnls else None,
        "largest_loss": min(pnls) if pnls else None,
        "average_hold_hours": mean(hold_hours) if hold_hours else None,
    }


def drawdown_series(rows: list[dict]) -> list[float]:
    """Percent drawdown from the running equity peak; 0.0 at new highs."""
    peak = float("-inf")
    out = []
    for row in rows:
        equity = float(row["equity"])
        peak = max(peak, equity)
        out.append((equity - peak) / peak * 100 if peak > 0 else 0.0)
    return out
