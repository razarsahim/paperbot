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


def test_not_enough_history():
    candles = load_csv(str(DATA))
    with pytest.raises(ValueError):
        backtest(candles[:35], Settings())


def test_ema_atr_warmup():
    candles = load_csv(str(DATA))
    assert ema([1, 2, 3], 5) == [None] * 3
    assert len(atr(candles)) == len(candles)
