import time
from dataclasses import replace
from paperbot.cli import run_loop
from paperbot.config import Settings
from paperbot.models import Candle, Quote
from paperbot.notify import Notifier


def fresh_snapshot():
    now_ms = int(time.time() * 1000)
    bars = [Candle(i * 3_600_000, 100.0, 101.0, 99.0, 100.0, 1.0) for i in range(120)]
    return bars, Quote(100.0, 100.1, now_ms)


class FlakyMarket:
    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError('exchange unreachable')
        return fresh_snapshot()


def test_run_loop_backs_off_alerts_on_streak_and_recovers(tmp_path, capsys):
    cfg = Settings()
    notifier = Notifier(str(tmp_path / 'alerts.jsonl'), throttle_seconds=0)
    sleeps = []
    market = FlakyMarket(failures=3)
    run_loop(str(tmp_path / 'paper.sqlite'), cfg, notifier,
             market_factory=lambda: market, sleep=sleeps.append, iterations=5)
    assert market.calls == 5
    # Backoff grows during the outage, then resets to the base interval.
    assert sleeps[0] > cfg.interval_seconds
    assert sleeps[1] > sleeps[0]
    assert sleeps[-1] == cfg.interval_seconds
    log = (tmp_path / 'alerts.jsonl').read_text()
    assert 'FEED FAILURE' in log
    assert 'FEED RECOVERED' in log
    # Failures are visible, not hidden.
    assert 'SAFE ERROR' in capsys.readouterr().err
