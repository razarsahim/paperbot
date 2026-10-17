"""Chronology-safe backtests for the Research Lab strategies, per strategy and
as a shared-capital walk-forward, with realistic costs (fees, slippage,
approximated funding, liquidation-first exits). Results are research
diagnostics — never validated or predictive. A final holdout slice is
reserved and never used for tuning (there is no tuning here: parameters are
frozen).
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from paperbot.models import Candle
from paperbot.strategy import atr, ema
from ..indicators import rsi
from ..perp import ContractSpec, funding_cost, plan_entry, realized_pnl
from .config import STRATEGIES, ResearchSettings
from .indicators import adx, bollinger, relative_volume
from .strategies import (ADX_RANGE_MAX, ADX_TREND_MIN, BREAKOUT_LOOKBACK,
                         RELVOL_MIN)

FUNDING_INTERVAL_MS = 8 * 3_600_000
FUNDING_RATE = 0.0001


def _htf_dir(ema_fast: list, i: int, lag: int) -> str:
    """Causal higher-timeframe proxy: EMA direction over the last `lag` bars."""
    if i - lag < 0 or ema_fast[i] is None or ema_fast[i - lag] is None:
        return "flat"
    return "up" if ema_fast[i] > ema_fast[i - lag] else "down"


def _signals_for(strategy: str, bars: list[Candle], cfg: ResearchSettings):
    """Causal per-bar (action, atr) using precomputed series. action[i] is the
    signal AT bar i (uses bars 0..i only); the engine enters at bar i+1 open."""
    n = len(bars)
    closes = [b.close for b in bars]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    e200 = ema(closes, min(200, max(2, n - 1)))
    a = adx(bars, 14)
    atr_s = atr(bars, 14)
    mid, upper, lower, width = bollinger(closes, 20, 2.0)
    rv = relative_volume(bars, 20)
    rsi_s = rsi(closes, 14)
    out = [(None, 0.0)] * n
    for i in range(cfg.min_bars, n):
        vol = atr_s[i]
        if not vol or vol <= 0:
            continue
        if strategy == "regime_trend":
            if a[i] is None or e50[i] is None or e200[i] is None or a[i] < ADX_TREND_MIN:
                continue
            htf = _htf_dir(e50, i, 12)
            if e50[i] > e200[i] and htf == "up" and closes[i] > e50[i]:
                out[i] = ("long", vol)
            elif e50[i] < e200[i] and htf == "down" and closes[i] < e50[i]:
                out[i] = ("short", vol)
        elif strategy == "volatility_breakout":
            if rv[i] is None or width[i] is None:
                continue
            recent = [w for w in width[max(0, i - 24):i] if w is not None]
            compressed = recent and width[i - 1] is not None and width[i - 1] <= min(recent) * 1.15
            falling = (atr_s[i - 1] is not None and atr_s[max(0, i - 5)] is not None
                       and atr_s[i - 1] < atr_s[max(0, i - 5)])
            if not (compressed or falling) or rv[i] < RELVOL_MIN:
                continue
            window = bars[max(0, i - BREAKOUT_LOOKBACK):i]
            hi, lo = max(b.high for b in window), min(b.low for b in window)
            if closes[i] > hi:
                out[i] = ("long", vol)
            elif closes[i] < lo:
                out[i] = ("short", vol)
        elif strategy == "trend_pullback":
            if e20[i] is None or e50[i] is None:
                continue
            htf = _htf_dir(e50, i, 8)
            if e20[i] > e50[i] and htf == "up" and closes[i - 1] <= e20[i - 1] and closes[i] > e20[i]:
                out[i] = ("long", vol)
            elif e20[i] < e50[i] and htf == "down" and closes[i - 1] >= e20[i - 1] and closes[i] < e20[i]:
                out[i] = ("short", vol)
        elif strategy == "range_reversion":
            if a[i] is None or upper[i] is None or a[i] >= ADX_RANGE_MAX:
                continue
            r = rsi_s[i]
            if bars[i].low < lower[i] and closes[i] > lower[i] and (r is None or r < 40):
                out[i] = ("long", vol)
            elif bars[i].high > upper[i] and closes[i] < upper[i] and (r is None or r > 60):
                out[i] = ("short", vol)
        # orderflow_imbalance: needs live order book, not candle-backtestable
    return out


def research_backtest(bars: list[Candle], cfg: ResearchSettings, spec: ContractSpec,
                      strategy: str) -> dict:
    if strategy == "orderflow_imbalance":
        return {"skipped": True, "reason": "requires live order book; not candle-backtestable",
                "trades": 0, "net_return_pct": 0.0, "trade_list": []}
    signals = _signals_for(strategy, bars, cfg)
    equity = cfg.allocation_per_strategy_usd
    peak, max_dd = equity, 0.0
    pos = None
    trades = []
    for i in range(cfg.min_bars, len(bars)):
        candle = bars[i]
        if pos is not None:
            boundary = (pos["last_funding"] // FUNDING_INTERVAL_MS + 1) * FUNDING_INTERVAL_MS
            while boundary <= candle.timestamp:
                pos["funding"] += funding_cost(pos["side"], FUNDING_RATE, candle.open, pos["qty"])
                boundary += FUNDING_INTERVAL_MS
            pos["last_funding"] = candle.timestamp
            side, sign = pos["side"], (1 if pos["side"] == "long" else -1)
            exit_price = reason = None
            if (side == "long" and candle.low <= pos["liq"]) or (side == "short" and candle.high >= pos["liq"]):
                exit_price, reason = pos["liq"], "LIQUIDATION"
            elif (side == "long" and candle.open <= pos["stop"]) or (side == "short" and candle.open >= pos["stop"]):
                exit_price, reason = candle.open, "STOP_GAP"
            elif (side == "long" and candle.low <= pos["stop"]) or (side == "short" and candle.high >= pos["stop"]):
                exit_price, reason = pos["stop"], "STOP"
            if exit_price is not None:
                if reason == "LIQUIDATION":
                    pnl = -(pos["margin"] + pos["entry_fee"] + max(pos["funding"], 0.0))
                    fill, fee = exit_price, 0.0
                else:
                    fill = exit_price * (1 - sign * cfg.slippage_rate)
                    fee = abs(fill * pos["qty"] * spec.taker_fee)
                    pnl = realized_pnl(side, pos["entry"], fill, pos["qty"],
                                       pos["entry_fee"], fee, pos["funding"])
                equity += pnl
                trades.append({"entry_ms": pos["entry_ms"], "exit_ms": candle.timestamp,
                               "side": side, "net_pnl_usd": pnl, "exit_reason": reason})
                pos = None
            else:
                # trailing stop on completed bar, never widens
                from ..perp import trail_stop
                if atr(bars[:i + 1], 14)[-1]:
                    pos["stop"] = trail_stop(side, pos["stop"], candle.close,
                                             atr(bars[:i + 1], 14)[-1], cfg.trail_atr_multiplier)
        peak = max(peak, equity); max_dd = max(max_dd, (peak - equity) / peak if peak else 0)
        if pos is not None:
            continue
        action, vol = signals[i - 1]   # previous bar's signal; enter at this open
        if action is None:
            continue
        plan = plan_entry(action, candle.open, vol, spec, cfg, equity=equity,
                          available_margin=equity * 0.9,
                          risk_budget_usd=cfg.max_risk_per_trade_usd, with_target=False)
        if not plan.ok:
            continue
        pos = {"side": action, "entry": plan.entry_price, "qty": plan.qty,
               "stop": plan.stop, "liq": plan.liq_price_est, "margin": plan.margin_usd,
               "entry_fee": plan.entry_fee_usd, "funding": 0.0,
               "entry_ms": candle.timestamp, "last_funding": candle.timestamp}
    if pos is not None:
        sign = 1 if pos["side"] == "long" else -1
        equity += sign * (bars[-1].close - pos["entry"]) * pos["qty"] - pos["entry_fee"] - pos["funding"]
    wins = [t for t in trades if t["net_pnl_usd"] > 0]
    losses = [t for t in trades if t["net_pnl_usd"] < 0]
    gl = abs(sum(t["net_pnl_usd"] for t in losses))
    return {"skipped": False, "trades": len(trades), "trade_list": trades,
            "final_equity": equity,
            "net_return_pct": (equity / cfg.allocation_per_strategy_usd - 1) * 100,
            "max_drawdown_pct": max_dd * 100,
            "win_rate_pct": (len(wins) / len(trades) * 100) if trades else None,
            "profit_factor": (sum(t["net_pnl_usd"] for t in wins) / gl) if gl else None}


def validate_strategies(data: dict[str, tuple[list[Candle], ContractSpec]],
                        cfg: ResearchSettings, n_windows: int = 3,
                        holdout_frac: float = 0.2) -> dict:
    """Per-strategy backtests across the provided markets plus a shared-capital
    walk-forward on the FIRST market, reserving a final holdout slice."""
    per_strategy = {}
    for sdef in STRATEGIES:
        agg = {"trades": 0, "net_return_pct": 0.0, "trade_list": [], "skipped": False,
               "markets": 0}
        for symbol, (bars, spec) in data.items():
            r = research_backtest(bars, cfg, spec, sdef.key)
            if r.get("skipped"):
                agg["skipped"] = True
                continue
            agg["trades"] += r["trades"]
            agg["net_return_pct"] += r["net_return_pct"]
            agg["trade_list"].extend(r["trade_list"])
            agg["markets"] += 1
        if agg["markets"]:
            agg["net_return_pct"] /= agg["markets"]
        per_strategy[sdef.key] = agg

    first_symbol = next(iter(data))
    bars, spec = data[first_symbol]
    holdout_start = int(len(bars) * (1 - holdout_frac))
    train = bars[:holdout_start]
    windows = []
    win_len = len(train) // n_windows
    for k in range(n_windows):
        seg = train[max(0, k * win_len - cfg.min_bars):(k + 1) * win_len]
        if len(seg) < cfg.min_bars + 50:
            continue
        rets = [research_backtest(seg, cfg, spec, s.key)["net_return_pct"]
                for s in STRATEGIES if s.key != "orderflow_imbalance"]
        windows.append({"index": k, "bars": (k + 1) * win_len - k * win_len,
                        "mean_strategy_return_pct": sum(rets) / len(rets) if rets else 0.0,
                        "start_utc": datetime.fromtimestamp(
                            seg[0].timestamp / 1000, timezone.utc).isoformat()})
    total_trades = sum(s["trades"] for s in per_strategy.values())
    profitable = sum(1 for s in per_strategy.values()
                     if not s["skipped"] and s["net_return_pct"] > 0)
    warnings = [
        "Research-strategy backtest with modeled fees, slippage, funding and "
        "liquidation-first exits — an approximation, NOT evidence of future "
        "profitability and not predictive.",
        "Strategy parameters are FROZEN; no optimization against any window.",
        f"A {holdout_frac:.0%} final holdout slice is reserved and was NOT used "
        "for tuning or window selection.",
        f"Funding approximated at a constant {FUNDING_RATE:.4%}/8h.",
        "Order-Flow Imbalance is skipped here (needs live order books).",
    ]
    if total_trades < 100:
        warnings.append(f"Small sample: {total_trades} trades across all strategies.")
    return {"costs_modeled": True, "per_strategy": per_strategy,
            "combined": {"total_trades": total_trades,
                         "strategies_profitable": profitable,
                         "strategies_tested": sum(1 for s in per_strategy.values() if not s["skipped"])},
            "walk_forward": {"windows": windows,
                             "holdout": {"reserved": True, "used_for_tuning": False,
                                         "bars": len(bars) - holdout_start}},
            "warnings": warnings}
