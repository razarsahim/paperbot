import pytest
from paperbot.report import drawdown_series, trade_stats


def test_trade_stats_on_mixed_results():
    trades = [
        {'net_pnl': 10.0, 'entry_ms': 0, 'exit_ms': 3_600_000},
        {'net_pnl': -5.0, 'entry_ms': 7_200_000, 'exit_ms': 10_800_000},
        {'net_pnl': -5.0, 'entry_ms': 14_400_000, 'exit_ms': 25_200_000},
        {'net_pnl': 20.0, 'entry_ms': 28_800_000, 'exit_ms': 32_400_000},
    ]
    stats = trade_stats(trades)
    assert stats['closed_trades'] == 4
    assert stats['win_rate_pct'] == pytest.approx(50.0)
    assert stats['profit_factor'] == pytest.approx(30.0 / 10.0)
    assert stats['expectancy'] == pytest.approx(5.0)
    assert stats['total_net_pnl'] == pytest.approx(20.0)
    assert stats['average_hold_hours'] == pytest.approx((1 + 1 + 3 + 1) / 4)


def test_trade_stats_empty_and_no_losers():
    assert trade_stats([])['closed_trades'] == 0
    assert trade_stats([])['profit_factor'] is None
    only_wins = trade_stats([{'net_pnl': 1.0, 'entry_ms': 0, 'exit_ms': 0}])
    assert only_wins['profit_factor'] is None  # undefined without losers
    assert only_wins['win_rate_pct'] == 100.0


def test_drawdown_series_tracks_running_peak():
    rows = [
        {'ts_ms': 1, 'equity': 1000.0},
        {'ts_ms': 2, 'equity': 1100.0},
        {'ts_ms': 3, 'equity': 990.0},
        {'ts_ms': 4, 'equity': 1100.0},
        {'ts_ms': 5, 'equity': 1200.0},
    ]
    dd = drawdown_series(rows)
    assert dd == pytest.approx([0.0, 0.0, -10.0, 0.0, 0.0])
