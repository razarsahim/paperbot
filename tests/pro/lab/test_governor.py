import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.governor import LabGovernor
from paperbot_pro.lab.store import LabStore

H = 3_600_000


def make(tmp_path):
    cfg = replace(LabSettings(), db_path=str(tmp_path / 'lab.sqlite'))
    store = LabStore(cfg.db_path, cfg)
    return LabGovernor(store, cfg), store, cfg


def planned(symbol='BTC/USDT:USDT', risk=4.0, margin=20.0, strategy='trend'):
    return {'symbol': symbol, 'strategy': strategy, 'planned_risk_usd': risk,
            'margin_usd': margin, 'entry_fee_usd': 0.05}


def fake_position(store, symbol, strategy='trend', risk=4.0, margin=20.0):
    with store.conn:
        store.conn.execute(
            """INSERT INTO positions(strategy, symbol, side, leverage, qty, entry_price,
               margin_usd, notional_usd, stop, initial_stop, target, liq_price_est,
               entry_fee_usd, planned_risk_usd, opened_ms, signal_bar_ms, rationale,
               exchange, taker_fee) VALUES(?,?,?,?,?,?,?,?,?,?,NULL,?,?,?,?,?,?,?,?)""",
            (strategy, symbol, 'long', 10.0, 0.2, 100.0, margin, margin * 10,
             95.0, 95.0, 90.5, 0.05, risk, 0, 0, 'T', 'fake', 0.0006))


def test_hwm_examples_from_spec(tmp_path):
    gov, store, cfg = make(tmp_path)
    for equity, want_threshold in ((250.0, 200.0), (300.0, 250.0),
                                   (350.0, 300.0), (400.0, 350.0)):
        state = gov.update_hwm(equity, now_ms=1000)
        assert state['peak_equity'] == pytest.approx(equity)
        assert state['threshold'] == pytest.approx(want_threshold)
        assert state['breached'] is False


def test_threshold_never_decreases_even_across_restart(tmp_path):
    gov, store, cfg = make(tmp_path)
    gov.update_hwm(330.0, now_ms=1000)
    state = gov.update_hwm(290.0, now_ms=2000)     # reversal, above threshold 280
    assert state['peak_equity'] == pytest.approx(330.0)
    assert state['threshold'] == pytest.approx(280.0)
    assert state['breached'] is False
    store.close()
    gov2, store2, _ = make(tmp_path)               # restart
    state = gov2.update_hwm(300.0, now_ms=3000)
    assert state['peak_equity'] == pytest.approx(330.0)
    assert state['threshold'] == pytest.approx(280.0)


def test_breach_locks_atomically_and_recovery_does_not_unlock(tmp_path):
    gov, store, cfg = make(tmp_path)
    gov.update_hwm(320.0, now_ms=1000)
    state = gov.update_hwm(269.9, now_ms=2000)     # below 270 threshold
    assert state['breached'] is True
    assert store.get('lab_locked') is True
    assert 'breach' in store.get('lab_lock_reason').lower()
    state = gov.update_hwm(400.0, now_ms=3000)     # roaring recovery
    assert store.get('lab_locked') is True          # still locked: manual review only
    verdict = gov.approve(planned(), now_ms=4000)
    assert not verdict.approved and 'lock' in verdict.reason.lower()


def test_gap_far_below_threshold_records_honest_loss(tmp_path):
    gov, store, cfg = make(tmp_path)
    gov.update_hwm(250.0, now_ms=1000)
    state = gov.update_hwm(150.0, now_ms=2000)     # gap: $50 beyond the threshold
    assert state['breached'] is True
    assert state['excess_loss_usd'] == pytest.approx(50.0)


def test_manual_reset_requires_lock_and_reanchors_peak(tmp_path):
    gov, store, cfg = make(tmp_path)
    with pytest.raises(ValueError):
        gov.reset(current_equity=250.0, note='nothing to reset')
    gov.update_hwm(300.0, now_ms=1000)
    gov.update_hwm(249.0, now_ms=2000)
    assert store.get('lab_locked') is True
    gov.reset(current_equity=249.0, note='reviewed drawdown, restarting experiment')
    assert store.get('lab_locked') is False
    state = gov.update_hwm(249.0, now_ms=3000)
    assert state['peak_equity'] == pytest.approx(249.0)   # re-anchored
    assert state['threshold'] == pytest.approx(199.0)
    assert state['breached'] is False
    assert any('reset' in a['message'].lower() for a in store.audit_log())


def test_entry_rails_slots_combined_risk_cash_duplicates(tmp_path):
    gov, store, cfg = make(tmp_path)
    gov.update_hwm(250.0, now_ms=1000)
    assert gov.approve(planned(), now_ms=1000).approved
    fake_position(store, 'A/USDT:USDT', risk=5.5)  # inserted directly: simulates drift
    fake_position(store, 'B/USDT:USDT', risk=5.5)
    verdict = gov.approve(planned('C/USDT:USDT', risk=4.5), now_ms=2000)
    assert not verdict.approved and 'combined' in verdict.reason     # 15.5 > 15
    assert gov.approve(planned('C/USDT:USDT', risk=3.5), now_ms=2000).approved
    fake_position(store, 'C/USDT:USDT', risk=3.5)
    verdict = gov.approve(planned('D/USDT:USDT', risk=0.5), now_ms=3000)
    assert not verdict.approved and 'position limit' in verdict.reason
    verdict = gov.approve(planned('A/USDT:USDT', risk=0.5), now_ms=3000)
    assert not verdict.approved and 'already open' in verdict.reason
    verdict = gov.approve(planned('E/USDT:USDT', risk=6.0), now_ms=3000)
    assert not verdict.approved and '$5' in verdict.reason


def test_strategy_sleeve_cash_is_isolated(tmp_path):
    gov, store, cfg = make(tmp_path)
    gov.update_hwm(250.0, now_ms=1000)
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=10 WHERE key='trend'")
    verdict = gov.approve(planned(margin=20.0, strategy='trend'), now_ms=2000)
    assert not verdict.approved and 'strategy cash' in verdict.reason
    assert gov.approve(planned(margin=20.0, strategy='breakout'), now_ms=2000).approved
