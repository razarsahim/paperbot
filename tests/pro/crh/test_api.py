"""CRH Lab API: job lifecycle, cancel, reuse, run retrieval, exports,
compare, scanner and forward-paper (read-only) endpoints."""
import gzip
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paperbot_pro.crh import runner as R
from paperbot_pro.crh.api import create_crh_app
from paperbot_pro.crh.data import Cache
from paperbot_pro.crh.runner import RunStore


def _fake_result(params, t0, t1, run_id, final=55.0):
    cfg = R.config_from_params(params)
    trades = [{"id": 1, "strategy": "crash_reversal", "symbol": "ZEC/USDT:USDT", "side": "long",
               "leverage": 10.0, "qty": 0.1, "entry_price": 100.0, "exit_price": 150.0,
               "stop_initial": 90.0, "stop_final": 140.0, "target": None, "margin_usd": 1.0,
               "notional_usd": 10.0, "entry_fee_usd": 0.006, "exit_fee_usd": 0.009,
               "funding_usd": 0.0, "net_pnl_usd": final - 50.0, "mfe_pct": 50.0, "mae_pct": 0.0,
               "entry_ms": t0 + 3_600_000, "exit_ms": t0 + 7_200_000, "exit_reason": "STOP",
               "rationale": "test", "indicator_snapshot": {}, "signal_bar_ms": t0}]
    curve = [[t0, 50.0, 50.0, 0, 0, 50.0, 0.0], [t1, final, final, 0, 0, final, final - 50]]
    return {"run_id": run_id, "params": params, "config": cfg.__dict__.copy(),
            "window_utc": {"start_ms": t0, "end_ms_exclusive": t1}, "trades": trades,
            "open_at_end": [], "signals": [{"ts_ms": t0, "strategy": "crash_reversal",
                                            "symbol": "ZEC/USDT:USDT", "action": "long",
                                            "approved": True, "reject_reason": None, "details": ""}],
            "risk_events": [], "funding_events": [], "equity_curve": curve,
            "final_cash": final, "final_equity": final, "fidelity": "exact",
            "summary": {"config_label": cfg.label, "window": {"start": R.utc_iso(t0),
                        "end_exclusive": R.utc_iso(t1)}, "fidelity": "exact (...)",
                        "universe": params.get("universe", "custom"), "capital": cfg.starting_capital_usd, "leverage": cfg.leverage,
                        "final_equity": final, "trades": 1},
            "totals": {"final_equity_usd": final, "initial_capital_usd": 50.0,
                       "net_return_pct": (final / 50 - 1) * 100, "completed_trades": 1,
                       "open_positions_at_end": 0, "win_rate_pct": 100.0, "profit_factor": None,
                       "max_drawdown_pct": 0.0, "max_drawdown_usd": 0.0, "largest_loss_usd": None,
                       "liquidations": 0, "fees_usd": 0.015, "funding_usd": 0.0,
                       "slippage_usd_est": 0.01, "net_realized_pnl_usd": final - 50,
                       "net_unrealized_pnl_usd": 0.0, "return_over_maxdd": None},
            "daily": [], "universe": {"daily": {"2026-10-15": ["ZEC/USDT:USDT"]}, "ineligible": {}},
            "instruments": {"ZEC/USDT:USDT": {"bybit_symbol": "ZECUSDT"}},
            "candidates": {"ZEC/USDT:USDT": [{"close_ts": t0, "drop_pct": -9.0}]},
            "near_misses": {}, "data": {"no_data": []}, "checks": {}, "warnings": [],
            "reused_from": None}


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = RunStore(str(tmp_path / "runs.sqlite"), str(tmp_path / "results"))
    cache = Cache(tmp_path / "cache", offline=True)
    calls = {"n": 0}

    def fake_run(params, cache=None, store=None, progress=None, cancelled=None, run_id=None, force=False):
        calls["n"] += 1
        t0, t1 = R.resolve_window(params)
        cfg = R.config_from_params(params)
        key = R.reuse_key(params, cfg, t0, t1)
        if store is not None and not force:
            prev = store.find_reusable(key)
            if prev:
                res = store.load(prev)
                res["reused_from"] = prev
                return res
        store.create(run_id, params, key, cfg.label)
        for stage in ("universe", "candles", "prescan", "books", "replay", "report"):
            if cancelled and cancelled():
                store.fail(run_id, "cancelled")
                raise RuntimeError("cancelled")
            progress(stage, 1.0, None)
            if params.get("slow"):
                time.sleep(0.05)
        res = _fake_result(params, t0, t1, run_id, final=float(params.get("final", 55.0)))
        store.finish(run_id, res)
        return res
    import paperbot_pro.crh.jobs as J
    monkeypatch.setattr(J, "run_backtest", fake_run)
    app = create_crh_app(store, cache)
    c = TestClient(app)
    c.calls = calls
    return c


