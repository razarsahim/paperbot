import json
from paperbot.notify import FailureTracker, Notifier, dispatch_events


def make(tmp_path, **kw):
    return Notifier(str(tmp_path / 'alerts.jsonl'), **kw)


def test_alert_appended_to_jsonl_log(tmp_path):
    notifier = make(tmp_path, clock=lambda: 1000.0)
    assert notifier.send('info', 'SIMULATED BUY', 'qty 0.001 @ 60000') is True
    lines = (tmp_path / 'alerts.jsonl').read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry['level'] == 'info'
    assert entry['title'] == 'SIMULATED BUY'
    assert entry['ts'] == 1000.0


def test_duplicate_key_throttled_until_window_passes(tmp_path):
    now = {'t': 1000.0}
    notifier = make(tmp_path, throttle_seconds=900, clock=lambda: now['t'])
    assert notifier.send('error', 'FEED FAILURE', 'x', key='feed') is True
    now['t'] += 60
    assert notifier.send('error', 'FEED FAILURE', 'y', key='feed') is False
    now['t'] += 900
    assert notifier.send('error', 'FEED FAILURE', 'z', key='feed') is True
    assert len((tmp_path / 'alerts.jsonl').read_text().splitlines()) == 2


def test_webhook_failure_never_raises_and_still_logs(tmp_path, monkeypatch, capsys):
    notifier = make(tmp_path, webhook_url='https://example.invalid/hook')

    def boom(*a, **k):
        raise OSError('network down')
    monkeypatch.setattr('paperbot.notify.urlopen', boom)
    assert notifier.send('warning', 'LOCK', 'daily lock') is True
    assert len((tmp_path / 'alerts.jsonl').read_text().splitlines()) == 1
    assert 'webhook' in capsys.readouterr().err.lower()


def test_dispatch_routes_entries_exits_and_locks(tmp_path):
    notifier = make(tmp_path)
    dispatch_events(notifier, [
        'SIMULATED BUY 0.001 @ 60000; stop 59000; target 62000',
        'SIMULATED EXIT (STOP) @ 59000; net P&L -5.00',
        'DAILY DRAWDOWN LOCK: no entries until next UTC day',
        "MONITORING GAP: open position's stop unobserved for 7200s",
        'HOLD: No qualifying EMA reclaim',  # must NOT alert
        'NO SIGNAL: insufficient historical data',  # must NOT alert
    ])
    entries = [json.loads(l) for l in (tmp_path / 'alerts.jsonl').read_text().splitlines()]
    titles = [e['title'] for e in entries]
    assert any('BUY' in t for t in titles)
    assert any('EXIT' in t for t in titles)
    assert any('LOCK' in t for t in titles)
    assert any('MONITORING GAP' in t for t in titles)
    assert len(entries) == 4


def test_alert_log_write_failure_prints_but_never_raises(tmp_path, capsys):
    notifier = make(tmp_path)
    tmp_path.chmod(0o500)  # alerts dir becomes unwritable (disk trouble)
    try:
        notifier.send('error', 'FEED FAILURE', 'must not crash the engine')
    finally:
        tmp_path.chmod(0o700)
    assert 'alert' in capsys.readouterr().err.lower()


def test_failure_tracker_alerts_on_streak_and_recovery():
    tracker = FailureTracker(threshold=3)
    assert tracker.record_failure('a') is False
    assert tracker.record_failure('b') is False
    assert tracker.record_failure('c') is True   # streak reached: alert once
    assert tracker.record_failure('d') is False  # no repeat alert every tick
    assert tracker.record_success() is True      # recovery after alerted streak
    assert tracker.record_success() is False
    assert tracker.record_failure('e') is False
    assert tracker.record_success() is False     # short streak: no recovery alert
