import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.engine import LabEngine
from paperbot_pro.lab.store import LabStore

H = 3_600_000
SYMBOL = 'TST/USDT:USDT'
INSTRUMENT = {'symbol': SYMBOL, 'exchange': 'fake', 'taker_fee': 0.0006,
              'maint_margin_rate': 0.005, 'tick_size': 0.1, 'lot_size': 0.001}


def breakout_rows(n=100, base=100.0, break_now=True):
    rows = [[i * H, base, base + 0.5, base - 0.5, base, 100.0] for i in range(n - 1)]
    if break_now:
        rows.append([(n - 1) * H, base, base + 3.5, base - 0.2, base + 3.2, 350.0])
    else:
        rows.append([(n - 1) * H, base, base + 0.5, base - 0.5, base, 100.0])
    return rows


class FakeLabMarket:
    def __init__(self, rows, last):
        self.rows = rows
        self.last = last
        self.down = False

    def candles(self, exchange, symbol, tf, limit):
        if self.down:
            raise ConnectionError('outage')
        return self.rows, 0.0

    def ticker(self, exchange, symbol):
        if self.down:
            raise ConnectionError('outage')
        return {'bid': self.last - 0.05, 'ask': self.last + 0.05, 'last': self.last}, 0.0

    def funding_rate(self, exchange, symbol):
        if self.down:
            raise ConnectionError('outage')
        return {'fundingRate': 0.0001}, 0.0


def make(tmp_path, auto_entry=True, rows=None, last=None):
    cfg = replace(LabSettings(), db_path=str(tmp_path / 'lab.sqlite'),
                  auto_entry=auto_entry)
    store = LabStore(cfg.db_path, cfg)
    rows = rows if rows is not None else breakout_rows()
    market = FakeLabMarket(rows, last=last if last is not None else rows[-1][4])
    engine = LabEngine(store, cfg, market=market,
                       instruments_provider=lambda: [INSTRUMENT])
    return engine, store, cfg, market


def test_signal_gated_without_lab_auto_entry(tmp_path):
    engine, store, cfg, market = make(tmp_path, auto_entry=False)
    now = breakout_rows()[-1][0] + H + 1000
    summary = engine.run_cycle(now_ms=now)
    assert summary['opened'] == 0 and summary['signals'] >= 1
    sig = store.signals()[0]
    assert sig['approved'] is False and 'auto-entry' in sig['reject_reason']


def test_entry_opens_open_ended_position_within_dollar_risk(tmp_path):
    engine, store, cfg, market = make(tmp_path)
    now = breakout_rows()[-1][0] + H + 1000
    summary = engine.run_cycle(now_ms=now)
    assert summary['opened'] == 1
    pos = store.position(SYMBOL)
    assert pos['target'] is None                       # no fixed take-profit cap
    assert pos['planned_risk_usd'] <= 5.0 + 1e-9
    assert pos['strategy'] == 'breakout'
    ledger = store.strategy_ledger()['breakout']
    assert ledger['cash_usd'] == pytest.approx(
        50.0 - pos['margin_usd'] - pos['entry_fee_usd'])
    others = [v for k, v in store.strategy_ledger().items() if k != 'breakout']
    assert all(v['cash_usd'] == pytest.approx(50.0) for v in others)  # isolation


def test_trailing_stop_ratchets_and_never_widens(tmp_path):
    engine, store, cfg, market = make(tmp_path)
    rows = market.rows
    now = rows[-1][0] + H + 1000
    engine.run_cycle(now_ms=now)
    stop0 = store.position(SYMBOL)['stop']
    # favorable closed bar well above entry
    rows.append([rows[-1][0] + H, 103.2, 112.0, 103.0, 111.5, 200.0])
    market.last = 111.5
    engine.run_cycle(now_ms=now + H)
    stop1 = store.position(SYMBOL)['stop']
    assert stop1 > stop0
    # pullback bar: stop must NOT widen
    rows.append([rows[-1][0] + H, 111.5, 111.8, 105.6, 105.8, 150.0])
    market.last = 105.8
    engine.run_cycle(now_ms=now + 2 * H)
    assert store.position(SYMBOL) is None or store.position(SYMBOL)['stop'] >= stop1


