import pytest
from dataclasses import replace
from paperbot_pro.research.config import STRATEGIES, ResearchSettings
from paperbot_pro.research.governor import ResearchGovernor
from paperbot_pro.research.store import ResearchStore

H = 3_600_000


def make(tmp_path, **kw):
    cfg = replace(ResearchSettings(), db_path=str(tmp_path / 'research.sqlite'), **kw)
    store = ResearchStore(cfg.db_path, cfg)
    return ResearchGovernor(store, cfg), store, cfg


def planned(strategy='regime_trend', symbol='BTC/USDT:USDT', risk=1.5, margin=10.0):
    return {'strategy': strategy, 'symbol': symbol, 'planned_risk_usd': risk,
            'margin_usd': margin, 'entry_fee_usd': 0.02}


def fake_pos(store, strategy, symbol, risk=1.5, margin=10.0, cluster='BTC'):
    with store.conn:
        store.conn.execute(
            """INSERT INTO positions(strategy, symbol, side, leverage, qty, entry_price,
               margin_usd, notional_usd, stop, initial_stop, target, liq_price_est,
               entry_fee_usd, planned_risk_usd, opened_ms, signal_bar_ms, rationale,
               exchange, taker_fee, corr_cluster)
               VALUES(?,?,?,10,0.1,100,?,?,95,95,NULL,90.5,0.02,?,0,0,'T','bybit',0.0006,?)""",
            (strategy, symbol, 'long', margin, margin * 10, risk, cluster))


def test_settings_and_five_strategies():
    ResearchSettings().validate()
    assert len(STRATEGIES) == 5
    with pytest.raises(ValueError):
        ResearchSettings(max_risk_per_trade_usd=3.0).validate()   # > $2
    with pytest.raises(ValueError):
        ResearchSettings(strategy_lock_floor_usd=25.0).validate()  # must be $30
    with pytest.raises(ValueError):
        ResearchSettings(allocation_per_strategy_usd=60.0).validate()  # 5x60 != 250


def test_store_five_ledgers_and_lab_init(tmp_path):
    gov, store, cfg = make(tmp_path)
    ledger = store.strategy_ledger()
    assert sorted(ledger) == sorted(s.key for s in STRATEGIES)
    assert all(r['cash_usd'] == pytest.approx(50.0) for r in ledger.values())
    assert all(r['locked'] == 0 for r in ledger.values())
    assert store.get('peak_equity') == pytest.approx(250.0)
    assert store.total_cash() == pytest.approx(250.0)


def test_per_trade_risk_cap_two_dollars(tmp_path):
    gov, store, cfg = make(tmp_path)
    assert gov.approve(planned(risk=2.0), now_ms=0).approved
    v = gov.approve(planned(risk=2.5), now_ms=0)
    assert not v.approved and '$2' in v.reason


def test_strategy_warning_and_lock_thresholds(tmp_path):
    gov, store, cfg = make(tmp_path)
    # $40 -> warning but still tradable
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=40 WHERE key='regime_trend'")
    assert store.strategy_status('regime_trend')['level'] == 'warning'
    assert gov.approve(planned(margin=5.0), now_ms=0).approved
    # $30 floor (=$20 cumulative loss) -> locked, no new entries
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=30 WHERE key='regime_trend'")
    status = store.strategy_status('regime_trend')
    assert status['level'] == 'locked'
    v = gov.approve(planned(margin=5.0), now_ms=0)
    assert not v.approved and 'locked' in v.reason.lower()


def test_strategy_lock_is_equity_based_not_per_trade(tmp_path):
    """The $20 figure is cumulative loss from $50, i.e. a $30 equity floor
    on net mark-to-market equity, not a per-trade risk amount."""
    gov, store, cfg = make(tmp_path)
    # strategy equity (cash + margin + uPnL) drops to $30 via unrealized loss
    fake_pos(store, 'regime_trend', 'BTC/USDT:USDT', margin=10.0)
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=25 WHERE key='regime_trend'")
    # cash 25 + margin 10 + uPnL -5 = 30 equity -> at the floor
    breaches = gov.strategy_equity_breaches({'regime_trend': 30.0})
    assert 'regime_trend' in breaches


def test_no_cross_strategy_borrowing(tmp_path):
    gov, store, cfg = make(tmp_path)
    # above the $30 lock floor but can't cover a $40 margin from its own $35
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=35 WHERE key='regime_trend'")
    v = gov.approve(planned(strategy='regime_trend', margin=40.0), now_ms=0)
    assert not v.approved and 'cash' in v.reason.lower()
    # another strategy with funds is unaffected
    assert gov.approve(planned(strategy='volatility_breakout', margin=10.0), now_ms=0).approved


def test_correlated_overlap_rejected(tmp_path):
    gov, store, cfg = make(tmp_path)
    fake_pos(store, 'regime_trend', 'BTC/USDT:USDT', cluster='BTC')
    v = gov.approve(dict(planned(strategy='trend_pullback', symbol='BTCDOM/USDT:USDT'),
                         corr_cluster='BTC'), now_ms=0)
    assert not v.approved and 'correl' in v.reason.lower()
    assert gov.approve(dict(planned(strategy='trend_pullback', symbol='ETH/USDT:USDT'),
                            corr_cluster='ETH'), now_ms=0).approved


def test_lab_trailing_hwm_breach_locks_all(tmp_path):
    gov, store, cfg = make(tmp_path)
    gov.update_hwm(300.0, now_ms=1000)       # peak 300, threshold 250
    s = gov.update_hwm(249.0, now_ms=2000)   # breach
    assert s['breached'] and store.get('lab_locked') is True
    s = gov.update_hwm(400.0, now_ms=3000)   # recovery doesn't unlock
    assert store.get('lab_locked') is True
    v = gov.approve(planned(), now_ms=4000)
    assert not v.approved and 'lab' in v.reason.lower()


def test_lab_threshold_never_decreases_across_restart(tmp_path):
    gov, store, cfg = make(tmp_path)
    gov.update_hwm(320.0, now_ms=1000)
    store.close()
    gov2, store2, _ = make(tmp_path)
    s = gov2.update_hwm(280.0, now_ms=2000)
    assert s['peak_equity'] == pytest.approx(320.0)
    assert s['threshold'] == pytest.approx(270.0)
