from pathlib import Path
from dataclasses import replace
import pytest
from paperbot.config import Settings
from paperbot.market import load_csv
from paperbot.backtest import backtest
from paperbot.strategy import evaluate, ema, atr

DATA = Path(__file__).parents[1] / 'data' / 'synthetic_demo_btc_gbp.csv'


def test_backtest_runs_on_synthetic_candles():
    candles = load_csv(str(DATA))
    report = backtest(candles, Settings())
    assert report.initial_cash == 1000.0
    assert report.final_equity > 0
    assert 0 <= report.win_rate_pct <= 100
    assert report.max_drawdown_pct >= 0
    assert len(report.trades) > 0
    assert all(trade.entry_ts <= trade.exit_ts for trade in report.trades)


def test_backtest_never_reads_future_bars_for_past_signal():
    candles = load_csv(str(DATA))
    prefix = candles[:200]
    original_signal = evaluate(prefix)
    changed_future = list(prefix) + [replace(c, close=c.open * 1.1, high=max(c.high, c.open * 1.1)) for c in candles[200:210]]
    assert evaluate(changed_future[:200]) == original_signal
    assert backtest(prefix, Settings()).trades == [
        t for t in backtest(candles, Settings()).trades if t.exit_ts < candles[200].timestamp
    ]


def test_gap_open_above_target_exits_at_target_not_stop(monkeypatch):
    """A bar that OPENS at/above target exits at the open (first trade of the
    bar), before any later intrabar dip to the stop can matter. Fill is still
    modelled conservatively at the target price, never better."""
    from paperbot.models import Candle
    from paperbot.strategy import Signal

    flat = [Candle(i * 3_600_000, 100.0, 101.0, 99.0, 100.0, 1.0) for i in range(100)]
    entry_i = 90
    bars = list(flat)
    # Entry bar: no same-bar stop/target touch. fill ~100.15, stop ~98.15, target ~104.16
    bars[entry_i + 1] = Candle(bars[entry_i + 1].timestamp, 105.0, 106.0, 98.0, 100.0, 1.0)
    monkeypatch.setattr('paperbot.backtest.evaluate',
                        lambda b: Signal(len(b) == entry_i, 1.0, 'FAKE'))
    report = backtest(bars, Settings())
    assert len(report.trades) == 1
    trade = report.trades[0]
    assert trade.reason.startswith('TARGET'), f'got {trade.reason}'
    assert trade.net_pnl > 0


def test_backtest_daily_lock_sticks_for_rest_of_utc_day(monkeypatch):
    """Parity with the live engine: once marked equity dips 2% below the UTC
    day's starting equity, no new entries that day even if equity recovers.
    Scenario: position held across midnight marks down >2% from the new day's
    open without hitting its stop, recovers, exits at target — a later
    same-day signal must NOT produce a trade."""
    from paperbot.models import Candle
    from paperbot.strategy import Signal

    H = 3_600_000
    def bar(i, o, h, l, c):
        return Candle(i * H, o, h, l, c, 1.0)
    bars = [bar(i, 100.0, 102.0, 99.9, 100.0) for i in range(111)]
    # Entry at bar 90 open (~fill 100.15, stop 99.75, target 108.15 with rr=20)
    bars[91] = bar(91, 100.0, 101.5, 99.9, 101.0)
    bars[92] = bar(92, 101.0, 102.5, 100.9, 102.0)
    for i in (93, 94, 95):
        bars[i] = bar(i, 102.0 if i == 93 else 103.0, 103.5, 101.5, 103.0)
    bars[96] = bar(96, 103.0, 103.5, 102.5, 103.0)   # UTC day 4 starts here
    bars[97] = bar(97, 103.0, 103.2, 100.2, 100.3)   # >2% dip from day start, stop survives
    bars[98] = bar(98, 100.3, 103.2, 100.2, 103.0)   # same-day recovery
    bars[99] = bar(99, 103.0, 108.5, 102.9, 107.0)   # target hit: equity back above threshold
    bars[100] = bar(100, 104.0, 105.0, 103.0, 104.0)  # same-day signal fires here
    for i in range(101, 111):
        bars[i] = bar(i, 104.0, 105.0, 103.5, 104.0)
    monkeypatch.setattr('paperbot.backtest.evaluate',
                        lambda b: Signal(len(b) in (90, 100), 0.2, 'FAKE'))
    cfg = replace(Settings(), risk_per_trade=0.01, reward_risk=20.0)
    report = backtest(bars, cfg)
    assert report.trades and report.trades[0].reason.startswith('TARGET')
    assert all(t.entry_ts != bars[100].timestamp for t in report.trades), \
        're-entered during the same UTC day after the daily lock triggered'
    assert not report.still_open


def test_not_enough_history():
    candles = load_csv(str(DATA))
    with pytest.raises(ValueError):
        backtest(candles[:35], Settings())


def test_ema_atr_warmup():
    candles = load_csv(str(DATA))
    assert ema([1, 2, 3], 5) == [None] * 3
    assert len(atr(candles)) == len(candles)
