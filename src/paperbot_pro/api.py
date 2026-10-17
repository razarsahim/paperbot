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


def compute_lab(store, lab_cfg) -> dict:
    """Extreme Lab snapshot: capital, HWM/threshold, strategies, state."""
    from .perp import unrealized_pnl as _upnl
    marks = store.get("marks", {}) or {}
    positions = store.open_positions()
    margin_used = sum(p["margin_usd"] for p in positions)
    unrealized = 0.0
    out_positions = []
    for p in positions:
        mark = marks.get(p["symbol"])
        u = _upnl(p["side"], p["entry_price"], mark, p["qty"]) if mark is not None else None
        if u is not None:
            unrealized += u
        out_positions.append({**{k: p[k] for k in (
            "id", "strategy", "symbol", "side", "leverage", "qty", "entry_price",
            "margin_usd", "notional_usd", "stop", "target", "liq_price_est",
            "funding_paid_usd", "planned_risk_usd", "opened_ms")},
            "mark_price": mark, "unrealized_pnl_usd": u})
    cash = store.total_cash()
    equity = cash + margin_used + unrealized
    peak = max(float(store.get("peak_equity", lab_cfg.starting_capital_usd)), equity)
    threshold = peak - lab_cfg.trailing_drawdown_usd
    last_scan = store.get("last_scan_ms")
    now_ms = time.time() * 1000
    ledger = store.strategy_ledger()
    from .lab.config import STRATEGIES
    return {
        "status": {
            "live": bool(last_scan and now_ms - last_scan <
                         lab_cfg.monitor_interval_seconds * 3000),
            "last_scan_ms": last_scan,
            "auto_entry": lab_cfg.auto_entry,
            "locked": bool(store.get("lab_locked")),
            "lock_reason": store.get("lab_lock_reason"),
            "manual_pause": bool(store.get("lab_manual_pause")),
            "integrity_locked": bool(store.get("integrity_locked")),
            "integrity_reason": store.get("integrity_reason"),
        },
        "capital": {
            "initial_usd": lab_cfg.starting_capital_usd,
            "equity_usd": equity, "cash_usd": cash,
            "margin_used_usd": margin_used, "unrealized_usd": unrealized,
            "peak_equity_usd": peak, "threshold_usd": threshold,
            "remaining_allowance_usd": max(0.0, equity - threshold),
        },
        "strategies": [{**ledger[s.key], "display_name": s.name,
                        "description": s.description, "cohort": s.cohort,
                        "leverage": lab_cfg.leverage,
                        "status": store.strategy_status(s.key),
                        "unrealized_pnl_usd": sum(
                            (_upnl(p["side"], p["entry_price"], marks.get(p["symbol"]), p["qty"])
                             if marks.get(p["symbol"]) is not None else 0.0)
                            for p in positions if p["strategy"] == s.key),
                        "return_pct": ((ledger[s.key]["cash_usd"]
                                        + sum(p["margin_usd"] for p in positions
                                              if p["strategy"] == s.key))
                                       / ledger[s.key]["allocation_usd"] - 1) * 100,
                        "open_symbols": [p["symbol"] for p in positions
                                         if p["strategy"] == s.key]}
                       for s in STRATEGIES if s.key in ledger],
        "positions": out_positions,
        "signals": store.signals(100),
        "trades": store.trades(200),
        "opportunities": store.get("lab_opportunities", {}),
        "equity_curve": [[r["ts_ms"], r["equity_usd"], r["threshold_usd"]]
                         for r in store.equity_history(5000)],
        "audit": store.audit_log(100),
    }


