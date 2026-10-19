"""Regression fixtures from earlier replays, reproduced through the cache +
pipeline OFFLINE. Nothing is hardcoded as 'expected' beyond the previously
published outcomes; any drift is a real change in data or logic. Skipped
when the local cache lacks the archived data."""
import json
from pathlib import Path

import pytest

from paperbot_pro.crh.data import Cache
from paperbot_pro.crh.runner import run_backtest, reuse_key, config_from_params, resolve_window

CACHE = Path("cache")
TOP20 = [f"{s}/USDT:USDT" for s in "BTC ETH BNB XRP SOL TRX ZEC HYPE DOGE XMR LINK ADA XLM NEAR BCH LTC".split()]
have = lambda sym, day: (CACHE / "bybit" / "book_samples" / sym / f"{day}.json.gz").exists() and \
    (CACHE / "bybit" / "kline_1m" / f"{sym}.parquet").exists() and \
    (CACHE / "bybit" / "risk_limit" / f"{sym}.json").exists()


@pytest.mark.skipif(not have("ZECUSDT", "2026-10-15"), reason="cache lacks Oct 15-19 data")
def test_continuous_oct15_19_top20_reproduces_published_result():
    r = run_backtest({"start": "2026-10-15T00:00:00Z", "end": "2026-10-19T00:00:00Z",
                      "symbols": TOP20, "capital": 50, "leverage": 10}, cache=Cache(offline=True))
    s = r["summary"]
    assert s["trades"] == 2 and s["open_at_end"] == 0
    assert s["final_equity"] == pytest.approx(67.33, abs=0.01)
    assert [t["symbol"][:3] for t in r["trades"]] == ["ZEC", "NEA"]
    assert r["checks"]["leakage"]["ok"] and r["checks"]["accounting_ok"]
    assert r["checks"]["mark_price_liquidation"]["mismatch"] == []
    assert s["is_baseline_rules"] and s["fidelity"].startswith("exact (")
    assert [round(d["end_equity"], 2) for d in r["daily"]] == [75.27, 67.33, 67.33, 67.33]


@pytest.mark.skipif(not have("ENAUSDT", "2026-10-18"), reason="cache lacks top-50 Oct 17-19 data")
def test_top50_oct17_19_reproduces_published_result_with_open_ena():
    inst = json.loads(Path("research/crh_top50_2026-10-17_to_19/instruments.json").read_text())
    syms = [i["symbol"] for i in inst]
    r = run_backtest({"start": "2026-10-17T00:00:00Z", "end": "2026-10-19T00:00:00Z",
                      "symbols": syms, "capital": 50, "leverage": 10}, cache=Cache(offline=True))
    s = r["summary"]
    assert s["trades"] == 0 and s["open_at_end"] == 1
    assert r["open_at_end"][0]["symbol"] == "ENA/USDT:USDT"
    assert s["final_equity"] == pytest.approx(59.28, abs=0.01)
    assert s["realized_pnl"] == 0 and s["unrealized_pnl"] == pytest.approx(9.28, abs=0.01)
    # 40 other instruments never produced a signal; no L2 was needed or fetched for them
    assert len(r["candidates"]) == 1 and "ENA/USDT:USDT" in r["candidates"]


@pytest.mark.skipif(not have("ZECUSDT", "2026-10-15"), reason="cache lacks Oct 15-19 data")
def test_cached_rerun_is_identical_and_reusable(tmp_path):
    from paperbot_pro.crh.runner import RunStore
    store = RunStore(str(tmp_path / "runs.sqlite"), str(tmp_path / "results"))
    params = {"start": "2026-10-15T00:00:00Z", "end": "2026-10-17T00:00:00Z",
              "symbols": TOP20, "capital": 500, "leverage": 10}
    a = run_backtest(params, cache=Cache(offline=True), store=store)
    b = run_backtest(params, cache=Cache(offline=True), store=store)
    assert b["reused_from"] == a["run_id"]
    c = run_backtest(params, cache=Cache(offline=True), store=store, force=True)
    assert c["run_id"] != a["run_id"]
    assert c["trades"] == a["trades"] and c["equity_curve"] == a["equity_curve"]
    assert a["summary"]["capital"] == 500 and a["config"]["risk_per_trade_usd"] == 50.0


def test_reuse_key_changes_with_config_window_and_universe():
    base = {"preset": "48h", "capital": 50, "leverage": 10, "universe": "top20"}
    t0, t1 = resolve_window({"start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z"})
    k1 = reuse_key(base, config_from_params(base), t0, t1)
    assert k1 != reuse_key({**base, "universe": "top50"}, config_from_params(base), t0, t1)
    assert k1 != reuse_key(base, config_from_params({**base, "leverage": 25}), t0, t1)
    assert k1 != reuse_key(base, config_from_params(base), t0, t1 + 60_000)


def test_resolve_window_presets_end_on_completed_hour():
    t0, t1 = resolve_window({"preset": "24h"})
    assert t1 % 3_600_000 == 0 and t1 - t0 == 24 * 3_600_000
    with pytest.raises(ValueError):
        resolve_window({"start": "2026-10-02T00:00:00Z", "end": "2026-10-01T00:00:00Z"})
