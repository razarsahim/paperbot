"""Scientific validation for the perp simulator: chronology-safe per-market
backtests with fees, slippage, funding and conservative liquidation, plus an
aggregated report. Results are diagnostics — NEVER evidence of future
profitability. The report artifact is what unlocks auto-entry, so it must be
generated deliberately and reviewed by a human.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from paperbot.models import Candle
from .config import ProSettings
from .perp import ContractSpec, funding_cost, liquidation_price, plan_entry, realized_pnl
from .scanner import StrategyParams, generate_signal

FUNDING_INTERVAL_MS = 8 * 3_600_000
DEFAULT_FUNDING_RATE = 0.0001  # ~0.01%/8h, a typical positive rate; approximation


def _exit_check(side: str, position: dict, candle: Candle, cfg: ProSettings,
                fee: float) -> tuple[str, float] | None:
    """Conservative candle-based exit: liquidation first, then gap-at-open
    stop, open-beyond-target, intrabar stop (stop-first), intrabar target."""
    liq, stop, target = position["liq"], position["stop"], position["target"]
    if (side == "long" and candle.low <= liq) or (side == "short" and candle.high >= liq):
        return ("LIQUIDATION", liq)
    if (side == "long" and candle.open <= stop) or (side == "short" and candle.open >= stop):
        return ("STOP_GAP", candle.open)
    if (side == "long" and candle.open >= target) or (side == "short" and candle.open <= target):
        return ("TARGET_GAP", target)
    if (side == "long" and candle.low <= stop) or (side == "short" and candle.high >= stop):
        return ("STOP", stop)
    if (side == "long" and candle.high >= target) or (side == "short" and candle.low <= target):
        return ("TARGET", target)
    return None


def perp_backtest(bars: list[Candle], cfg: ProSettings, spec: ContractSpec,
                  params: StrategyParams | None = None,
                  funding_rate: float = DEFAULT_FUNDING_RATE) -> dict:
    """Single-market, one position at a time, next-bar-open entries from
    previous-bar signals. Funding charged at 8h boundaries using a constant
    approximate rate (historical per-interval rates are not public backfill
    on all venues — documented approximation, conservative for longs)."""
    cfg.validate()
    params = params or StrategyParams()
    equity = cfg.starting_balance_usd
    peak, max_dd = equity, 0.0
    position: dict | None = None
    trades: list[dict] = []
    day, day_start, locked_daily, locked_total = "", equity, False, False
    for i in range(cfg.min_bars, len(bars)):
        candle = bars[i]
        new_day = datetime.fromtimestamp(candle.timestamp / 1000, timezone.utc).strftime("%Y-%m-%d")
        if new_day != day:
            day, locked_daily = new_day, False
            day_start = equity
        exited = False
        if position is not None:
            # funding at boundaries inside this bar
            boundary = (position["last_funding"] // FUNDING_INTERVAL_MS + 1) * FUNDING_INTERVAL_MS
            while boundary <= candle.timestamp:
                position["funding"] += funding_cost(position["side"], funding_rate,
                                                    candle.open, position["qty"])
                boundary += FUNDING_INTERVAL_MS
            position["last_funding"] = candle.timestamp
            hit = _exit_check(position["side"], position, candle, cfg, spec.taker_fee)
            if hit is not None:
                reason, raw = hit
                sign = 1 if position["side"] == "long" else -1
                if reason == "LIQUIDATION":
                    pnl = -(position["margin"] + position["entry_fee"] + max(position["funding"], 0.0))
                    exit_fee = 0.0
                    fill = raw
                else:
                    fill = raw * (1 - sign * cfg.slippage_rate)
                    exit_fee = abs(fill * position["qty"] * spec.taker_fee)
                    pnl = realized_pnl(position["side"], position["entry"], fill,
                                       position["qty"], position["entry_fee"], exit_fee,
                                       position["funding"])
                equity += pnl
                trades.append({"symbol": spec.symbol, "side": position["side"],
                               "entry_ms": position["entry_ms"], "exit_ms": candle.timestamp,
                               "entry_price": position["entry"], "exit_price": fill,
                               "margin_usd": position["margin"],
                               "entry_fee_usd": position["entry_fee"], "exit_fee_usd": exit_fee,
                               "funding_usd": position["funding"], "net_pnl_usd": pnl,
                               "exit_reason": reason})
                position, exited = None, True
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        if equity <= peak * (1 - cfg.max_total_drawdown):
            locked_total = True
        if equity <= day_start * (1 - cfg.max_daily_loss):
            locked_daily = True
        if position is not None or exited or locked_total or locked_daily:
            continue
        signal = generate_signal(bars[:i], params)  # previous bars only
        if signal.action is None:
            continue
        price = candle.open  # next-bar-open execution
        plan = plan_entry(signal.action, price, signal.atr, spec, cfg, equity,
                          available_margin=equity * 0.9, risk_rate=cfg.risk_per_trade)
        if not plan.ok:
            continue
        position = {"side": plan.side, "entry": plan.entry_price, "qty": plan.qty,
                    "stop": plan.stop, "target": plan.target, "liq": plan.liq_price_est,
                    "margin": plan.margin_usd, "entry_fee": plan.entry_fee_usd,
                    "funding": 0.0, "entry_ms": candle.timestamp,
                    "last_funding": candle.timestamp}
        # entry-bar adverse path, conservatively (liq first)
        hit = _exit_check(plan.side, position, candle, cfg, spec.taker_fee)
        if hit is not None:
            reason, raw = hit
            sign = 1 if plan.side == "long" else -1
            if reason == "LIQUIDATION":
                pnl = -(plan.margin_usd + plan.entry_fee_usd)
                fill, exit_fee = raw, 0.0
            else:
                fill = raw * (1 - sign * cfg.slippage_rate)
                exit_fee = abs(fill * plan.qty * spec.taker_fee)
                pnl = realized_pnl(plan.side, plan.entry_price, fill, plan.qty,
                                   plan.entry_fee_usd, exit_fee, 0.0)
            equity += pnl
            trades.append({"symbol": spec.symbol, "side": plan.side,
                           "entry_ms": candle.timestamp, "exit_ms": candle.timestamp,
                           "entry_price": plan.entry_price, "exit_price": fill,
                           "margin_usd": plan.margin_usd,
                           "entry_fee_usd": plan.entry_fee_usd, "exit_fee_usd": exit_fee,
                           "funding_usd": 0.0, "net_pnl_usd": pnl,
                           "exit_reason": reason + "_ENTRY_BAR"})
            position = None
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak)
    if position is not None:
        # mark open position at last close, costs included, honestly flagged
        sign = 1 if position["side"] == "long" else -1
        mark = bars[-1].close
        equity += sign * (mark - position["entry"]) * position["qty"] - position["entry_fee"] - position["funding"]
    winners = [t for t in trades if t["net_pnl_usd"] > 0]
    losers = [t for t in trades if t["net_pnl_usd"] < 0]
    gross_w = sum(t["net_pnl_usd"] for t in winners)
    gross_l = abs(sum(t["net_pnl_usd"] for t in losers))
    return {"symbol": spec.symbol, "bars": len(bars), "trades": trades,
            "final_equity": equity,
            "net_return_pct": (equity / cfg.starting_balance_usd - 1) * 100,
            "max_drawdown_pct": max_dd * 100,
            "win_rate_pct": len(winners) / len(trades) * 100 if trades else None,
            "profit_factor": gross_w / gross_l if gross_l else None,
            "still_open": position is not None,
            "locked_total": locked_total}


def validate_markets(data: dict[str, tuple[list[Candle], ContractSpec]],
                     cfg: ProSettings) -> dict:
    markets = []
    for symbol, (bars, spec) in data.items():
        result = perp_backtest(bars, cfg, spec)
        markets.append({"symbol": symbol, "bars": result["bars"],
                        "trades": len(result["trades"]),
                        "net_return_pct": result["net_return_pct"],
                        "max_drawdown_pct": result["max_drawdown_pct"],
                        "win_rate_pct": result["win_rate_pct"],
                        "profit_factor": result["profit_factor"],
                        "first_bar": bars[0].iso, "last_bar": bars[-1].iso})
    total_trades = sum(m["trades"] for m in markets)
    profitable = sum(1 for m in markets if m["net_return_pct"] > 0)
    warnings = [
        "Simulated perp backtest with modeled costs; results are an approximation "
        "and NOT evidence of future profitability.",
        "Per-market tests run independently: portfolio concurrency caps (3 slots, "
        "1.5% combined risk) are NOT modeled in the aggregate; treat combined "
        "figures as an upper bound on activity.",
        f"Funding approximated at a constant {DEFAULT_FUNDING_RATE:.4%}/8h.",
    ]
    if total_trades < 30 * max(1, len(markets)) / 3:
        warnings.append(f"Small sample: {total_trades} trades across {len(markets)} markets.")
    mean_ret = (sum(m["net_return_pct"] for m in markets) / len(markets)) if markets else 0.0
    summary = (f"{len(markets)} markets, {total_trades} trades, "
               f"{profitable}/{len(markets)} profitable, mean return "
               f"{mean_ret:+.2f}% — "
               f"{'NEGATIVE/UNPROVEN' if profitable <= len(markets) / 2 else 'mixed'} evidence; "
               "not predictive.")
    return {"generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "strategy_params": StrategyParams().describe(),
            "markets": markets,
            "combined": {"total_trades": total_trades, "markets_profitable": profitable,
                         "mean_return_pct": mean_ret},
            "warnings": warnings, "summary": summary}


def run_validation(store, cfg: ProSettings, market, out_path: str | None = None) -> dict:
    """Download real public candles for every eligible instrument and write
    the validation artifact. Requires network."""
    instruments = [dict(r) for r in store.conn.execute(
        "SELECT * FROM instruments WHERE eligible=1")]
    data = {}
    for inst in instruments:
        raw, _age = market.candles(inst["exchange"], inst["symbol"], cfg.candle_timeframe, 1000)
        bars = [Candle(int(x[0]), *[float(v) for v in x[1:6]]) for x in raw]
        bars = [b for b in bars if b.timestamp + cfg.timeframe_ms <= time.time() * 1000]
        if len(bars) >= cfg.min_bars + 20:
            spec = ContractSpec(inst["symbol"], inst["taker_fee"], inst["maint_margin_rate"],
                                inst["tick_size"], inst["lot_size"])
            data[inst["symbol"]] = (bars, spec)
    report = validate_markets(data, cfg)
    report["data_provenance"] = {"source": "ccxt public fetch_ohlcv",
                                 "timeframe": cfg.candle_timeframe,
                                 "markets": len(data), "no_live_execution": True}
    path = Path(out_path or cfg.validation_report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    store.audit("info", "validation", f"validation report written: {report['summary']}")
    return report
