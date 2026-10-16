import pytest
from dataclasses import replace
from paperbot.config import Settings
from paperbot.engine import PaperEngine
from paperbot.models import Candle, Quote
from paperbot.store import Store
from paperbot.strategy import evaluate


def candles(n=120, close=100.0):
    return [Candle(i * 3_600_000, close, close + 2, close - 2, close, 1)
            for i in range(n)]


def make(tmp_path):
    cfg = replace(Settings(), min_bars=85)
    db = Store(str(tmp_path / 'paper.sqlite'), cfg.starting_balance, cfg.symbol)
    return PaperEngine(db, cfg)


def test_position_costs_and_initial_stop_risk_budget(tmp_path):
    bot = make(tmp_path)
    result = bot._enter(100, 1.0, 120 * 3_600_000, 119 * 3_600_000, 'TEST')
    assert 'SIMULATED BUY' in result
    pos = bot.db.position()
    assert pos['stop'] < pos['entry_price']
    assert pos['target'] > pos['entry_price']
    planned_exit = pos['stop'] * (1 - bot.cfg.slippage_rate)
    planned_net_loss = pos['qty'] * pos['entry_price'] + pos['entry_fee'] - (
        pos['qty'] * planned_exit * (1 - bot.cfg.fee_rate))
    assert planned_net_loss <= 1000 * bot.cfg.risk_per_trade + 1e-8
    assert bot.db.get('balance') >= -1e-8


def test_stop_exit_with_slippage_and_no_reentry_same_tick(tmp_path, monkeypatch):
    bot = make(tmp_path)
    bot._enter(100, 1, 3_600_000 * 118, 3_600_000 * 117, 'TEST')
    pos = bot.db.position()
    from paperbot.strategy import Signal
    monkeypatch.setattr('paperbot.engine.evaluate', lambda bars: Signal(True, 1, 'FAKE'))
    now = 120 * 3_600_000 + 20_000
    # Leave the latest bar at open ts 119; it closed only 20 sec ago.
    result = bot.tick(candles(), Quote(pos['stop'] - 0.1, pos['stop'], now), now)
    assert any('SIMULATED EXIT' in s for s in result)
    assert bot.db.position() is None
    assert len(bot.db.trades()) == 1
    assert bot.db.trades()[0]['net_pnl'] < 0
    assert not any('SIMULATED BUY' in s for s in result), 'No instant revenge entry'


def test_duplicate_bar_no_second_entry(tmp_path, monkeypatch):
    bot = make(tmp_path)
    from paperbot.strategy import Signal
    monkeypatch.setattr('paperbot.engine.evaluate', lambda bars: Signal(True, 1, 'FAKE'))
    now = 120 * 3_600_000 + 5_000
    quote = Quote(100, 100.1, now)
    first = bot.tick(candles(), quote, now)
    second = bot.tick(candles(), quote, now)
    assert sum('SIMULATED BUY' in e for e in first) == 1
    assert sum('SIMULATED BUY' in e for e in second) == 0
    assert bot.db.position() is not None


def test_restart_recovers_original_position(tmp_path):
    bot = make(tmp_path)
    bot._enter(100, 1, 1, 0, 'TEST')
    original = bot.db.position()
    bot.db.close()
    again = make(tmp_path)
    assert again.db.position() == original
    assert again.db.get('balance') < 1000


def test_never_widens_stop_even_high_volatility(tmp_path, monkeypatch):
    bot = make(tmp_path)
    bot._enter(100, 1, 3_600_000 * 118, 3_600_000 * 117, 'TEST')
    pos = bot.db.position()
    # Force a mark where profit is > 1R, but high ATR would suggest looser stop.
    b = candles(close=101.0)
    now = 120 * 3_600_000 + 5_000
    from paperbot.strategy import Signal
    monkeypatch.setattr('paperbot.engine.evaluate', lambda bars: Signal(False, 100.0, 'FAKE'))
    bot.tick(b, Quote(101.5, 101.6, now), now)
    assert bot.db.position()['stop'] >= pos['stop']


