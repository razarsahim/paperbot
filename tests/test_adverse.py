"""Adverse market / infrastructure scenarios. These tests document that the
simulation surfaces bad outcomes honestly instead of hiding them."""
import json
from dataclasses import replace
from paperbot.config import Settings
from paperbot.engine import PaperEngine
from paperbot.models import Candle, Quote
from paperbot.notify import Notifier
from paperbot.store import Store
from paperbot.cli import run_loop


def candles(n=120, close=100.0):
    return [Candle(i * 3_600_000, close, close + 2, close - 2, close, 1)
            for i in range(n)]


def make(tmp_path):
    cfg = replace(Settings(), min_bars=85)
    db = Store(str(tmp_path / 'paper.sqlite'), cfg.starting_balance, cfg.symbol)
    return PaperEngine(db, cfg)


def test_flash_crash_gap_through_stop_realizes_worse_than_planned_loss(tmp_path):
    bot = make(tmp_path)
    bot._enter(100, 1.0, 118 * 3_600_000, 117 * 3_600_000, 'TEST')
    planned_risk = 1000 * bot.cfg.risk_per_trade
    now = 120 * 3_600_000 + 5_000
    events = bot.tick(candles(), Quote(80.0, 80.1, now), now)  # 20% gap down
    assert any('SIMULATED EXIT' in e for e in events)
    assert bot.db.position() is None
    trade = bot.db.trades()[0]
    assert trade['exit_price'] < 98  # filled at crashed bid, not at the stop
    assert trade['net_pnl'] < -planned_risk  # loss honestly exceeds the plan
    rows = bot.db.equity_history()
    assert rows[-1]['equity'] < 1000 - planned_risk  # snapshot shows the damage


def test_restart_after_outage_keeps_position_and_flags_monitoring_gap(tmp_path):
    bot = make(tmp_path)
    bot._enter(100, 1.0, 118 * 3_600_000, 117 * 3_600_000, 'TEST')
    now1 = 120 * 3_600_000 + 5_000
    bot.tick(candles(120), Quote(100.0, 100.1, now1), now1)
    original = bot.db.position()
    bot.db.close()

    again = make(tmp_path)  # process restart 2h later
    now2 = now1 + 2 * 3_600_000
    events = again.tick(candles(122), Quote(100.0, 100.1, now2), now2)
    assert again.db.position() == original
    assert any('MONITORING GAP' in e for e in events)
    assert again.db.trades() == []  # no phantom exits or replayed entries


def test_repeated_identical_ticks_are_idempotent(tmp_path, monkeypatch):
    bot = make(tmp_path)
    from paperbot.strategy import Signal
    monkeypatch.setattr('paperbot.engine.evaluate', lambda bars: Signal(True, 1, 'FAKE'))
    now = 120 * 3_600_000 + 5_000
    quote = Quote(100.0, 100.1, now)
    bot.tick(candles(), quote, now)
    pos = bot.db.position()
    for _ in range(5):  # feed replays the same snapshot
        bot.tick(candles(), quote, now)
    assert bot.db.position() == pos  # no averaging down, no duplicates
    assert bot.db.trades() == []
    assert len(bot.db.equity_history()) == 1  # same-ts snapshot replaced, not duplicated


def test_total_feed_outage_backs_off_alerts_once_and_touches_no_state(tmp_path, capsys):
    cfg = Settings()

    class DeadMarket:
        def snapshot(self):
            raise ConnectionError('exchange unreachable')

    notifier = Notifier(str(tmp_path / 'alerts.jsonl'))
    sleeps = []
    run_loop(str(tmp_path / 'paper.sqlite'), cfg, notifier,
             market_factory=lambda: DeadMarket(), sleep=sleeps.append, iterations=10)
    assert max(sleeps) == 900  # backoff capped at 15 minutes
    assert sleeps == sorted(sleeps)  # monotonic during the outage
    alerts = [json.loads(l) for l in (tmp_path / 'alerts.jsonl').read_text().splitlines()]
    assert sum(a['title'] == 'FEED FAILURE' for a in alerts) == 1  # throttled
    assert not (tmp_path / 'paper.sqlite').exists()  # fail closed: nothing written
    assert capsys.readouterr().err.count('SAFE ERROR') == 10  # nothing hidden