def test_breach_triggers_emergency_exit_and_lock_persists_restart(tmp_path):
    engine, store, cfg, market = make(tmp_path)
    now = breakout_rows()[-1][0] + H + 1000
    engine.run_cycle(now_ms=now)
    pos = store.position(SYMBOL)
    assert pos is not None
    # a single 10x isolated position caps its loss at ~margin (<$50), so the
    # realistic breach path is a previously raised high-water mark; simulate
    # prior gains then a reversal: peak 580 -> threshold 530 > equity ~500.
    store.set('peak_equity', 580.0)
    summary = engine.run_cycle(now_ms=now + 60_000)
    assert store.get('lab_locked') is True
    assert store.position(SYMBOL) is None              # emergency-exited
    trade = store.trades()[0]
    assert trade['exit_reason'].startswith('EMERGENCY')
    assert trade['net_pnl_usd'] < 0                    # round-trip costs recorded

    engine2, store2 = LabEngine(LabStore(cfg.db_path, cfg), cfg, market=market,
                                instruments_provider=lambda: [INSTRUMENT]), None
    assert engine2.db.get('lab_locked') is True        # restart: still locked
    rows2 = breakout_rows(n=120)
    market.rows = rows2
    market.last = rows2[-1][4]
    summary2 = engine2.run_cycle(now_ms=rows2[-1][0] + H + 1000)
    assert summary2['opened'] == 0                     # entries stay locked
    assert any('lock' in (s['reject_reason'] or '').lower()
               for s in engine2.db.signals())


def test_breach_during_outage_defers_exit_honestly(tmp_path):
    engine, store, cfg, market = make(tmp_path)
    now = breakout_rows()[-1][0] + H + 1000
    engine.run_cycle(now_ms=now)
    pos = store.position(SYMBOL)
    # equity already marked; simulate: lock manually via governor breach with
    # stale marks is impossible without quotes -> engine must NOT fabricate.
    crash_price = pos['entry_price'] - (55.0 / pos['qty'])
    market.last = max(crash_price, 1.0)
    engine.run_cycle(now_ms=now + 60_000)              # breach + lock with live quotes? no:
    # make the breach happen first, then outage BEFORE emergency exit retry:
    # (if already closed above, recreate scenario fresh)
    if store.position(SYMBOL) is None:
        # fresh scenario: new store with open position and pre-set lock
        engine, store, cfg, market = make(tmp_path / 'b')
        engine.run_cycle(now_ms=now)
        pos = store.position(SYMBOL)
        store.set('lab_locked', True)
        store.set('lab_lock_reason', 'test breach')
    market.down = True
    summary = engine.run_cycle(now_ms=now + 120_000)
    assert store.position(SYMBOL) is not None          # retained, not fabricated
    assert any('cannot be verified' in a['message'] or 'UNMONITORED' in a['message']
               for a in store.audit_log())
    market.down = False
    market.last = pos['entry_price']                   # recovery
    engine.run_cycle(now_ms=now + 180_000)
    assert store.position(SYMBOL) is None              # emergency exit on recovery
    assert store.trades()[0]['exit_reason'].startswith('EMERGENCY')


def test_equity_history_carries_peak_and_threshold(tmp_path):
    engine, store, cfg, market = make(tmp_path, auto_entry=False)
    now = breakout_rows()[-1][0] + H + 1000
    engine.run_cycle(now_ms=now)
    row = store.equity_history()[-1]
    assert row['equity_usd'] == pytest.approx(500.0)       # unified $500 base, no entries
    assert row['peak_equity_usd'] == pytest.approx(500.0)
    assert row['threshold_usd'] == pytest.approx(450.0)
