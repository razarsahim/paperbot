"""CRH lab API (read-only except for starting/cancelling PAPER backtests).

Served separately (`propaper crh-api`, 127.0.0.1:8778) so the running
dashboard API is never restarted; `router` can also be mounted into the main
app. No endpoint can place an order or touch a live engine; the forward-paper
view opens the live Extreme Lab DB read-only.
"""
from __future__ import annotations
import csv
import io
import json
import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .config import CRHConfig, scaled_baseline
from .data import Cache, DATA_VERSION, HOUR_MS
from .engine import crh_signal, near_misses, prescan, SymbolFrame
from .jobs import JobManager
from .runner import PRESET_HOURS, RunStore, config_from_params, resolve_window

TRADE_COLUMNS = ["id", "symbol", "side", "entry_ms", "exit_ms", "entry_price", "exit_price",
                 "qty", "margin_usd", "notional_usd", "leverage", "planned_risk_usd",
                 "entry_fee_usd", "exit_fee_usd", "funding_usd", "net_pnl_usd", "mfe_pct",
                 "mae_pct", "stop_initial", "stop_final", "exit_reason", "rationale"]


def _gross(t: dict) -> float:
    return t["net_pnl_usd"] + t["entry_fee_usd"] + t["exit_fee_usd"] + t["funding_usd"]


