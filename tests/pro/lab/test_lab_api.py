import pytest
from dataclasses import replace
from fastapi.testclient import TestClient
from paperbot_pro.api import create_app
from paperbot_pro.config import ProSettings
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.store import LabStore


def make_cfg(tmp_path):
    cfg = replace(ProSettings(),
                  db_path=str(tmp_path / 'pro.sqlite'),
                  legacy_db_path=str(tmp_path / 'paper.sqlite'),
                  validation_report_path=str(tmp_path / 'validation_report.json'))
    lab_cfg = replace(LabSettings(), db_path=str(tmp_path / 'lab.sqlite'),
                      main_db_path=cfg.db_path)
    return cfg, lab_cfg


def test_lab_endpoint_reports_capital_hwm_and_strategies(tmp_path):
    cfg, lab_cfg = make_cfg(tmp_path)
    client = TestClient(create_app(cfg, lab_cfg))
    body = client.get('/api/lab').json()
    assert body['capital']['initial_usd'] == 500.0
    assert body['capital']['equity_usd'] == pytest.approx(500.0)
    assert body['capital']['peak_equity_usd'] == pytest.approx(500.0)
    assert body['capital']['threshold_usd'] == pytest.approx(450.0)
    assert body['capital']['remaining_allowance_usd'] == pytest.approx(50.0)
    assert len(body['strategies']) == 10
    assert all(s['cash_usd'] == 50.0 for s in body['strategies'])
    assert body['status']['locked'] is False


def test_lab_strategies_carry_cohort_and_status_for_the_dashboard(tmp_path):
    cfg, lab_cfg = make_cfg(tmp_path)
    client = TestClient(create_app(cfg, lab_cfg))
    body = client.get('/api/lab').json()
    by_key = {s['key']: s for s in body['strategies']}
    # cohort tags present for the leaderboard / per-cohort rules
    assert by_key['breakout']['cohort'] == 'extreme'
    assert by_key['regime_trend']['cohort'] == 'research'
    # per-strategy status, leverage and leaderboard-ready P&L fields present
    for s in body['strategies']:
        assert s['status']['level'] in {'ok', 'warning', 'locked'}
        assert s['leverage'] == 10.0
        assert 'unrealized_pnl_usd' in s and 'return_pct' in s
    # fresh research sleeve: $50 cash is above the $40 warn floor -> ok
    assert by_key['regime_trend']['status']['level'] == 'ok'
    assert body['status']['auto_entry'] is False
    assert body['positions'] == [] and body['trades'] == []


def test_lab_endpoint_surfaces_lock_state(tmp_path):
    cfg, lab_cfg = make_cfg(tmp_path)
    store = LabStore(lab_cfg.db_path, lab_cfg)
    store.set('lab_locked', True)
    store.set('lab_lock_reason', 'TRAILING DRAWDOWN BREACH: test')
    store.close()
    body = TestClient(create_app(cfg, lab_cfg)).get('/api/lab').json()
    assert body['status']['locked'] is True
    assert 'BREACH' in body['status']['lock_reason']


def test_sse_emits_lab_event_too(tmp_path):
    cfg, lab_cfg = make_cfg(tmp_path)
    client = TestClient(create_app(cfg, lab_cfg))
    events = set()
    with client.stream('GET', '/api/events?limit=2') as response:
        for line in response.iter_lines():
            if line.startswith('event:'):
                events.add(line.split(':', 1)[1].strip())
            if {'overview', 'lab'} <= events:
                break
    assert {'overview', 'lab'} <= events
