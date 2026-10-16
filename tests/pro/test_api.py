import json
import pytest
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
    from tests.pro.conftest import write_valid_artifact
    write_valid_artifact(cfg)
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


def test_overview_equity_does_not_double_count_settled_funding(tmp_path):
    """Review I1: funding is settled from cash when applied; overview equity
    must use gross unrealized, not subtract funding a second time."""
    from paperbot_pro.store import ProStore
    cfg = make_cfg(tmp_path)
    store = ProStore(cfg.db_path, cfg)
    with store.conn:
        store.conn.execute(
            """INSERT INTO positions(symbol, side, leverage, qty, entry_price, margin_usd,
               notional_usd, stop, initial_stop, target, liq_price_est, entry_fee_usd,
               funding_paid_usd, planned_risk_usd, planned_risk_pct, sleeve, opened_ms,
               signal_bar_ms, rationale) VALUES('X/USDT:USDT','long',10,1,100,10,100,95,
               95,110,90.5,0.06,2.0,5,0.005,'core',0,0,'T')""")
    store.set('cash_core', 900.0 - 10.0 - 0.06 - 2.0)  # margin+fee+settled funding out
    store.set('marks', {'X/USDT:USDT': 100.0})         # mark at entry: gross unrealized 0
    store.close()
    body = TestClient(create_app(cfg)).get('/api/overview').json()
    assert body['equity_usd'] == pytest.approx(1000.0 - 0.06 - 2.0)
    # the per-position view may still show funding-adjusted unrealized PnL
    pos = TestClient(create_app(cfg)).get('/api/positions').json()[0]
    assert pos['unrealized_pnl_usd'] == pytest.approx(-2.0)


def test_free_margin_excludes_watch_only_hype_and_manual_pause_surfaces(tmp_path):
    from paperbot_pro.store import ProStore
    cfg = make_cfg(tmp_path)
    body = TestClient(create_app(cfg)).get('/api/overview').json()
    assert body['free_margin_usd'] == pytest.approx(900.0)  # hype $100 is watch-only
    store = ProStore(cfg.db_path, cfg)
    store.set('manual_pause', True)
    store.close()
    body = TestClient(create_app(cfg)).get('/api/overview').json()
    assert body['risk']['trading_enabled'] is False
    assert 'paused' in body['risk']['pause_reason'].lower()


def test_sse_stream_emits_initial_overview_event(tmp_path):
    client = TestClient(create_app(make_cfg(tmp_path)))
    with client.stream('GET', '/api/events?limit=1') as response:
        assert response.headers['content-type'].startswith('text/event-stream')
        for line in response.iter_lines():
            if line.startswith('event:'):
                assert 'overview' in line
                break
