import json
from dataclasses import replace
from fastapi.testclient import TestClient
from paperbot.store import Store
from paperbot_pro.api import create_app
from paperbot_pro.config import ProSettings


def make_cfg(tmp_path, **kw):
    legacy = Store(str(tmp_path / 'paper.sqlite'), 1000.0, 'BTC/GBP')
    with legacy.conn:
        legacy.set('balance', 995.0)
        legacy.record_equity(1_000_000, 50_000.0, 995.0, 995.0, 0.0)
    legacy.close()
    return replace(ProSettings(),
                   db_path=str(tmp_path / 'pro.sqlite'),
                   legacy_db_path=str(tmp_path / 'paper.sqlite'),
                   validation_report_path=str(tmp_path / 'validation_report.json'),
                   **kw)


def test_health_reports_engines_and_sources(tmp_path):
    client = TestClient(create_app(make_cfg(tmp_path)))
    body = client.get('/api/health').json()
    assert body['status'] in ('ok', 'degraded')
    assert body['engines']['pro']['auto_entry_enabled'] is False
    assert body['engines']['legacy']['last_tick_ms'] is None or isinstance(
        body['engines']['legacy']['last_tick_ms'], int)
    assert isinstance(body['data_sources'], list)


def test_overview_sources_real_state_and_legacy_bridge(tmp_path):
    client = TestClient(create_app(make_cfg(tmp_path)))
    body = client.get('/api/overview').json()
    assert body['mode'] == 'PAPER'
    assert body['equity_usd'] == 1000.0
    assert body['sleeves']['core']['balance_usd'] == 900.0
    assert body['sleeves']['hype']['watch_only'] is True
    assert body['legacy']['symbol'] == 'BTC/GBP'
    assert body['legacy']['cash_gbp'] == 995.0
    assert body['risk']['max_positions'] == 3


def test_auto_entry_gated_on_validation_artifact(tmp_path):
    cfg = make_cfg(tmp_path, auto_entry=True)
    client = TestClient(create_app(cfg))
    body = client.get('/api/overview').json()
    assert body['risk']['trading_enabled'] is False
    assert 'validation' in (body['risk']['pause_reason'] or '').lower()
    with open(cfg.validation_report_path, 'w') as f:
        json.dump({'generated_at': '2026-10-16', 'windows': []}, f)
    body = TestClient(create_app(cfg)).get('/api/overview').json()
    assert body['risk']['trading_enabled'] is True
    assert body['risk']['pause_reason'] is None


def test_empty_collections_and_404(tmp_path):
    client = TestClient(create_app(make_cfg(tmp_path)))
    assert client.get('/api/positions').json() == []
    assert client.get('/api/trades').json() == []
    assert client.get('/api/signals').json() == []
    assert client.get('/api/universe').json()['stale'] is True
    assert client.get('/api/trades/999').status_code == 404
    assert client.get('/api/settings').json()['leverage'] == 10.0


def test_sse_stream_emits_initial_overview_event(tmp_path):
    client = TestClient(create_app(make_cfg(tmp_path)))
    with client.stream('GET', '/api/events?limit=1') as response:
        assert response.headers['content-type'].startswith('text/event-stream')
        for line in response.iter_lines():
            if line.startswith('event:'):
                assert 'overview' in line
                break
