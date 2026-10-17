import json
import pytest
from dataclasses import replace
from paperbot_pro.research.config import ResearchSettings
from paperbot_pro.research.engine import ResearchEngine
from paperbot_pro.research.store import ResearchStore

H = 3_600_000
SYMBOL = 'TST/USDT:USDT'
INSTRUMENT = {'symbol': SYMBOL, 'exchange': 'bybit', 'taker_fee': 0.0006,
              'maint_margin_rate': 0.005, 'tick_size': 0.1, 'lot_size': 0.001}


def breakout_rows(n=70, base=100.0):
    rows = [[i * H, base, base + 0.4, base - 0.4, base, 100.0] for i in range(n - 1)]
    rows.append([(n - 1) * H, base, base + 3.5, base - 0.2, base + 3.2, 450.0])
    return rows


class FakeMarket:
    def __init__(self, rows, last):
        self.rows, self.last, self.down = rows, last, False

    def candles(self, ex, sym, tf, limit):
        if self.down: raise ConnectionError('outage')
        return self.rows, 0.0

    def ticker(self, ex, sym):
        if self.down: raise ConnectionError('outage')
        return {'bid': self.last - 0.05, 'ask': self.last + 0.05, 'last': self.last}, 0.0

    def funding_rate(self, ex, sym):
        if self.down: raise ConnectionError('outage')
        return {'fundingRate': 0.0001}, 0.0

    def orderbook(self, ex, sym):
        return None, 0.0

    def htf_trend(self, ex, sym, tf):
        return 'up'


def make(tmp_path, auto_entry=True):
    cfg = replace(ResearchSettings(), db_path=str(tmp_path / 'r.sqlite'),
                  live_state_path=str(tmp_path / 'r_live.json'), auto_entry=auto_entry)
    store = ResearchStore(cfg.db_path, cfg)
    rows = breakout_rows()
    market = FakeMarket(rows, last=rows[-1][4])
    engine = ResearchEngine(store, cfg, market=market,
                            instruments_provider=lambda: [INSTRUMENT])
    return engine, store, cfg, market


def test_gated_without_auto_entry(tmp_path):
    engine, store, cfg, market = make(tmp_path, auto_entry=False)
    now = breakout_rows()[-1][0] + H + 1000
    summary = engine.run_cycle(now_ms=now)
    assert summary['opened'] == 0 and summary['signals'] >= 1
    assert any('auto-entry' in (s['reject_reason'] or '') for s in store.signals())


def test_entry_respects_two_dollar_risk_and_strategy_ledger(tmp_path):
    engine, store, cfg, market = make(tmp_path)
    now = breakout_rows()[-1][0] + H + 1000
    summary = engine.run_cycle(now_ms=now)
    assert summary['opened'] == 1
    pos = store.position(SYMBOL)
    assert pos['planned_risk_usd'] <= 2.0 + 1e-9
    assert pos['target'] is None
    ledger = store.strategy_ledger()[pos['strategy']]
    assert ledger['cash_usd'] == pytest.approx(50.0 - pos['margin_usd'] - pos['entry_fee_usd'])
    others = [v for k, v in store.strategy_ledger().items() if k != pos['strategy']]
    assert all(v['cash_usd'] == pytest.approx(50.0) for v in others)


def test_strategy_equity_floor_exits_and_locks(tmp_path):
    engine, store, cfg, market = make(tmp_path)
    now = breakout_rows()[-1][0] + H + 1000
    engine.run_cycle(now_ms=now)
    pos = store.position(SYMBOL)
    strat = pos['strategy']
    # simulate accumulated prior losses: this strategy's cash is now low enough
    # that cash + margin + current uPnL <= $30 floor (cumulative $20 loss)
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=? WHERE key=?",
                           (30.0 - pos['margin_usd'], strat))
    engine.run_cycle(now_ms=now + 60_000)
    assert store.strategy_status(strat)['level'] == 'locked'
    assert store.position(SYMBOL) is None            # the open position was exited on lock
    exits = [t for t in store.trades() if 'STRATEGY LOCK' in t['exit_reason']
             or 'STOP' in t['exit_reason']]
    assert exits
    # the locked strategy refuses new entries even on a fresh signal
    market.rows = breakout_rows(n=90)
    market.last = market.rows[-1][4]
    engine.run_cycle(now_ms=market.rows[-1][0] + H + 1000)
    assert not any(p['strategy'] == strat for p in store.open_positions())
    assert any(s['strategy'] == strat and not s['approved']
               and 'locked' in (s['reject_reason'] or '').lower()
               for s in store.signals())


def test_tick_through_stop_closes_once(tmp_path):
    engine, store, cfg, market = make(tmp_path)
    now = breakout_rows()[-1][0] + H + 1000
    engine.run_cycle(now_ms=now)
    engine.start_live_components(publisher_clock=lambda: 999.0)
    pos = store.position(SYMBOL)
    engine.on_live_ticker('TSTUSDT', {'markPrice': str(pos['stop'] - 1),
                                      'bid1Price': str(pos['stop'] - 1.1),
                                      'ask1Price': str(pos['stop'] - 0.9),
                                      'lastPrice': str(pos['stop'] - 1)},
                          now + 10_000, 'snapshot')
    assert store.position(SYMBOL) is None
    assert len(store.trades()) == 1 and 'STOP' in store.trades()[0]['exit_reason']


def test_lab_breach_emergency_exits_and_locks(tmp_path):
    engine, store, cfg, market = make(tmp_path)
    now = breakout_rows()[-1][0] + H + 1000
    engine.run_cycle(now_ms=now)
    store.set('peak_equity', 320.0)            # prior gains -> threshold 270 > ~250
    summary = engine.run_cycle(now_ms=now + 60_000)
    assert store.get('lab_locked') is True
    assert store.position(SYMBOL) is None
    assert store.trades()[0]['exit_reason'].startswith('EMERGENCY')


def test_feed_outage_skips_without_fabricating(tmp_path):
    engine, store, cfg, market = make(tmp_path)
    market.down = True
    summary = engine.run_cycle(now_ms=200 * H)
    assert summary['opened'] == 0 and summary['errors'] >= 1
    assert any('unavailable' in a['message'] for a in store.audit_log())