def _wait(c, job_id, timeout=5):
    for _ in range(int(timeout / 0.02)):
        j = c.get(f"/api/crh/jobs/{job_id}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.02)
    raise AssertionError("job did not finish")


P = {"start": "2026-10-15T00:00:00Z", "end": "2026-10-16T00:00:00Z", "symbols": ["ZEC/USDT:USDT"],
     "capital": 50, "leverage": 10}


def test_health_and_presets(client):
    assert client.get("/api/crh/health").json()["paper_only"] is True
    p = client.get("/api/crh/presets").json()
    assert p["baseline"]["crash_drop_pct"] == -8.0 and "top50" in p["universes"]


def test_job_lifecycle_progress_and_result(client):
    j = client.post("/api/crh/backtests", json=P).json()
    assert j["status"] in ("queued", "running")
    done = _wait(client, j["job_id"])
    assert done["status"] == "done" and done["overall"] == 1.0 and done["run_id"]
    stages = [x["stage"] for x in done["log"]]
    assert stages[:3] == ["universe", "candles", "prescan"]
    run = client.get(f"/api/crh/runs/{done['run_id']}").json()
    assert run["summary"]["final_equity"] == 55.0 and len(run["trades"]) == 1
    assert run["candidates"] == {"ZEC/USDT:USDT": 1}            # slim view counts
    full = client.get(f"/api/crh/runs/{done['run_id']}?full=true").json()
    assert isinstance(full["candidates"]["ZEC/USDT:USDT"], list)
    assert len(client.get("/api/crh/runs").json()) == 1


def test_identical_settings_reuse_result_and_force_reruns(client):
    a = _wait(client, client.post("/api/crh/backtests", json=P).json()["job_id"])
    b = _wait(client, client.post("/api/crh/backtests", json=P).json()["job_id"])
    assert b["reused"] and b["run_id"] == a["run_id"]
    c = _wait(client, client.post("/api/crh/backtests?force=true", json=P).json()["job_id"])
    assert not c["reused"] and c["run_id"] != a["run_id"]


def test_cancel_running_job(client):
    j = client.post("/api/crh/backtests", json={**P, "slow": True}).json()
    time.sleep(0.06)
    assert client.post(f"/api/crh/jobs/{j['job_id']}/cancel").json()["cancelled"]
    done = _wait(client, j["job_id"])
    assert done["status"] == "cancelled"
    assert client.post(f"/api/crh/jobs/{j['job_id']}/cancel").status_code == 409


def test_invalid_parameters_rejected(client):
    assert client.post("/api/crh/backtests", json={**P, "leverage": 100}).status_code == 400
    assert client.post("/api/crh/backtests", json={"start": "2026-10-02T00:00:00Z",
                                                   "end": "2026-10-01T00:00:00Z"}).status_code == 400
    assert client.get("/api/crh/runs/nope").status_code == 404


def test_exports_compare_scanner_delete(client):
    a = _wait(client, client.post("/api/crh/backtests", json=P).json()["job_id"])
    b = _wait(client, client.post("/api/crh/backtests", json={**P, "leverage": 25, "final": 48}).json()["job_id"])
    csv_text = client.get(f"/api/crh/runs/{a['run_id']}/export.csv").text
    assert csv_text.startswith("HISTORICAL BACKTEST") and "ZEC/USDT:USDT" in csv_text
    js = client.get(f"/api/crh/runs/{a['run_id']}/export.json").json()
    assert js["run_id"] == a["run_id"]
    cmp = client.get(f"/api/crh/compare?ids={a['run_id']},{b['run_id']}").json()
    assert len(cmp["runs"]) == 2 and any("leverage" in f for f in cmp["flags"])
    assert "better return per unit" in cmp["verdict"]
    assert client.get("/api/crh/compare?ids=" + a["run_id"]).status_code == 400
    sc = client.get(f"/api/crh/scanner?run_id={a['run_id']}").json()
    assert sc["label"] == "HISTORICAL BACKTEST" and sc["rows"][0]["status"] == "signal"
    assert client.delete(f"/api/crh/runs/{a['run_id']}").json()["deleted"] == a["run_id"]
    assert client.get(f"/api/crh/runs/{a['run_id']}").status_code == 404


def test_forward_paper_reads_lab_db_read_only(tmp_path):
    import sqlite3
    from paperbot_pro.crh.api import build_router
    from paperbot_pro.crh.jobs import JobManager
    from fastapi import FastAPI
    db = tmp_path / "lab.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript("""
      CREATE TABLE kv(key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE strategies(key TEXT, name TEXT, allocation_usd REAL, cash_usd REAL, realized_pnl_usd REAL, locked INTEGER, lock_reason TEXT);
      CREATE TABLE positions(id INTEGER, strategy TEXT, symbol TEXT, side TEXT, qty REAL, entry_price REAL, margin_usd REAL);
      CREATE TABLE trades(id INTEGER, strategy TEXT, net_pnl_usd REAL, entry_fee_usd REAL, exit_fee_usd REAL, funding_usd REAL);
      CREATE TABLE signals(id INTEGER, strategy TEXT);
      INSERT INTO kv VALUES('marks','{"ZEC/USDT:USDT": 110}'),('lab_auto_entry','true'),('lab_locked','false');
      INSERT INTO strategies VALUES('crash_reversal','Crash Reversal Hunter',50,40,0,0,NULL);
      INSERT INTO positions VALUES(1,'crash_reversal','ZEC/USDT:USDT','long',0.1,100,10);
    """)
    conn.commit(); conn.close()
    store = RunStore(str(tmp_path / "r.sqlite"), str(tmp_path / "res"))
    app = FastAPI()
    app.include_router(build_router(store, JobManager(store, Cache(tmp_path / "c", offline=True)),
                                    Cache(tmp_path / "c", offline=True), lab_db_path=str(db)))
    out = TestClient(app).get("/api/crh/forward").json()
    assert out["label"] == "FORWARD PAPER" and out["available"]
    assert out["sleeve"]["equity_usd"] == pytest.approx(40 + 10 + 1.0)   # cash + margin + uPnL
    assert out["positions"][0]["unrealized_pnl_usd"] == pytest.approx(1.0)
