import json
import pytest
from dataclasses import replace
from paperbot.strategy import ema
from paperbot_pro.config import ProSettings
from paperbot_pro.engine import ProEngine
from paperbot_pro.store import ProStore

H = 3_600_000
SYMBOL = 'TST/USDT:USDT'


def reclaim_series(n=90):
    rows, price = [], 100.0
    for i in range(n):
        o = price
        price += 0.6
        rows.append([i * H, o, max(o, price) + 0.2, min(o, price) - 0.2, price, 10.0])
    closes = [r[4] for r in rows]
    e20 = ema(closes, 20)[-1]
    dip_close = e20 - 2.0
    rows.append([n * H, rows[-1][4], rows[-1][4] + 0.2, dip_close - 0.5, dip_close, 10.0])
    reclaim_close = e20 + 3.0
    rows.append([(n + 1) * H, dip_close, reclaim_close + 0.5, dip_close - 0.2, reclaim_close, 10.0])
    return rows


class FakeMarket:
    def __init__(self, candles_rows, last):
        self.rows = candles_rows
        self.last = last

    def candles(self, exchange, symbol, tf, limit):
        return self.rows, 0.0

    def ticker(self, exchange, symbol):
        return {'bid': self.last - 0.05, 'ask': self.last + 0.05, 'last': self.last}, 0.0

    def funding_rate(self, exchange, symbol):
        return {'fundingRate': 0.0001}, 0.0


def seed(tmp_path, auto_entry, with_artifact):
    cfg = replace(ProSettings(), auto_entry=auto_entry,
                  db_path=str(tmp_path / 'pro.sqlite'),
                  validation_report_path=str(tmp_path / 'validation_report.json'))
    store = ProStore(cfg.db_path, cfg)
    with store.conn:
        store.conn.execute("INSERT INTO universe VALUES('testcoin',1,'TST','Testcoin',100,1,1e9,1e8,1000)")
        store.conn.execute(
            "INSERT INTO instruments VALUES('testcoin','fake',?,1,NULL,0.0006,0.005,0.1,0.001,1000)",
            (SYMBOL,))
    if with_artifact:
        from tests.pro.conftest import write_valid_artifact
        write_valid_artifact(cfg)
    return cfg, store


def test_cycle_gates_execution_without_validation(tmp_path):
    cfg, store = seed(tmp_path, auto_entry=True, with_artifact=False)
    rows = reclaim_series()
    now = rows[-1][0] + H + 1000
    market = FakeMarket(rows, last=rows[-1][4])
    engine = ProEngine(store, cfg, market=market)
    summary = engine.run_cycle(now_ms=now)
    assert summary['signals'] == 1 and summary['opened'] == 0
    sig = store.signals()[0]
    assert sig['approved'] is False and 'validation' in sig['reject_reason']
    assert store.open_positions() == []


def test_cycle_opens_then_liquidation_closes_and_books_trade(tmp_path):
    cfg, store = seed(tmp_path, auto_entry=True, with_artifact=True)
    rows = reclaim_series()
    now = rows[-1][0] + H + 1000
    last = rows[-1][4]
    engine = ProEngine(store, cfg, market=FakeMarket(rows, last=last))
    summary = engine.run_cycle(now_ms=now)
    assert summary['opened'] == 1, store.signals()
    pos = store.position(SYMBOL)
    assert pos is not None and pos['side'] == 'long'
    assert pos['planned_risk_usd'] <= 1000 * cfg.risk_per_trade + 1e-9
    assert len(store.equity_history()) == 1

    crash = FakeMarket(rows, last=pos['liq_price_est'] * 0.9)  # gap through liq
    engine2 = ProEngine(store, cfg, market=crash)
    summary2 = engine2.run_cycle(now_ms=now + 60_000)
    assert summary2['closed'] == 1
    trade = store.trades()[0]
    assert trade['exit_reason'] == 'LIQUIDATION'
    assert float(store.get('cash_core')) > 0  # loss capped at committed capital
    assert store.position(SYMBOL) is None
    # same bar cannot signal twice (no immediate revenge entry)
    assert summary2['signals'] == 0


def opened_position(tmp_path):
    cfg, store = seed(tmp_path, auto_entry=True, with_artifact=True)
    rows = reclaim_series()
    now = rows[-1][0] + H + 1000
    engine = ProEngine(store, cfg, market=FakeMarket(rows, last=rows[-1][4]))
    assert engine.run_cycle(now_ms=now)['opened'] == 1
    return cfg, store, rows, now


def test_position_still_managed_after_leaving_universe(tmp_path):
    """CRITICAL (review C1): a universe refresh or eligibility flip must not
    orphan an open position — stops/liquidation stay enforced."""
    cfg, store, rows, now = opened_position(tmp_path)
    pos = store.position(SYMBOL)
    with store.conn:
        store.conn.execute("DELETE FROM universe")
        store.conn.execute("UPDATE instruments SET eligible=0")
    crash = FakeMarket(rows, last=pos['liq_price_est'] * 0.9)
    summary = ProEngine(store, cfg, market=crash).run_cycle(now_ms=now + 60_000)
    assert summary['closed'] == 1
    assert store.position(SYMBOL) is None
    assert store.trades()[0]['exit_reason'] == 'LIQUIDATION'


