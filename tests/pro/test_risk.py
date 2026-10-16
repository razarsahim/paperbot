import pytest
from dataclasses import replace
from paperbot_pro.config import ProSettings
from paperbot_pro.risk import RiskGovernor
from paperbot_pro.store import ProStore

H = 3_600_000


def make(tmp_path, **kw):
    cfg = replace(ProSettings(), **kw)
    store = ProStore(str(tmp_path / 'pro.sqlite'), cfg)
    return RiskGovernor(store, cfg), store, cfg


def planned(symbol='BTC/USDT:USDT', risk_usd=5.0, margin_usd=20.0):
    return {'symbol': symbol, 'planned_risk_usd': risk_usd, 'margin_usd': margin_usd,
            'entry_fee_usd': 0.1, 'sleeve': 'core'}


def open_fake_position(store, symbol, risk_usd=5.0, margin_usd=20.0):
    with store.conn:
        store.conn.execute(
            """INSERT INTO positions(symbol, side, leverage, qty, entry_price, margin_usd,
               notional_usd, stop, initial_stop, target, liq_price_est, entry_fee_usd,
               funding_paid_usd, planned_risk_usd, planned_risk_pct, sleeve, opened_ms,
               signal_bar_ms, rationale) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (symbol, 'long', 10.0, 0.1, 100.0, margin_usd, margin_usd * 10, 95.0, 95.0,
             110.0, 90.5, 0.06, 0.0, risk_usd, risk_usd / 1000.0, 'core', 0, 0, 'TEST'))


def test_rejects_duplicate_symbol(tmp_path):
    gov, store, cfg = make(tmp_path)
    open_fake_position(store, 'BTC/USDT:USDT')
    verdict = gov.approve(planned(), equity=1000.0, now_ms=12 * H)
    assert not verdict.approved and 'already open' in verdict.reason


def test_rejects_when_slots_full(tmp_path):
    gov, store, cfg = make(tmp_path)
    for s in ('A/USDT:USDT', 'B/USDT:USDT', 'C/USDT:USDT'):
        open_fake_position(store, s, risk_usd=1.0)
    verdict = gov.approve(planned('D/USDT:USDT', risk_usd=1.0), equity=1000.0, now_ms=12 * H)
    assert not verdict.approved and 'position limit' in verdict.reason


def test_rejects_combined_risk_over_ceiling(tmp_path):
    gov, store, cfg = make(tmp_path)
    open_fake_position(store, 'A/USDT:USDT', risk_usd=6.0)
    open_fake_position(store, 'B/USDT:USDT', risk_usd=6.0)
    verdict = gov.approve(planned('C/USDT:USDT', risk_usd=5.0), equity=1000.0, now_ms=12 * H)
    assert not verdict.approved and 'combined' in verdict.reason  # 17 > 15 (1.5%)
    ok = gov.approve(planned('C/USDT:USDT', risk_usd=2.0), equity=1000.0, now_ms=12 * H)
    assert ok.approved


def test_daily_lock_sticky_and_clears_next_utc_day(tmp_path):
    gov, store, cfg = make(tmp_path)
    gov.update_locks(equity=1000.0, now_ms=12 * H)      # day 0 start
    gov.update_locks(equity=975.0, now_ms=13 * H)       # -2.5% intraday
    verdict = gov.approve(planned(), equity=975.0, now_ms=14 * H)
    assert not verdict.approved and 'daily' in verdict.reason.lower()
    gov.update_locks(equity=1000.0, now_ms=15 * H)      # recovers same day
    verdict = gov.approve(planned(), equity=1000.0, now_ms=15 * H)
    assert not verdict.approved, 'daily lock must stick all UTC day'
    gov.update_locks(equity=1000.0, now_ms=25 * H)      # next UTC day
    assert gov.approve(planned(), equity=1000.0, now_ms=25 * H).approved


def test_total_drawdown_pause_requires_manual_reset(tmp_path):
    gov, store, cfg = make(tmp_path)
    gov.update_locks(equity=1000.0, now_ms=12 * H)
    gov.update_locks(equity=940.0, now_ms=13 * H)       # -6% from peak
    verdict = gov.approve(planned(), equity=2000.0, now_ms=40 * H)
    assert not verdict.approved and 'review' in verdict.reason.lower()
    assert store.get('locked_total') is True            # survives equity recovery


def test_breach_rejects_entry_within_same_cycle_before_locks_persisted(tmp_path):
    """Review I3: a mid-cycle equity breach must gate entries immediately,
    not only after update_locks runs at cycle end."""
    gov, store, cfg = make(tmp_path)
    gov.update_locks(equity=1000.0, now_ms=12 * H)   # anchors day_start/peak
    verdict = gov.approve(planned(), equity=975.0, now_ms=12 * H + 60_000)
    assert not verdict.approved and 'daily' in verdict.reason.lower()
    verdict = gov.approve(planned(), equity=940.0, now_ms=12 * H + 60_000)
    assert not verdict.approved and 'review' in verdict.reason.lower()


def test_hype_sleeve_watch_only_and_loss_cap(tmp_path):
    gov, store, cfg = make(tmp_path)
    hype = dict(planned('PEPE/USDT:USDT', risk_usd=2.0, margin_usd=10.0), sleeve='hype')
    verdict = gov.approve(hype, equity=1000.0, now_ms=12 * H)
    assert not verdict.approved and 'watch' in verdict.reason.lower()

    gov2, store2, cfg2 = make(tmp_path / 'b', hype_watch_only=False)
    store2.set('hype_cumulative_loss_usd', 29.0)
    v2 = gov2.approve(dict(hype), equity=1000.0, now_ms=12 * H)
    assert not v2.approved and 'cumulative loss cap' in v2.reason


def test_rejects_insufficient_sleeve_margin(tmp_path):
    gov, store, cfg = make(tmp_path)
    store.set('cash_core', 15.0)
    verdict = gov.approve(planned(margin_usd=20.0), equity=1000.0, now_ms=12 * H)
    assert not verdict.approved and 'margin' in verdict.reason


def test_every_decision_is_logged(tmp_path):
    gov, store, cfg = make(tmp_path)
    gov.approve(planned(), equity=1000.0, now_ms=12 * H, symbol_action=('BTC/USDT:USDT', 'long'))
    open_fake_position(store, 'BTC/USDT:USDT')
    gov.approve(planned(), equity=1000.0, now_ms=13 * H, symbol_action=('BTC/USDT:USDT', 'long'))
    logged = store.signals()
    assert len(logged) == 2
    assert logged[0]['approved'] is False and logged[1]['approved'] is True