def compute_research(store, research_cfg) -> dict:
    """Research Lab snapshot — mirrors compute_lab with per-strategy lock
    levels and correlation clusters on positions."""
    from .perp import unrealized_pnl as _upnl
    from .research.config import STRATEGIES as R_STRATEGIES
    marks = store.get("marks", {}) or {}
    positions = store.open_positions()
    margin_used = sum(p["margin_usd"] for p in positions)
    unrealized, out_positions = 0.0, []
    for p in positions:
        mark = marks.get(p["symbol"])
        u = _upnl(p["side"], p["entry_price"], mark, p["qty"]) if mark is not None else None
        if u is not None:
            unrealized += u
        out_positions.append({**{k: p[k] for k in (
            "id", "strategy", "symbol", "side", "leverage", "qty", "entry_price",
            "margin_usd", "notional_usd", "stop", "target", "liq_price_est",
            "funding_paid_usd", "planned_risk_usd", "opened_ms", "corr_cluster")},
            "mark_price": mark, "unrealized_pnl_usd": u})
    cash = store.total_cash()
    equity = cash + margin_used + unrealized
    peak = max(float(store.get("peak_equity", research_cfg.starting_capital_usd)), equity)
    threshold = peak - research_cfg.trailing_drawdown_usd
    last_scan = store.get("last_scan_ms")
    now_ms = time.time() * 1000
    ledger = store.strategy_ledger()
    return {
        "status": {
            "live": bool(last_scan and now_ms - last_scan <
                         research_cfg.monitor_interval_seconds * 3000),
            "last_scan_ms": last_scan, "auto_entry": research_cfg.auto_entry,
            "locked": bool(store.get("lab_locked")),
            "lock_reason": store.get("lab_lock_reason"),
            "manual_pause": bool(store.get("research_manual_pause")),
            "integrity_locked": bool(store.get("integrity_locked")),
            "integrity_reason": store.get("integrity_reason"),
        },
        "capital": {
            "initial_usd": research_cfg.starting_capital_usd,
            "equity_usd": equity, "cash_usd": cash, "margin_used_usd": margin_used,
            "unrealized_usd": unrealized, "peak_equity_usd": peak,
            "threshold_usd": threshold,
            "remaining_allowance_usd": max(0.0, equity - threshold),
        },
        "strategies": [{**ledger[s.key], "display_name": s.name,
                        "description": s.description,
                        "status": store.strategy_status(s.key),
                        "open_symbols": [p["symbol"] for p in positions
                                         if p["strategy"] == s.key]}
                       for s in R_STRATEGIES if s.key in ledger],
        "positions": out_positions,
        "signals": store.signals(100),
        "trades": store.trades(200),
        "opportunities": store.get("research_opportunities", {}) or {},
        "equity_curve": [[r["ts_ms"], r["equity_usd"], r["threshold_usd"]]
                         for r in store.equity_history(5000)],
        "audit": store.audit_log(100),
    }


