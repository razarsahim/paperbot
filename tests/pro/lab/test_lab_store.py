import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings, STRATEGIES
from paperbot_pro.lab.store import LabStore


def make(tmp_path, **kw):
    cfg = replace(LabSettings(), db_path=str(tmp_path / 'lab.sqlite'), **kw)
    return LabStore(cfg.db_path, cfg), cfg


def test_settings_rails():
    LabSettings().validate()
    assert len(STRATEGIES) == 5
    with pytest.raises(ValueError):
        LabSettings(max_risk_per_trade_usd=6.0).validate()      # > $5
    with pytest.raises(ValueError):
        LabSettings(max_combined_risk_usd=20.0).validate()      # > $15
    with pytest.raises(ValueError):
        LabSettings(max_open_positions=4).validate()            # > 3
    with pytest.raises(ValueError):
        LabSettings(leverage=20).validate()
    with pytest.raises(ValueError):
        LabSettings(trailing_drawdown_usd=0).validate()
    with pytest.raises(ValueError):
        LabSettings(allocation_per_strategy_usd=60.0).validate()  # 5x60 != 250


def test_store_initializes_five_strategy_ledgers(tmp_path):
    store, cfg = make(tmp_path)
    ledger = store.strategy_ledger()
    assert sorted(ledger) == sorted(s.key for s in STRATEGIES)
    for row in ledger.values():
        assert row['cash_usd'] == pytest.approx(50.0)
        assert row['realized_pnl_usd'] == 0.0
    assert store.get('peak_equity') == pytest.approx(250.0)
    assert store.get('lab_locked') is False
    assert store.total_cash() == pytest.approx(250.0)


def test_store_persists_peak_and_lock_across_reopen(tmp_path):
    store, cfg = make(tmp_path)
    store.set('peak_equity', 310.0)
    store.set('lab_locked', True)
    store.set('lab_lock_reason', 'trailing drawdown breached at 259.9')
    store.close()
    again, _ = make(tmp_path)
    assert again.get('peak_equity') == pytest.approx(310.0)
    assert again.get('lab_locked') is True
    assert 'breached' in again.get('lab_lock_reason')
