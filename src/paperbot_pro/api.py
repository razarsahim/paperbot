"""Read-only FastAPI for PaperBot Pro. Binds localhost; mutates nothing.

Serves simulation state from the pro DB plus a read-only bridge to the
legacy BTC/GBP spot engine's DB. No credentials, no order endpoints.
"""
from __future__ import annotations
import asyncio
import csv
import io
import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from paperbot.report import drawdown_series, trade_stats
from .config import ProSettings
from .store import ProStore
from .validation import auto_entry_gate


def _read_legacy(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            kv = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT * FROM kv")}
            pos = conn.execute("SELECT COUNT(*) FROM position").fetchone()[0]
            n_trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            eq_row = conn.execute(
                "SELECT equity FROM equity_history ORDER BY ts_ms DESC LIMIT 1").fetchone()
            return {
                "symbol": kv.get("symbol", "BTC/GBP"),
                "equity_gbp": float(eq_row[0]) if eq_row else float(kv.get("balance", 0.0)),
                "cash_gbp": float(kv.get("balance", 0.0)),
                "open_position": bool(pos),
                "closed_trades": int(n_trades),
                "locked_total": bool(kv.get("locked_total", False)),
                "last_tick_ms": kv.get("last_tick_ms"),
            }
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _marks(store: ProStore) -> dict:
    return store.get("marks", {}) or {}


def _unrealized(pos: dict, mark: float | None, include_funding: bool = True) -> float | None:
    """Per-position display subtracts funding already paid; portfolio equity
    must NOT (funding is settled from cash when applied — double-count bug
    found in review)."""
    if mark is None:
        return None
    direction = 1 if pos["side"] == "long" else -1
    gross = direction * (mark - pos["entry_price"]) * pos["qty"]
    return gross - pos["funding_paid_usd"] if include_funding else gross


def compute_overview(store: ProStore, cfg: ProSettings) -> dict:
    positions = store.open_positions()
    marks = _marks(store)
    margin_used = sum(p["margin_usd"] for p in positions)
    unrealized = sum((_unrealized(p, marks.get(p["symbol"]), include_funding=False) or 0.0)
                     for p in positions)
    cash_core = float(store.get("cash_core"))
    cash_hype = float(store.get("cash_hype"))
    equity = cash_core + cash_hype + margin_used + unrealized
    initial = float(store.get("initial_balance"))
    day_start = float(store.get("day_start_equity", equity))
    trades = store.trades()
    stats = trade_stats([{"net_pnl": t["net_pnl_usd"], "entry_ms": t["entry_ms"],
                          "exit_ms": t["exit_ms"]} for t in trades])
    history = store.equity_history()
    dd = drawdown_series([{"equity": r["equity_usd"]} for r in history]) if history else []
    combined_risk = sum(p["planned_risk_usd"] for p in positions)
    locked_daily = bool(store.get("locked_daily"))
    locked_total = bool(store.get("locked_total"))
    gate_ok, gate_reason = auto_entry_gate(cfg)
    if locked_total:
        pause = "TOTAL DRAWDOWN PAUSE: manual review required"
    elif locked_daily:
        pause = "Daily loss lockout until next UTC day"
    elif store.get("manual_pause"):
        pause = "Manually paused: run `propaper resume` to re-enable entries"
    elif not gate_ok:
        pause = gate_reason
    else:
        pause = None
    return {
        "mode": "PAPER", "ts_ms": int(time.time() * 1000),
        "equity_usd": equity, "cash_usd": cash_core + cash_hype,
        "margin_used_usd": margin_used,
        # Watch-only hype cash is NOT deployable margin.
        "free_margin_usd": cash_core + (0.0 if cfg.hype_watch_only else cash_hype),
        "exposure_notional_usd": sum(p["notional_usd"] for p in positions),
        "daily_pnl_usd": equity - day_start,
        "total_pnl_usd": equity - initial,
        "win_rate_pct": stats["win_rate_pct"],
        "profit_factor": stats["profit_factor"],
        "max_drawdown_pct": abs(min(dd)) if dd else 0.0,
        "risk": {
            "open_positions": len(positions),
            "max_positions": cfg.max_open_positions,
            "combined_planned_risk_pct": combined_risk / equity * 100 if equity > 0 else 0.0,
            "risk_ceiling_pct": cfg.max_combined_risk * 100,
            "daily_locked": locked_daily, "total_locked": locked_total,
            "trading_enabled": pause is None, "pause_reason": pause,
        },
        "sleeves": {
            "core": {"balance_usd": cfg.core_sleeve_usd, "available_usd": cash_core},
            "hype": {"balance_usd": cfg.hype_sleeve_usd, "available_usd": cash_hype,
                     "watch_only": cfg.hype_watch_only},
        },
        "legacy": _read_legacy(cfg.legacy_db_path),
    }


def create_app(cfg: ProSettings) -> FastAPI:
    cfg.validate()
    store = ProStore(cfg.db_path, cfg)
    app = FastAPI(title="PaperBot Pro (PAPER ONLY)", docs_url="/api/docs")
    app.add_middleware(CORSMiddleware,
                       allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                       allow_methods=["GET"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        legacy = _read_legacy(cfg.legacy_db_path)
        now = time.time() * 1000
        legacy_tick = legacy.get("last_tick_ms") if legacy else None
        last_scan = store.get("last_scan_ms")
        sources = store.get("data_sources", [])
        degraded = any(not s.get("ok") for s in sources)
        return {
            "status": "degraded" if degraded else "ok",
            "engines": {
                "legacy": {"running": bool(legacy_tick and now - legacy_tick < 300_000),
                           "last_tick_ms": legacy_tick},
                "pro": {"running": bool(last_scan and now - last_scan < cfg.scan_interval_seconds * 3000),
                        "last_scan_ms": last_scan,
                        "auto_entry_enabled": auto_entry_gate(cfg)[0]},
            },
            "data_sources": sources,
        }

    @app.get("/api/overview")
    def overview():
        return compute_overview(store, cfg)

    @app.get("/api/positions")
    def positions():
        marks = _marks(store)
        out = []
        for p in store.open_positions():
            mark = marks.get(p["symbol"])
            out.append({
                "id": p["id"], "symbol": p["symbol"], "side": p["side"],
                "leverage": p["leverage"], "qty": p["qty"], "entry_price": p["entry_price"],
                "mark_price": mark, "liq_price_est": p["liq_price_est"],
                "stop": p["stop"], "target": p["target"], "margin_usd": p["margin_usd"],
                "notional_usd": p["notional_usd"],
                "unrealized_pnl_usd": _unrealized(p, mark),
                "funding_paid_usd": p["funding_paid_usd"],
                "fees_paid_usd": p["entry_fee_usd"],
                "planned_risk_pct": p["planned_risk_pct"] * 100,
                "opened_at_ms": p["opened_ms"], "sleeve": p["sleeve"],
            })
        return out

    @app.get("/api/trades")
    def trades(limit: int = 200, symbol: str | None = None, sleeve: str | None = None):
        return store.trades(limit=limit, symbol=symbol, sleeve=sleeve)

    @app.get("/api/trades/{trade_id}")
    def trade_detail(trade_id: int):
        rows = [t for t in store.trades(limit=100_000) if t["id"] == trade_id]
        if not rows:
            raise HTTPException(404, "trade not found")
        return rows[0]

    @app.get("/api/signals")
    def signals(limit: int = 200):
        return store.signals(limit)

    @app.get("/api/universe")
    def universe():
        rows = [dict(r) for r in store.conn.execute(
            "SELECT * FROM universe ORDER BY rank")]
        instruments = {r["coingecko_id"]: dict(r) for r in store.conn.execute(
            "SELECT * FROM instruments")}
        indicators = store.get("asset_indicators", {})
        updated = max((r["updated_ms"] for r in rows), default=None)
        assets = []
        for r in rows:
            inst = instruments.get(r["coingecko_id"])
            ind = indicators.get(r["coingecko_id"], {})
            assets.append({
                "rank": r["rank"], "coingecko_id": r["coingecko_id"],
                "symbol": r["symbol"], "name": r["name"], "price_usd": r["price_usd"],
                "change_24h_pct": r["change_24h_pct"], "market_cap_usd": r["market_cap_usd"],
                "volume_24h_usd": r["volume_24h_usd"],
                "trend": ind.get("trend", "flat"), "atr_pct": ind.get("atr_pct"),
                "rsi": ind.get("rsi"), "signal": ind.get("signal"),
                "eligible": bool(inst and inst["eligible"]),
                "reason": inst["reason"] if inst else "instrument not resolved yet",
                "instrument": ({
                    "exchange": inst["exchange"], "symbol": inst["symbol"],
                    "taker_fee": inst["taker_fee"], "maint_margin_rate": inst["maint_margin_rate"],
                    "tick_size": inst["tick_size"], "lot_size": inst["lot_size"],
                    "funding_rate": ind.get("funding_rate"), "mark_price": ind.get("mark_price"),
                    "spread_pct": ind.get("spread_pct"), "data_age_s": ind.get("data_age_s"),
                } if inst and inst["eligible"] else None),
            })
        changes = [{"date": r["date"], "added": json.loads(r["added"]),
                    "removed": json.loads(r["removed"])}
                   for r in store.conn.execute(
                       "SELECT * FROM universe_changes ORDER BY id DESC LIMIT 30")]
        now_ms = time.time() * 1000
        stale = updated is None or now_ms - updated > cfg.universe_refresh_hours * 3_600_000 * 1.5
        return {"updated_at_ms": updated, "stale": stale, "assets": assets, "changes": changes}

    @app.get("/api/analytics")
    def analytics():
        history = store.equity_history()
        curve = [[r["ts_ms"], r["equity_usd"]] for r in history]
        dd = drawdown_series([{"equity": r["equity_usd"]} for r in history])
        trades_all = store.trades(limit=100_000)
        monthly: dict[str, float] = {}
        by_asset: dict[str, dict] = {}
        for t in trades_all:
            month = time.strftime("%Y-%m", time.gmtime(t["exit_ms"] / 1000))
            monthly[month] = monthly.get(month, 0.0) + t["net_pnl_usd"]
            a = by_asset.setdefault(t["symbol"], {"symbol": t["symbol"], "trades": 0, "pnl_usd": 0.0})
            a["trades"] += 1
            a["pnl_usd"] += t["net_pnl_usd"]
        report_path = Path(cfg.validation_report_path)
        summary = None
        if report_path.exists():
            try:
                summary = json.loads(report_path.read_text()).get("summary")
            except (json.JSONDecodeError, OSError):
                summary = "validation report unreadable"
        return {
            "equity_curve": curve,
            "drawdown_curve": [[r["ts_ms"], d] for r, d in zip(history, dd)],
            "monthly": [{"month": m, "pnl_usd": v} for m, v in sorted(monthly.items())],
            "by_asset": sorted(by_asset.values(), key=lambda a: a["pnl_usd"]),
            "benchmarks": {"cash_usd": float(store.get("initial_balance")),
                           "btc_hold_pct": store.get("btc_hold_pct")},
            "validation": {"exists": report_path.exists(), "summary": summary},
        }

    @app.get("/api/hype")
    def hype():
        tokens = []
        for r in store.conn.execute("SELECT * FROM hype_tokens ORDER BY id DESC LIMIT 100"):
            row = dict(r)
            row["flags"] = json.loads(row["flags"])
            row["evidence"] = json.loads(row["evidence"])
            tokens.append(row)
        return {
            "sleeve": {"balance_usd": float(store.get("cash_hype")),
                       "spent_usd": float(store.get("hype_cumulative_loss_usd", 0.0)),
                       "loss_cap_usd": cfg.hype_cumulative_loss_cap_usd,
                       "watch_only": cfg.hype_watch_only},
            "tokens": tokens,
        }

    @app.get("/api/audit")
    def audit(limit: int = 200):
        return store.audit_log(limit)

    @app.get("/api/settings")
    def settings():
        d = asdict(cfg)
        d["note"] = "PAPER ONLY — read-only display; no credentials exist in this system"
        return d

    @app.get("/api/export/trades.csv")
    def export_trades():
        rows = store.trades(limit=100_000)
        buf = io.StringIO()
        if rows:
            flat = [{**t, "indicator_snapshot": json.dumps(t.get("indicator_snapshot"))}
                    for t in rows]
            writer = csv.DictWriter(buf, fieldnames=list(flat[0].keys()))
            writer.writeheader()
            writer.writerows(flat)
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=paper_trades.csv"})

    @app.get("/api/candles")
    def candles(symbol: str, tf: str = "1h", limit: int = 300):
        from .marketdata import fetch_candles_cached
        try:
            data = fetch_candles_cached(store, cfg, symbol, tf, limit)
        except Exception as exc:
            raise HTTPException(503, f"market data unavailable: {exc}")
        trade_markers = []
        for t in store.trades(limit=500, symbol=symbol):
            trade_markers.append({"ts_ms": t["entry_ms"], "kind": "entry", "side": t["side"],
                                  "price": t["entry_price"], "label": f"{t['side']} entry"})
            trade_markers.append({"ts_ms": t["exit_ms"], "kind": "exit", "side": t["side"],
                                  "price": t["exit_price"], "label": t["exit_reason"]})
        pos = store.position(symbol)
        return {"symbol": symbol, "tf": tf, "candles": data,
                "markers": trade_markers,
                "overlays": {"stop": pos["stop"] if pos else None,
                             "target": pos["target"] if pos else None,
                             "liq": pos["liq_price_est"] if pos else None}}

    @app.get("/api/events")
    async def events(limit: int | None = None):
        async def stream():
            sent = 0
            while limit is None or sent < limit:
                payload = json.dumps(compute_overview(store, cfg))
                yield f"event: overview\ndata: {payload}\n\n"
                sent += 1
                if limit is None or sent < limit:
                    await asyncio.sleep(10)
        return StreamingResponse(stream(), media_type="text/event-stream")

    return app
