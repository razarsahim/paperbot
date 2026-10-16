"""Multi-day simulated soak: open -> hold across midnights, funding
boundaries, an outage and a process restart -> exit. Asserts continuous
state integrity without any live network."""
import pytest
from dataclasses import replace
from paperbot_pro.config import ProSettings
from paperbot_pro.engine import ProEngine
from paperbot_pro.store import ProStore
from tests.pro.test_cycle import FakeMarket, reclaim_series, seed, SYMBOL

H = 3_600_000


class ScriptedMarket(FakeMarket):
    """Serves a scripted last-price per call; can simulate outages."""
    def __init__(self, rows, prices):
        super().__init__(rows, last=prices[0])
        self.prices = list(prices)
        self.i = 0
        self.down = False

    def step(self, price=None, down=False):
        self.down = down
        if price is not None:
            self.last = price

    def ticker(self, exchange, symbol):
        if self.down:
            raise ConnectionError('simulated outage')
        return super().ticker(exchange, symbol)

    def candles(self, exchange, symbol, tf, limit):
        if self.down:
            raise ConnectionError('simulated outage')
        return super().candles(exchange, symbol, tf, limit)


def test_three_day_soak_with_outage_and_restart(tmp_path):
    cfg, store = seed(tmp_path, auto_entry=True, with_artifact=True)
    rows = reclaim_series()                       # signal on bar 91
    start = rows[-1][0] + H + 1000                # ~hour 92 (day 3)
    market = ScriptedMarket(rows, prices=[rows[-1][4]])
    engine = ProEngine(store, cfg, market=market)
    assert engine.run_cycle(now_ms=start)['opened'] == 1
    pos = store.position(SYMBOL)
    hold_price = (pos['entry_price'] + pos['target']) / 2 * 0.99  # safely inside

    outage_hours = range(24, 36)                  # a 12h outage on day 2 of the hold
    restart_at = 48
    for hour in range(1, 72):
        now = start + hour * H
        if hour == restart_at:                    # simulated process restart
            engine = ProEngine(store, cfg, market=market)
        market.step(price=hold_price, down=hour in outage_hours)
        engine.run_cycle(now_ms=now)
        assert len(store.open_positions()) <= 1   # never duplicated

    pos = store.position(SYMBOL)
    assert pos is not None, 'position lost during soak'
    # every 8h boundary inside the monitored window must have exactly one
    # funding event — including the ones that fell inside the outage
    events = [r[0] for r in store.conn.execute(
        'SELECT funding_ts_ms FROM funding_events ORDER BY funding_ts_ms')]
    first_boundary = (pos['opened_ms'] // (8 * H) + 1) * (8 * H)
    expected = list(range(first_boundary, start + 71 * H + 1, 8 * H))
    assert events == expected
    assert len(events) == len(set(events))
    # outage was loud, not silent
    assert any('UNMONITORED' in a['message'] for a in store.audit_log(500))
    # equity snapshots only for successful cycles; none fabricated during outage
    history = store.equity_history()
    assert len(history) == 72 - len(list(outage_hours))
    # finally let it hit the target and verify clean close + accounting
    market.step(price=pos['target'] * 1.01, down=False)
    summary = engine.run_cycle(now_ms=start + 72 * H)
    assert summary['closed'] == 1
    trade = store.trades()[0]
    assert trade['exit_reason'] == 'TARGET'
    assert trade['funding_usd'] == pytest.approx(sum(
        r[0] for r in store.conn.execute('SELECT amount_usd FROM funding_events')))
    cash = float(store.get('cash_core'))
    assert cash == pytest.approx(750.0 + trade['net_pnl_usd'])