def test_stale_candle_blocks_entry(tmp_path, monkeypatch):
    bot = make(tmp_path)
    from paperbot.strategy import Signal
    monkeypatch.setattr('paperbot.engine.evaluate', lambda bars: Signal(True, 1, 'FAKE'))
    now = 130 * 3_600_000
    result = bot.tick(candles(), Quote(100, 100.1, now), now)
    assert bot.db.position() is None
    assert 'old' in str(result)


def test_stale_quote_fails_closed(tmp_path):
    bot = make(tmp_path)
    with pytest.raises(ValueError, match='Stale'):
        bot.tick(candles(), Quote(100, 100.2, 1), 130_000)


def test_bad_candle_gap_fails_closed(tmp_path):
    bot = make(tmp_path)
    b = candles()
    b[-1] = Candle(b[-1].timestamp + 3_600_000, 100, 102, 98, 100, 1)
    now = 121 * 3_600_000 + 5_000
    result = bot.tick(b, Quote(100, 100.1, now), now)
    assert 'irregular' in str(result)
    assert bot.db.position() is None


def test_total_drawdown_lock_prevents_entry(tmp_path, monkeypatch):
    bot = make(tmp_path)
    with bot.db.conn:
        bot.db.set('peak_equity', 1100.0)
    from paperbot.strategy import Signal
    monkeypatch.setattr('paperbot.engine.evaluate', lambda bars: Signal(True, 1, 'FAKE'))
    now = 120 * 3_600_000 + 5_000
    result = bot.tick(candles(), Quote(100, 100.1, now), now)
    assert bot.db.get('locked_total') is True
    assert bot.db.position() is None
    assert 'LOCK' in str(result)


def test_daily_lock_sticks_until_next_utc_day(tmp_path, monkeypatch):
    """README: daily 2% drawdown locks NEW entries until the next UTC day.

    The lock must NOT silently lift if equity recovers later the same day.
    """
    bot = make(tmp_path)
    from paperbot.strategy import Signal
    signal = {'buy': False}
    monkeypatch.setattr('paperbot.engine.evaluate',
                        lambda bars: Signal(signal['buy'], 1, 'FAKE'))

    def tick_at(hour):
        now = hour * 3_600_000 + 5_000
        return bot.tick(candles(hour), Quote(100.0, 100.1, now), now)

    tick_at(110)  # mid-UTC-day: initialises utc_day and day_start_equity=1000
    with bot.db.conn:
        bot.db.set('balance', 975.0)  # simulated 2.5% intraday loss
    result = tick_at(111)
    assert any('DAILY' in e for e in result)
    with bot.db.conn:
        bot.db.set('balance', 1000.0)  # equity recovers the same UTC day
    signal['buy'] = True
    result = tick_at(112)
    assert any('DAILY' in e for e in result), 'lock lifted intraday'
    assert bot.db.position() is None, 'entry allowed during daily lockout'
    result = tick_at(122)  # next UTC day: lock expires, entries allowed again
    assert not any('DAILY' in e for e in result)
    assert bot.db.position() is not None


def test_settings_invalid_risk_rejected():
    with pytest.raises(ValueError):
        replace(Settings(), risk_per_trade=0.20).validate()


def test_wide_spread_blocks_entry_but_allows_protective_exit(tmp_path, monkeypatch):
    bot = make(tmp_path)
    from paperbot.strategy import Signal
    monkeypatch.setattr('paperbot.engine.evaluate', lambda bars: Signal(True, 1, 'FAKE'))
    now = 120 * 3_600_000 + 5_000
    result = bot.tick(candles(), Quote(97, 100, now), now)
    assert bot.db.position() is None
    assert 'WIDE SPREAD' in str(result)

    other = make(tmp_path / 'second')
    other._enter(100, 1, 118 * 3_600_000, 117 * 3_600_000, 'TEST')
    result = other.tick(candles(), Quote(95, 100, now), now)
    assert 'SIMULATED EXIT' in str(result)
    assert other.db.position() is None


def test_entry_fail_safe_on_untrusted_bid_ask(tmp_path):
    bot = make(tmp_path)
    now = 120 * 3_600_000 + 5_000
    with pytest.raises(ValueError):
        bot.tick(candles(), Quote(101, 100, now), now)
