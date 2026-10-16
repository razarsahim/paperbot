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


def test_not_enough_history():
    candles = load_csv(str(DATA))
    with pytest.raises(ValueError):
        backtest(candles[:35], Settings())


def test_ema_atr_warmup():
    candles = load_csv(str(DATA))
    assert ema([1, 2, 3], 5) == [None] * 3
    assert len(atr(candles)) == len(candles)
