"""Persistent, DB-backed auto-entry flag.

Auto-entry was env-only (PAPERBOT_LAB_AUTO_ENTRY), so the engine and the API
could disagree (each reads its own process env) and the setting did not survive
a restart. A `lab_auto_entry` kv override, when set, is the single source of
truth both the engine gate and the API read; unset falls back to the env/config
default. Mirrors how `lab_manual_pause` already works. PAPER ONLY."""
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.engine import LabEngine
from paperbot_pro.lab.store import LabStore

H = 3_600_000
SYMBOL = "TST/USDT:USDT"
INSTRUMENT = {"symbol": SYMBOL, "exchange": "fake", "taker_fee": 0.0006,
              "maint_margin_rate": 0.005, "tick_size": 0.1, "lot_size": 0.001}


def breakout_rows(n=100, base=100.0):
    rows = [[i * H, base, base + 0.5, base - 0.5, base, 100.0] for i in range(n - 1)]
    rows.append([(n - 1) * H, base, base + 3.5, base - 0.2, base + 3.2, 350.0])
    return rows


class FakeMarket:
    def __init__(self, rows, last):
        self.rows, self.last = rows, last
    def candles(self, e, s, tf, limit):
        return self.rows, 0.0
    def ticker(self, e, s):
        return {"bid": self.last - 0.05, "ask": self.last + 0.05, "last": self.last}, 0.0
    def funding_rate(self, e, s):
        return {"fundingRate": 0.0001}, 0.0


def make(tmp_path, cfg_auto_entry=False):
    cfg = replace(LabSettings(), db_path=str(tmp_path / "lab.sqlite"), auto_entry=cfg_auto_entry)
    store = LabStore(cfg.db_path, cfg)
    rows = breakout_rows()
    engine = LabEngine(store, cfg, market=FakeMarket(rows, rows[-1][4]),
                       instruments_provider=lambda: [INSTRUMENT])
    return engine, store, cfg


def test_kv_flag_enables_entries_even_when_config_default_off(tmp_path):
    engine, store, cfg = make(tmp_path, cfg_auto_entry=False)
    store.set("lab_auto_entry", True)                 # persistent override ON
    summary = engine.run_cycle(now_ms=breakout_rows()[-1][0] + H + 1000)
    assert summary["opened"] == 1                     # entry taken despite cfg default off
    assert not any("auto-entry disabled" in (s["reject_reason"] or "")
                   for s in store.signals())


def test_kv_flag_off_blocks_entries_even_when_config_on(tmp_path):
    engine, store, cfg = make(tmp_path, cfg_auto_entry=True)
    store.set("lab_auto_entry", False)                # persistent override OFF
    summary = engine.run_cycle(now_ms=breakout_rows()[-1][0] + H + 1000)
    assert summary["opened"] == 0
    assert any("auto-entry disabled" in (s["reject_reason"] or "") for s in store.signals())


def test_unset_flag_falls_back_to_config(tmp_path):
    engine, store, cfg = make(tmp_path, cfg_auto_entry=True)
    assert store.get("lab_auto_entry") is None        # unset -> cfg default (True) applies
    summary = engine.run_cycle(now_ms=breakout_rows()[-1][0] + H + 1000)
    assert summary["opened"] == 1


def test_api_reports_the_effective_flag(tmp_path):
    from paperbot_pro.api import compute_lab
    engine, store, cfg = make(tmp_path, cfg_auto_entry=False)
    assert compute_lab(store, cfg)["status"]["auto_entry"] is False
    store.set("lab_auto_entry", True)
    assert compute_lab(store, cfg)["status"]["auto_entry"] is True


def test_health_and_settings_reflect_the_effective_lab_flag(tmp_path):
    """The health lab badge and /api/settings must show the same effective
    auto-entry the engine uses — not the stale config default."""
    from fastapi.testclient import TestClient
    from paperbot_pro.api import create_app
    from paperbot_pro.config import ProSettings
    pro = replace(ProSettings(), db_path=str(tmp_path / "pro.sqlite"),
                  legacy_db_path=str(tmp_path / "paper.sqlite"),
                  validation_report_path=str(tmp_path / "v.json"))
    lab = replace(LabSettings(), db_path=str(tmp_path / "lab.sqlite"), main_db_path=pro.db_path)
    LabStore(lab.db_path, lab).set("lab_auto_entry", True)
    client = TestClient(create_app(pro, lab))
    assert client.get("/api/health").json()["engines"]["lab"]["auto_entry_enabled"] is True
    assert client.get("/api/settings").json()["lab_auto_entry"] is True
