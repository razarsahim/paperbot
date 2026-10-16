import pytest
from paperbot_pro.config import ProSettings
from paperbot_pro.store import ProStore


def make(tmp_path):
    cfg = ProSettings()
    return ProStore(str(tmp_path / 'pro.sqlite'), cfg), cfg


def test_settings_validation_rejects_unsafe_values():
    ProSettings().validate()
    with pytest.raises(ValueError):
        ProSettings(risk_per_trade=0.02).validate()       # >1% per trade
    with pytest.raises(ValueError):
        ProSettings(leverage=25).validate()               # cap 10x
    with pytest.raises(ValueError):
        ProSettings(core_sleeve_usd=950, hype_sleeve_usd=100).validate()  # sleeves != total
    with pytest.raises(ValueError):
        ProSettings(max_combined_risk=0.10).validate()


def test_store_initializes_sleeves_and_lock_state(tmp_path):
    store, cfg = make(tmp_path)
    assert store.get('cash_core') == pytest.approx(900.0)
    assert store.get('cash_hype') == pytest.approx(100.0)
    assert store.get('peak_equity') == pytest.approx(1000.0)
    assert store.get('locked_total') is False
    assert store.get('locked_daily') is False
    assert store.open_positions() == []
    assert store.trades() == []


def test_store_audit_and_signal_log_roundtrip(tmp_path):
    store, cfg = make(tmp_path)
    store.audit('warning', 'risk', 'combined risk ceiling reached')
    store.log_signal(1_000_000, 'BTC/USDT:USDT', 'long', False, 'daily lock', 'ema reclaim')
    rows = store.audit_log()
    assert rows[0]['category'] == 'risk'
    sig = store.signals()[0]
    assert sig['approved'] is False and sig['reject_reason'] == 'daily lock'


def test_store_persists_across_reopen(tmp_path):
    store, cfg = make(tmp_path)
    store.set('cash_core', 850.0)
    store.record_equity(123_000, 950.0, 850.0, 100.0, 0.0, 0.0)
    store.close()
    again, _ = make(tmp_path)
    assert again.get('cash_core') == pytest.approx(850.0)
    assert again.equity_history()[-1]['equity_usd'] == pytest.approx(950.0)