def _strategy_stats(trades: list[dict]) -> dict:
    """Per-strategy realised stats + a realised-cumulative max-drawdown proxy
    (clearly a realised series, not mark-to-market). Sample flagged."""
    pnls = [t["net_pnl_usd"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_w, gross_l = sum(wins), abs(sum(losses))
    fees = sum(t.get("entry_fee_usd", 0) + t.get("exit_fee_usd", 0) for t in trades)
    funding = sum(t.get("funding_usd", 0) for t in trades)
    peak = cum = max_dd = 0.0
    for p in reversed(pnls):   # trades come newest-first
        cum += p
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return {
        "trade_count": len(trades),
        "win_rate_pct": (len(wins) / len(trades) * 100) if trades else None,
        "profit_factor": (gross_w / gross_l) if gross_l else (None if not wins else None),
        "expectancy_usd": (sum(pnls) / len(pnls)) if pnls else None,
        "realized_pnl_usd": sum(pnls),
        "fees_usd": fees, "funding_usd": funding,
        "max_drawdown_realized_usd": max_dd,
        "sample": "insufficient" if len(trades) < 30 else "developing",
    }


def compute_strategies(lab_store, lab_cfg, research_store=None, research_cfg=None) -> dict:
    """Unified comparison of all ten strategies with a net-PnL ranking. Each row
    is tagged by its cohort ('extreme'/'research'). Post-merge every strategy
    lives in the Extreme Lab; the research store (if still passed) only fills in
    keys the lab ledger does not yet have, so the count is 10 in either phase and
    nothing is double-counted. Figures are forward-paper diagnostics, never
    validated returns."""
    from .lab.config import STRATEGIES as L_STRATEGIES
    from .perp import unrealized_pnl as _upnl
    rows, seen = [], set()

    def add_rows(store, cfg, defs, cohort_of):
        ledger = store.strategy_ledger()
        marks = store.get("marks", {}) or {}
        positions = store.open_positions()
        for sdef in defs:
            if sdef.key not in ledger or sdef.key in seen:
                continue
            seen.add(sdef.key)
            led = ledger[sdef.key]
            strat_pos = [p for p in positions if p["strategy"] == sdef.key]
            margin = sum(p["margin_usd"] for p in strat_pos)
            unreal = sum((_upnl(p["side"], p["entry_price"], marks.get(p["symbol"]), p["qty"])
                          if marks.get(p["symbol"]) is not None else 0.0) for p in strat_pos)
            equity = led["cash_usd"] + margin + unreal
            stats = _strategy_stats(store.trades(limit=100_000, strategy=sdef.key))
            locked = bool(led.get("locked")) or bool(store.get("lab_locked"))
            rows.append({
                "lab": cohort_of(sdef), "key": sdef.key, "name": sdef.name,
                "allocation_usd": led["allocation_usd"], "cash_usd": led["cash_usd"],
                "equity_usd": equity, "unrealized_pnl_usd": unreal,
                "return_pct": (equity / led["allocation_usd"] - 1) * 100,
                "open_positions": len(strat_pos), "leverage": cfg.leverage,
                "locked": locked, **stats,
            })

    add_rows(lab_store, lab_cfg, L_STRATEGIES, lambda s: getattr(s, "cohort", "extreme"))
    if research_store is not None and research_cfg is not None:
        from .research.config import STRATEGIES as R_STRATEGIES
        add_rows(research_store, research_cfg, R_STRATEGIES, lambda s: "research")
    ordered = sorted(rows, key=lambda r: r["realized_pnl_usd"] + r["unrealized_pnl_usd"],
                     reverse=True)
    for i, r in enumerate(ordered, 1):
        r["rank_by_net_pnl"] = i
    return {"count": len(rows), "strategies": rows,
            "note": "Forward-paper diagnostics on virtual funds with real costs — "
                    "not validated or predictive. Small samples are flagged."}


def create_app(cfg: ProSettings, lab_cfg=None, research_cfg=None) -> FastAPI:
    from dataclasses import replace as _replace
    from .lab.config import LabSettings
    from .lab.store import LabStore
    cfg.validate()
    store = ProStore(cfg.db_path, cfg)
    if lab_cfg is None:
        lab_cfg = _replace(LabSettings.from_env(), main_db_path=cfg.db_path)
    lab_store = LabStore(lab_cfg.db_path, lab_cfg)
    from .research.config import ResearchSettings
    from .research.store import ResearchStore
    if research_cfg is None:
        research_cfg = _replace(ResearchSettings.from_env(), main_db_path=cfg.db_path)
    research_store = ResearchStore(research_cfg.db_path, research_cfg)
    app = FastAPI(title="PaperBot Pro (PAPER ONLY)", docs_url="/api/docs")
    # localhost-only, any port (the dashboard dev/prod server port varies);
    # the API binds 127.0.0.1 so this never widens beyond the local machine.
    app.add_middleware(CORSMiddleware,
                       allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
                       allow_methods=["GET"], allow_headers=["*"])

    @app.middleware("http")
    async def _private_network_access(request, call_next):
        # Chrome's Private Network Access blocks a localhost page from calling
        # a localhost API unless the (pre)flight is answered with this header.
        # Everything here is 127.0.0.1-bound, so granting it is local-only.
        if request.headers.get("access-control-request-private-network") == "true":
            from starlette.responses import Response
            resp = Response(status_code=200)
        else:
            resp = await call_next(request)
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
        return resp

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
                "lab": {"running": bool(lab_store.get("last_scan_ms") and
                                        now - lab_store.get("last_scan_ms") <
                                        lab_cfg.monitor_interval_seconds * 3000),
                        "last_scan_ms": lab_store.get("last_scan_ms"),
                        "auto_entry_enabled": lab_cfg.auto_entry,
                        "locked": bool(lab_store.get("lab_locked"))},
            },
            "data_sources": sources,
        }

    @app.get("/api/overview")
    def overview():
        return compute_overview(store, cfg)

    @app.get("/api/lab")
    def lab():
        return compute_lab(lab_store, lab_cfg)

    @app.get("/api/research")
    def research():
        return compute_research(research_store, research_cfg)

    @app.get("/api/strategies")
    def strategies():
        return compute_strategies(lab_store, lab_cfg, research_store, research_cfg)

    @app.get("/api/research/stream")
    async def research_stream(limit: int | None = None):
        live_path = Path(research_cfg.live_state_path)

        def sample() -> dict:
            now = int(time.time() * 1000)
            try:
                state = json.loads(live_path.read_text())
            except (OSError, json.JSONDecodeError):
                return {"live_status": "DISCONNECTED", "server_ts_ms": now,
                        "capital": None, "positions": []}
            age = now - state.get("published_at_ms", 0)
            state["live_status"] = "STALE" if age > max(
                research_cfg.price_fresh_seconds, 60) * 1000 else "LIVE"
            state["server_ts_ms"] = now
            state["publish_age_ms"] = age
            return state

        async def stream():
            sent, last = 0, None
            while limit is None or sent < limit:
                payload = json.dumps(sample())
                if payload != last or limit is not None:
                    yield f"event: research_live\ndata: {payload}\n\n"
                    last = payload
                    sent += 1
                if limit is None or sent < limit:
                    await asyncio.sleep(0.2)
        return StreamingResponse(stream(), media_type="text/event-stream")

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

    @app.get("/api/lab/stream")
    async def lab_stream(limit: int | None = None):
        """Live Extreme Lab state: samples the engine-published snapshot file
        (atomic JSON, no SQLite in the hot path) every 200ms and pushes on
        change. live_status: LIVE (fresh), STALE (old), DISCONNECTED (absent
        or unreadable). Supports any number of concurrent clients."""
        live_path = Path(lab_cfg.live_state_path)

        def sample() -> dict:
            now_ms = int(time.time() * 1000)
            try:
                state = json.loads(live_path.read_text())
            except (OSError, json.JSONDecodeError):
                return {"live_status": "DISCONNECTED", "server_ts_ms": now_ms,
                        "capital": None, "positions": []}
            age_ms = now_ms - state.get("published_at_ms", 0)
            if age_ms > max(lab_cfg.price_fresh_seconds, 60) * 1000:
                state["live_status"] = "STALE"
            else:
                state["live_status"] = "LIVE"
            state["server_ts_ms"] = now_ms
            state["publish_age_ms"] = age_ms
            return state

        async def stream():
            sent = 0
            last_payload = None
            while limit is None or sent < limit:
                state = sample()
                payload = json.dumps(state)
                if payload != last_payload or limit is not None:
                    yield f"event: lab_live\ndata: {payload}\n\n"
                    last_payload = payload
                    sent += 1
                if limit is None or sent < limit:
                    await asyncio.sleep(0.2)
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/events")
    async def events(limit: int | None = None):
        async def stream():
            sent = 0
            while limit is None or sent < limit:
                yield (f"event: overview\ndata: "
                       f"{json.dumps(compute_overview(store, cfg))}\n\n")
                sent += 1
                if limit is not None and sent >= limit:
                    break
                yield f"event: lab\ndata: {json.dumps(compute_lab(lab_store, lab_cfg))}\n\n"
                sent += 1
                if limit is None or sent < limit:
                    await asyncio.sleep(10)
        return StreamingResponse(stream(), media_type="text/event-stream")

    return app