def build_router(store: RunStore, jobs: JobManager, cache: Cache,
                 lab_db_path: str = "state/extreme_lab.sqlite") -> APIRouter:
    r = APIRouter(prefix="/api/crh")

    @r.get("/health")
    def health():
        return {"ok": True, "paper_only": True, "data_version": DATA_VERSION,
                "cache_root": str(cache.root), "jobs": len(jobs.jobs), "runs": len(store.list()),
                "time_ms": int(time.time() * 1000)}

    @r.get("/presets")
    def presets():
        base = CRHConfig()
        return {"ranges": list(PRESET_HOURS), "universes": ["top20", "top50", "top100"],
                "capital": [50, 100, 500, 1000, 5000], "leverage": [1, 5, 10, 15, 25],
                "fidelity": ["exact", "approximate"],
                "baseline": base.__dict__, "scaled_example_500": scaled_baseline(500).__dict__,
                "labels": {"historical": "HISTORICAL BACKTEST", "forward": "FORWARD PAPER",
                           "market": "LIVE MARKET DATA"}}

    @r.post("/backtests")
    def start(params: dict, force: bool = False):
        try:
            resolve_window(params)
            config_from_params(params)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, f"invalid parameters: {exc}")
        job = jobs.submit(params, force=force)
        return job.snapshot()

    @r.get("/jobs")
    def list_jobs():
        return jobs.list()

    @r.get("/jobs/{job_id}")
    def job(job_id: str):
        j = jobs.get(job_id)
        if j is None:
            raise HTTPException(404, "no such job")
        return j.snapshot()

    @r.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        if not jobs.cancel(job_id):
            raise HTTPException(409, "job not running")
        return {"cancelled": True}

    @r.get("/runs")
    def runs():
        return store.list()

    def _load(run_id: str) -> dict:
        res = store.load(run_id)
        if res is None:
            raise HTTPException(404, "no such run")
        return res

    @r.get("/runs/{run_id}")
    def run(run_id: str, full: bool = False):
        res = _load(run_id)
        if full:
            return res
        slim = {k: v for k, v in res.items() if k not in ("equity_curve", "candidates", "near_misses")}
        curve = res["equity_curve"]
        step = max(1, len(curve) // 3000)
        sampled = curve[::step] + ([curve[-1]] if curve and (len(curve) - 1) % step else [])
        slim["equity_curve"] = [p[:2] + [p[5], p[6]] for p in sampled]
        slim["candidates"] = {k: len(v) for k, v in res["candidates"].items()}
        slim["near_misses"] = {k: len(v) for k, v in res["near_misses"].items()}
        return slim

    @r.delete("/runs/{run_id}")
    def delete(run_id: str):
        _load(run_id)
        store.delete(run_id)
        return {"deleted": run_id}

    @r.get("/runs/{run_id}/export.json")
    def export_json(run_id: str):
        res = _load(run_id)
        return Response(json.dumps(res, default=str), media_type="application/json",
                        headers={"Content-Disposition": f"attachment; filename=crh_{run_id}.json"})

    @r.get("/runs/{run_id}/export.csv")
    def export_csv(run_id: str):
        res = _load(run_id)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["HISTORICAL BACKTEST", res["summary"]["config_label"], res["summary"]["window"]["start"],
                    res["summary"]["window"]["end_exclusive"], res["summary"]["fidelity"]])
        w.writerow(TRADE_COLUMNS + ["gross_pnl_usd", "duration_min", "status"])
        for t in res["trades"]:
            w.writerow([t.get(c) for c in TRADE_COLUMNS] + [round(_gross(t), 8),
                       round((t["exit_ms"] - t["entry_ms"]) / 60000, 1), "closed"])
        for p in res["open_at_end"]:
            row = {**p, "entry_ms": p["opened_ms"], "exit_ms": None, "exit_price": p.get("mark"),
                   "exit_fee_usd": 0.0, "funding_usd": p["funding_paid_usd"],
                   "net_pnl_usd": (p["unrealized_pnl_usd"] or 0) - p["entry_fee_usd"] - p["funding_paid_usd"],
                   "stop_final": p["stop"], "stop_initial": p["initial_stop"], "exit_reason": "OPEN",
                   "mfe_pct": None, "mae_pct": None}
            w.writerow([row.get(c) for c in TRADE_COLUMNS] + [p["unrealized_pnl_usd"], None, "open"])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=crh_{run_id}_trades.csv"})

    @r.get("/runs/{run_id}/chart")
    def chart(run_id: str, symbol: str, hours_before: int = 72, hours_after: int = 24):
        """1h candles around a symbol's trades with entry/exit markers, stop
        path and the signal's 24-bar reference level. Served from the cache."""
        res = _load(run_id)
        inst = res["instruments"].get(symbol)
        if inst is None:
            raise HTTPException(404, "symbol not in this run")
        bsym = inst.get("bybit_symbol") or symbol.split("/")[0] + "USDT"
        t0, t1 = res["window_utc"]["start_ms"], res["window_utc"]["end_ms_exclusive"]
        off = Cache(cache.root, offline=True)
        k = off.klines(bsym, "1h", t0 - hours_before * HOUR_MS, t1 + hours_after * HOUR_MS)
        candles = [[int(x[0]), *map(float, x[1:6])] for x in k]
        trades = [t for t in res["trades"] if t["symbol"] == symbol]
        opens = [p for p in res["open_at_end"] if p["symbol"] == symbol]
        markers, stops, refs = [], [], []
        for t in trades:
            markers.append({"ts_ms": t["entry_ms"], "kind": "entry", "side": t["side"],
                            "label": f"CRH entry {t['entry_price']:.6g}", "trade_id": t["id"]})
            markers.append({"ts_ms": t["exit_ms"], "kind": "exit", "side": t["side"],
                            "label": f"{t['exit_reason']} {t['net_pnl_usd']:+.2f}", "trade_id": t["id"],
                            "win": t["net_pnl_usd"] > 0})
            stops.append({"trade_id": t["id"], "from": t["entry_ms"], "to": t["exit_ms"],
                          "initial": t["stop_initial"], "final": t["stop_final"]})
        for p in opens:
            markers.append({"ts_ms": p["opened_ms"], "kind": "entry", "side": p["side"],
                            "label": f"CRH entry {p['entry_price']:.6g} (open)", "trade_id": p["id"]})
            stops.append({"trade_id": p["id"], "from": p["opened_ms"], "to": t1,
                          "initial": p["initial_stop"], "final": p["stop"]})
        for c in res["candidates"].get(symbol, []):
            refs.append({"close_ts": c["close_ts"], "drop_pct": c["drop_pct"]})
        # stop path reconstructed from the engine's hourly ratchet rule is not stored;
        # we give initial/final and the exact rule so the UI draws a stepped band.
        return {"label": "HISTORICAL BACKTEST", "symbol": symbol, "candles": candles,
                "markers": markers, "stops": stops, "signals": refs,
                "window": {"start_ms": t0, "end_ms": t1}}

    @r.get("/compare")
    def compare(ids: str = Query(..., description="comma-separated run ids")):
        runs_ = [_load(i) for i in ids.split(",") if i]
        if len(runs_) < 2:
            raise HTTPException(400, "need at least two run ids")
        rows = []
        for res in runs_:
            s, tot = res["summary"], res["totals"]
            rows.append({"run_id": res["run_id"], "label": s["config_label"], "window": s["window"],
                         "universe": s["universe"], "fidelity": s["fidelity"],
                         "capital": s["capital"], "leverage": s["leverage"],
                         "signal_timeframe": res["config"]["signal_timeframe"],
                         "net_pnl": tot["final_equity_usd"] - tot["initial_capital_usd"],
                         "net_return_pct": tot["net_return_pct"], "trades": tot["completed_trades"],
                         "open_at_end": tot["open_positions_at_end"], "win_rate_pct": tot["win_rate_pct"],
                         "profit_factor": None if tot["profit_factor"] in (None, float("inf")) else tot["profit_factor"],
                         "max_drawdown_pct": tot["max_drawdown_pct"], "max_drawdown_usd": tot["max_drawdown_usd"],
                         "largest_loss": tot["largest_loss_usd"], "liquidations": tot["liquidations"],
                         "fees": tot["fees_usd"], "funding": tot["funding_usd"],
                         "slippage": tot["slippage_usd_est"], "realized": tot["net_realized_pnl_usd"],
                         "unrealized": tot["net_unrealized_pnl_usd"],
                         "signals": sum(len(v) for v in res["candidates"].values()),
                         "approved": sum(1 for x in res["signals"] if x["approved"]),
                         "return_over_dd": tot["return_over_maxdd"],
                         "equity_curve": [[p[0], p[1]] for p in res["equity_curve"][::max(1, len(res['equity_curve']) // 2000)]],
                         "symbols_traded": sorted({t["symbol"] for t in res["trades"]} | {p["symbol"] for p in res["open_at_end"]})})
        flags = []
        for key, name in (("window", "date window"), ("fidelity", "data fidelity"),
                          ("universe", "universe"), ("capital", "capital"), ("leverage", "leverage"),
                          ("signal_timeframe", "signal timeframe")):
            if len({json.dumps(x[key], sort_keys=True) for x in rows}) > 1:
                flags.append(f"Runs differ in {name}: results are not like-for-like")
        if any(x["trades"] < 30 for x in rows):
            flags.append("Small samples (< 30 closed trades): differences are not statistically meaningful")
        a, b = rows[0], rows[1]
        sa = set(a["symbols_traded"]); sb = set(b["symbols_traded"])
        def ra(x):
            return (x["net_return_pct"] / max(x["max_drawdown_pct"], 0.5)) if x["trades"] + x["open_at_end"] else 0.0
        best = max(rows, key=ra)
        verdict = (f"{best['label']} ({best['run_id']}) has the better return per unit of max "
                   f"drawdown ({ra(best):+.2f}); this is descriptive, not predictive.")
        return {"label": "HISTORICAL BACKTEST comparison", "runs": rows, "flags": flags,
                "signals_added_in_second": sorted(sb - sa), "signals_missing_in_second": sorted(sa - sb),
                "risk_adjusted_metric": "net_return_pct / max(max_drawdown_pct, 0.5)",
                "verdict": verdict}

    @r.get("/scanner")
    def scanner(run_id: str | None = None, universe: str = "top50"):
        """Historical (per run) or current signal/near-miss table.
        Current mode uses LIVE MARKET DATA (public 1h klines) for the symbols
        of the most recent run of that universe; it never trades."""
        if run_id:
            res = _load(run_id)
            rows = []
            all_syms = sorted({s for d in res["universe"]["daily"].values() for s in d})
            for s in all_syms:
                c = res["candidates"].get(s, [])
                m = res["near_misses"].get(s, [])
                worst = min([x["drop_pct"] for x in c + m], default=None)
                sig = [x for x in res["signals"] if x["symbol"] == s]
                rows.append({"symbol": s, "signals": len(c), "near_misses": len(m),
                             "worst_drop_pct": worst,
                             "last_signal_ts": max([x["close_ts"] for x in c], default=None),
                             "status": "signal" if c else "near-miss" if m else "quiet",
                             "rejections": [x["reject_reason"] for x in sig if not x["approved"]],
                             "data": "ok" if s not in res["data"]["no_data"] else "no candles"})
            return {"label": "HISTORICAL BACKTEST", "run_id": run_id, "rows": rows,
                    "ineligible": res["universe"]["ineligible"]}
        # current market scan over the symbols of the latest run with that universe
        latest = next((x for x in store.list() if x["status"] == "done" and
                       x["params"].get("universe") == universe), None)
        if latest is None:
            return {"label": "LIVE MARKET DATA", "rows": [], "note": f"run a {universe} backtest first "
                    "to establish the eligible symbol list"}
        res = _load(latest["run_id"])
        syms = sorted({s for d in res["universe"]["daily"].values() for s in d})
        now = int(time.time() * 1000)
        t1 = now - now % HOUR_MS
        cfg = CRHConfig()
        import numpy as np
        from ..perp import ContractSpec
        from paperbot.models import Candle
        from paperbot.strategy import atr
        rows = []
        for s in syms:
            bsym = res["instruments"][s].get("bybit_symbol") or s.split("/")[0] + "USDT"
            try:
                k = cache.klines(bsym, "1h", t1 - 210 * HOUR_MS, t1)
            except Exception as exc:
                rows.append({"symbol": s, "status": "no data", "error": type(exc).__name__})
                continue
            if len(k) < cfg.min_bars:
                rows.append({"symbol": s, "status": "insufficient history"})
                continue
            win = [Candle(int(x[0]), *map(float, x[1:6])) for x in k[-199:]]
            vol = atr(win, 14)[-1] or 0.0
            act, reason, ind = crh_signal(win, cfg, vol)
            rows.append({"symbol": s, "change_24h_pct": ind.get("drop_24h_pct"),
                         "drop_condition": ind.get("drop_24h_pct", 0) <= cfg.crash_drop_pct,
                         "hammer": bool(ind.get("reversal_candle")), "status": "signal" if act else
                         ("near-miss" if ind.get("drop_24h_pct", 0) <= cfg.crash_drop_pct else "quiet"),
                         "reason": reason, "candle_close_ts": int(k[-1][0]) + HOUR_MS, "data": "ok"})
        return {"label": "LIVE MARKET DATA", "as_of_ms": t1, "rows": rows,
                "note": "Evaluates the deployed CRH rules on the last closed 1h candle; it never trades."}

    @r.get("/forward")
    def forward():
        """FORWARD PAPER: the live Extreme Lab's crash_reversal sleeve, read-only."""
        p = Path(lab_db_path)
        if not p.exists():
            return {"label": "FORWARD PAPER", "available": False, "reason": "lab DB not found"}
        conn = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            kv = {r_["key"]: json.loads(r_["value"]) for r_ in conn.execute("SELECT key, value FROM kv")}
            led = conn.execute("SELECT * FROM strategies WHERE key='crash_reversal'").fetchone()
            pos = [dict(x) for x in conn.execute("SELECT * FROM positions WHERE strategy='crash_reversal'")]
            trades = [dict(x) for x in conn.execute(
                "SELECT * FROM trades WHERE strategy='crash_reversal' ORDER BY id DESC LIMIT 200")]
            sigs = [dict(x) for x in conn.execute(
                "SELECT * FROM signals WHERE strategy='crash_reversal' ORDER BY id DESC LIMIT 100")]
        finally:
            conn.close()
        marks = kv.get("marks", {}) or {}
        from ..perp import unrealized_pnl
        unreal = 0.0
        for x in pos:
            m = marks.get(x["symbol"])
            x["mark_price"] = m
            x["unrealized_pnl_usd"] = unrealized_pnl(x["side"], x["entry_price"], m, x["qty"]) if m else None
            unreal += x["unrealized_pnl_usd"] or 0.0
        if led is None:
            return {"label": "FORWARD PAPER", "available": False, "reason": "sleeve not in ledger"}
        margin = sum(x["margin_usd"] for x in pos)
        eq = led["cash_usd"] + margin + unreal
        wins = [t for t in trades if t["net_pnl_usd"] > 0]
        losses = [t for t in trades if t["net_pnl_usd"] <= 0]
        gl = -sum(t["net_pnl_usd"] for t in losses)
        return {"label": "FORWARD PAPER", "available": True,
                "last_scan_ms": kv.get("last_scan_ms"), "auto_entry": kv.get("lab_auto_entry"),
                "lab_locked": kv.get("lab_locked"), "lab_lock_reason": kv.get("lab_lock_reason"),
                "sleeve": {"allocation_usd": led["allocation_usd"], "cash_usd": led["cash_usd"],
                           "realized_pnl_usd": led["realized_pnl_usd"], "locked": bool(led["locked"]),
                           "lock_reason": led["lock_reason"], "equity_usd": eq, "margin_usd": margin,
                           "unrealized_usd": unreal,
                           "return_pct": (eq / led["allocation_usd"] - 1) * 100,
                           "trades": len(trades), "win_rate_pct": len(wins) / len(trades) * 100 if trades else None,
                           "profit_factor": (sum(t["net_pnl_usd"] for t in wins) / gl) if gl else None,
                           "fees_usd": sum(t["entry_fee_usd"] + t["exit_fee_usd"] for t in trades),
                           "funding_usd": sum(t["funding_usd"] for t in trades)},
                "positions": pos, "trades": trades, "signals": sigs}
    return r


def create_crh_app(store: RunStore | None = None, cache: Cache | None = None) -> FastAPI:
    store = store or RunStore()
    cache = cache or Cache()
    jobs = JobManager(store, cache)
    app = FastAPI(title="PaperBot Pro — CRH Lab (PAPER ONLY)", docs_url="/api/crh/docs")
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])

    @app.middleware("http")
    async def _pna(request, call_next):
        if request.headers.get("access-control-request-private-network") == "true":
            from starlette.responses import Response as _R
            resp = _R(status_code=200)
        else:
            resp = await call_next(request)
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
        return resp
    app.include_router(build_router(store, jobs, cache))
    app.state.jobs = jobs
    return app
