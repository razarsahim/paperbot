"""Turn a finished replay LabStore into a self-describing result record and
compute the comparison metrics. Pure reads of the throwaway replay DB."""
from __future__ import annotations
import json
import math
from collections import Counter, defaultdict

from ..lab.config import STRATEGIES

SMALL_SAMPLE = 30   # fewer completed trades than this => not statistically meaningful


def _ledger_trades(store) -> list[dict]:
    rows = [dict(r) for r in store.conn.execute("SELECT * FROM trades ORDER BY exit_ms, id")]
    for r in rows:
        if isinstance(r.get("indicator_snapshot"), str):
            try:
                r["indicator_snapshot"] = json.loads(r["indicator_snapshot"])
            except ValueError:
                pass
    return rows


def _slippage_usd(t: dict, slip: float) -> float:
    sign = 1 if t["side"] == "long" else -1
    entry_cost = t["qty"] * t["entry_price"] / (1 + sign * slip) * slip
    if t["exit_reason"] == "LIQUIDATION":
        return entry_cost
    return entry_cost + t["qty"] * t["exit_price"] / (1 - sign * slip) * slip


def metrics(trades: list[dict], open_pos: list[dict], equity_curve: list[list],
            initial: float, slip: float) -> dict:
    n = len(trades)
    pnls = [t["net_pnl_usd"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    realized = sum(pnls)
    unreal_net = sum((p["unrealized_pnl_usd"] or 0.0) - p["entry_fee_usd"] - p["funding_paid_usd"]
                     for p in open_pos)
    final_equity = initial + realized + unreal_net
    fees = sum(t["entry_fee_usd"] + t["exit_fee_usd"] for t in trades) + \
        sum(p["entry_fee_usd"] for p in open_pos)
    funding = sum(t["funding_usd"] for t in trades) + sum(p["funding_paid_usd"] for p in open_pos)
    slippage = sum(_slippage_usd(t, slip) for t in trades) + \
        sum(p["qty"] * p["entry_price"] * slip / (1 + slip) for p in open_pos)
    # drawdown on the per-cycle mark-to-market equity curve
    peak, max_dd, max_dd_pct = -math.inf, 0.0, 0.0
    for _, eq in equity_curve:
        peak = max(peak, eq)
        dd = peak - eq
        if dd > max_dd:
            max_dd, max_dd_pct = dd, dd / peak * 100 if peak > 0 else 0.0
    # hourly returns for a (descriptive) risk-adjusted ratio
    hourly = [eq for i, (_, eq) in enumerate(equity_curve) if i % 60 == 0]
    rets = [(b / a - 1) for a, b in zip(hourly, hourly[1:]) if a > 0]
    sharpe_wk = None
    if len(rets) > 2:
        mu = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
        sharpe_wk = (mu / sd * math.sqrt(len(rets))) if sd > 0 else None
    by_side = {}
    for side in ("long", "short"):
        st = [t for t in trades if t["side"] == side]
        by_side[side] = {"trades": len(st), "net_pnl_usd": sum(t["net_pnl_usd"] for t in st),
                         "wins": sum(1 for t in st if t["net_pnl_usd"] > 0)}
    ret_pct = (final_equity / initial - 1) * 100
    return {
        "initial_capital_usd": initial,
        "final_equity_usd": final_equity,
        "net_realized_pnl_usd": realized,
        "net_unrealized_pnl_usd": unreal_net,
        "net_return_pct": ret_pct,
        "completed_trades": n,
        "open_positions_at_end": len(open_pos),
        "win_rate_pct": (len(wins) / n * 100) if n else None,
        "avg_win_usd": (gross_win / len(wins)) if wins else None,
        "avg_loss_usd": (-gross_loss / len(losses)) if losses else None,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else (None if not wins else math.inf),
        "expectancy_usd": (realized / n) if n else None,
        "max_drawdown_usd": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "return_over_maxdd": (ret_pct / max_dd_pct) if max_dd_pct > 0 else None,
        "sharpe_week_descriptive": sharpe_wk,
        "fees_usd": fees,
        "funding_usd": funding,
        "slippage_usd_est": slippage,
        "liquidations": sum(1 for t in trades if t["exit_reason"] == "LIQUIDATION"),
        "largest_win_usd": max(pnls) if pnls else None,
        "largest_loss_usd": min(pnls) if pnls else None,
        "by_side": by_side,
        "assets_traded": sorted({t["symbol"] for t in trades} | {p["symbol"] for p in open_pos}),
        "exit_reasons": dict(Counter(t["exit_reason"] for t in trades)),
        "small_sample": n < SMALL_SAMPLE,
    }


def extract_run(store, summary: dict, run_id: str, kind: str, strategies, with_orderbook: bool,
                t0: int, t1: int, instruments: list[dict]) -> dict:
    cfg = store.cfg
    trades = _ledger_trades(store)
    open_pos = summary["open_at_end"]
    keys = list(store.strategy_ledger())
    initial = cfg.allocation_per_strategy_usd * len(keys)
    curve = [[r["ts_ms"], r["equity_usd"]] for r in store.conn.execute(
        "SELECT ts_ms, equity_usd FROM equity_history ORDER BY ts_ms")]
    # final mark (t1) appended so the curve ends at the reported equity
    signals = [dict(r) for r in store.conn.execute("SELECT * FROM signals ORDER BY id")]
    audit = [dict(r) for r in store.conn.execute(
        "SELECT ts_ms, level, category, message FROM audit_log "
        "WHERE category IN ('risk','integrity') ORDER BY id")]
    ledger = store.strategy_ledger()
    per_strategy = {}
    for k in keys:
        st = [t for t in trades if t["strategy"] == k]
        op = [p for p in open_pos if p["strategy"] == k]
        sig = [s for s in signals if s["strategy"] == k]
        rej = Counter(s["reject_reason"] for s in sig if not s["approved"])
        # per-sleeve equity curve is only exact for a single-sleeve run
        m = metrics(st, op, curve if len(keys) == 1 else [], cfg.allocation_per_strategy_usd,
                    cfg.slippage_rate)
        m.update({"signals_fired": len(sig),
                  "signals_approved": sum(1 for s in sig if s["approved"]),
                  "rejections": dict(rej.most_common()),
                  "locked": bool(ledger[k]["locked"]), "lock_reason": ledger[k]["lock_reason"]})
        per_strategy[k] = m
    total = metrics(trades, open_pos, curve, initial, cfg.slippage_rate)
    final_eq = total["final_equity_usd"]
    curve.append([t1, final_eq])
    # accounting identity: cash + margin + uPnL == initial + realized + unrealized_net
    cash = store.total_cash()
    margin = sum(p["margin_usd"] for p in open_pos)
    upnl = sum(p["unrealized_pnl_usd"] or 0.0 for p in open_pos)
    identity_gap = (cash + margin + upnl) - final_eq
    hourly_curve = [c for i, c in enumerate(curve) if i % 60 == 0 or i == len(curve) - 1]
    return {
        "label": "HISTORICAL BACKTEST — not live paper; not predictive",
        "run_id": run_id, "kind": kind,
        "strategies": strategies or [s.key for s in STRATEGIES],
        "with_orderbook": with_orderbook,
        "window_utc": {"start_ms": t0, "end_ms_exclusive": t1},
        "instruments": [i["symbol"] for i in instruments],
        "cycles": summary["cycles"], "elapsed_s": summary["elapsed_s"],
        "leakage_check": {"max_data_ts_served": summary["max_data_ts_served"],
                          "final_now": summary["final_now"],
                          "ok": summary["max_data_ts_served"] <= summary["final_now"]},
        "accounting_identity_gap_usd": identity_gap,
        "final_equity_usd": final_eq,
        "totals": total,
        "per_strategy": per_strategy,
        "trades": [{k: t[k] for k in (
            "id", "strategy", "symbol", "side", "qty", "entry_price", "exit_price",
            "stop_initial", "stop_final", "margin_usd", "notional_usd", "entry_fee_usd",
            "exit_fee_usd", "funding_usd", "net_pnl_usd", "mfe_pct", "mae_pct",
            "entry_ms", "exit_ms", "exit_reason", "rationale")} for t in trades],
        "open_at_end": open_pos,
        "signals": [{k: s[k] for k in ("ts_ms", "strategy", "symbol", "action", "approved",
                                       "reject_reason", "details")} for s in signals],
        "risk_events": audit,
        "equity_curve_hourly": hourly_curve,
        "equity_curve_min": curve,
    }