def test_position_without_instrument_metadata_alerts_unmonitored(tmp_path):
    cfg, store, rows, now = opened_position(tmp_path)
    with store.conn:
        store.conn.execute("DELETE FROM universe")
        store.conn.execute("DELETE FROM instruments")
    summary = ProEngine(store, cfg, market=FakeMarket(rows, last=1.0)).run_cycle(now_ms=now + 60_000)
    assert store.position(SYMBOL) is not None  # cannot price it, must not guess
    assert any('UNMONITORED' in a['message'] for a in store.audit_log())


def test_stale_ticker_blocks_new_entries(tmp_path):
    """Review I2: entries must not be priced from stale quotes."""
    cfg, store = seed(tmp_path, auto_entry=True, with_artifact=True)
    rows = reclaim_series()
    now = rows[-1][0] + H + 1000

    class StaleMarket(FakeMarket):
        def ticker(self, exchange, symbol):
            data, _ = super().ticker(exchange, symbol)
            return data, cfg.price_fresh_seconds + 60.0
    summary = ProEngine(store, cfg, market=StaleMarket(rows, last=rows[-1][4])).run_cycle(now_ms=now)
    assert summary['opened'] == 0
    sig = store.signals()[0]
    assert sig['approved'] is False and 'stale' in sig['reject_reason'].lower()


def test_missing_quote_side_blocks_entry_without_crashing(tmp_path):
    cfg, store = seed(tmp_path, auto_entry=True, with_artifact=True)
    rows = reclaim_series()
    now = rows[-1][0] + H + 1000

    class NoAskMarket(FakeMarket):
        def ticker(self, exchange, symbol):
            return {'bid': self.last - 0.05, 'ask': None, 'last': self.last}, 0.0
    summary = ProEngine(store, cfg, market=NoAskMarket(rows, last=rows[-1][4])).run_cycle(now_ms=now)
    assert summary['opened'] == 0
    assert any('quote' in (s['reject_reason'] or '') for s in store.signals())


def double_reclaim_series():
    """reclaim_series plus a second dip+reclaim so bar 93 signals again."""
    from paperbot.strategy import ema
    rows = reclaim_series()                      # signal on bar 91
    closes = [r[4] for r in rows]
    e20 = ema(closes, 20)[-1]
    n = len(rows)
    dip2 = e20 - 2.5
    rows.append([n * H, rows[-1][4], rows[-1][4] + 0.2, dip2 - 0.5, dip2, 10.0])
    closes2 = [r[4] for r in rows]
    e20b = ema(closes2, 20)[-1]
    reclaim2 = e20b + 3.0
    rows.append([(n + 1) * H, dip2, reclaim2 + 0.5, dip2 - 0.2, reclaim2, 10.0])
    return rows


def test_no_reentry_on_bar_that_closed_before_the_exit(tmp_path):
    """Backtest parity: after a stop-out/liquidation, a signal from a bar that
    had already closed BEFORE the exit must not re-enter; only a bar closing
    after the exit may."""
    cfg, store = seed(tmp_path, auto_entry=True, with_artifact=True)
    rows_open = reclaim_series()                      # bars 0..91
    now1 = rows_open[-1][0] + H + 1000
    engine = ProEngine(store, cfg, market=FakeMarket(rows_open, last=rows_open[-1][4]))
    assert engine.run_cycle(now_ms=now1)['opened'] == 1
    pos = store.position(SYMBOL)

    rows_again = double_reclaim_series()              # bar 93 signals again
    now2 = rows_again[-1][0] + H + 1000
    crash = FakeMarket(rows_again, last=pos['liq_price_est'] * 0.9)
    summary = ProEngine(store, cfg, market=crash).run_cycle(now_ms=now2)
    assert summary['closed'] == 1
    assert summary['opened'] == 0, 'revenge re-entry on a pre-exit bar'
    assert store.position(SYMBOL) is None
    assert any('re-entry cooldown' in (s['reject_reason'] or '') for s in store.signals())


def test_manual_pause_blocks_entries_and_shows_reason(tmp_path):
    cfg, store = seed(tmp_path, auto_entry=True, with_artifact=True)
    store.set('manual_pause', True)
    rows = reclaim_series()
    now = rows[-1][0] + H + 1000
    summary = ProEngine(store, cfg, market=FakeMarket(rows, last=rows[-1][4])).run_cycle(now_ms=now)
    assert summary['opened'] == 0
    assert any('paused' in (s['reject_reason'] or '').lower() for s in store.signals())


def test_cycle_skips_symbol_on_feed_failure_without_fabricating(tmp_path):
    cfg, store = seed(tmp_path, auto_entry=True, with_artifact=True)

    class DeadMarket:
        def candles(self, *a, **k):
            raise ConnectionError('down')
        def ticker(self, *a, **k):
            raise ConnectionError('down')
        def funding_rate(self, *a, **k):
            raise ConnectionError('down')

    engine = ProEngine(store, cfg, market=DeadMarket())
    summary = engine.run_cycle(now_ms=200 * H)
    assert summary['errors'] == 1 and summary['opened'] == 0
    assert any('unavailable' in a['message'] for a in store.audit_log())
    health = store.get('data_sources')
    assert health[0]['ok'] is False
