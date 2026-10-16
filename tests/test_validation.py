from pathlib import Path
import pytest
from paperbot.config import Settings
from paperbot.market import load_csv
from paperbot.models import Candle
from paperbot.validation import walk_forward

DATA = Path(__file__).parents[1] / 'data' / 'synthetic_demo_btc_gbp.csv'


def test_walk_forward_windows_are_chronological_and_non_overlapping():
    bars = load_csv(str(DATA))
    report = walk_forward(bars, Settings(), n_windows=4)
    assert len(report.windows) == 4
    for w in report.windows:
        assert w.start_ms < w.end_ms
        for t in w.trades:
            assert w.start_ms <= t.entry_ts <= w.end_ms
    for a, b in zip(report.windows, report.windows[1:]):
        assert b.start_ms > a.end_ms  # strictly later, no overlap
    assert report.total_trades == sum(len(w.trades) for w in report.windows)
    # every window labelled with real dates for auditability
    assert all(w.start_utc.startswith('20') and w.end_utc.startswith('20')
               for w in report.windows)


def test_walk_forward_signals_use_only_pre_window_warmup_history():
    """Mutating bars AFTER a window must not change that window's results."""
    from dataclasses import replace
    bars = load_csv(str(DATA))
    report = walk_forward(bars, Settings(), n_windows=4)
    first = report.windows[0]
    cut = len(bars) - 100  # well inside the final window
    mutated = bars[:cut] + [
        replace(c, close=c.open * 1.2, high=max(c.high, c.open * 1.2))
        for c in bars[cut:]]
    report2 = walk_forward(mutated, Settings(), n_windows=4)
    assert report2.windows[0].net_return_pct == first.net_return_pct
    assert [t.entry_ts for t in report2.windows[0].trades] == [
        t.entry_ts for t in first.trades]


def test_walk_forward_buy_hold_benchmark_includes_costs():
    cfg = Settings()
    flat = [Candle(i * 3_600_000, 100.0, 101.0, 99.0, 100.0, 1.0) for i in range(400)]
    report = walk_forward(flat, cfg, n_windows=2)
    # flat market: buy-and-hold must LOSE the round-trip fees and slippage
    for w in report.windows:
        assert w.buy_hold_return_pct < 0


def test_cli_walkforward_prints_labelled_json(monkeypatch, capsys):
    import json
    from paperbot.cli import main
    monkeypatch.setattr('sys.argv', ['paperbot', 'walkforward', '--csv', str(DATA),
                                     '--windows', '3'])
    main()
    out = json.loads(capsys.readouterr().out)
    assert len(out['windows']) == 3
    assert out['windows'][0]['start_utc'].startswith('20')
    assert any('not evidence' in w for w in out['warnings'])


def test_walk_forward_rejects_insufficient_data():
    bars = load_csv(str(DATA))[:120]
    with pytest.raises(ValueError):
        walk_forward(bars, Settings(), n_windows=4)
