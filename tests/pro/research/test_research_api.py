import json
import time
import pytest
from dataclasses import replace
from fastapi.testclient import TestClient
from paperbot_pro.api import create_app
from paperbot_pro.config import ProSettings
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.research.config import ResearchSettings
from paperbot_pro.research.store import ResearchStore


def cfgs(tmp_path):
    pro = replace(ProSettings(), db_path=str(tmp_path / 'pro.sqlite'),
                  legacy_db_path=str(tmp_path / 'paper.sqlite'),
                  validation_report_path=str(tmp_path / 'v.json'))
    lab = replace(LabSettings(), db_path=str(tmp_path / 'lab.sqlite'), main_db_path=pro.db_path)
    research = replace(ResearchSettings(), db_path=str(tmp_path / 'research.sqlite'),
                       main_db_path=pro.db_path,
                       live_state_path=str(tmp_path / 'research_live.json'))
    return pro, lab, research


def test_research_endpoint_reports_capital_and_five_strategies(tmp_path):
    pro, lab, research = cfgs(tmp_path)
    client = TestClient(create_app(pro, lab, research))
    body = client.get('/api/research').json()
    assert body['capital']['initial_usd'] == 250.0
    assert body['capital']['equity_usd'] == pytest.approx(250.0)
    assert body['capital']['threshold_usd'] == pytest.approx(200.0)
    assert len(body['strategies']) == 5
    assert all(s['cash_usd'] == 50.0 for s in body['strategies'])
    assert body['status']['auto_entry'] is False


def test_strategies_endpoint_compares_all_ten_with_ranking(tmp_path):
    """Post-merge: all 10 strategies live in the Extreme Lab, each tagged by its
    cohort. regime_trend is a research-cohort sleeve inside the unified lab."""
    from paperbot_pro.lab.store import LabStore
    pro, lab, research = cfgs(tmp_path)
    lstore = LabStore(lab.db_path, lab)            # fresh unified lab: 10 sleeves
    with lstore.conn:
        for pnl in (3.0, -1.0, 2.0):
            lstore.conn.execute(
                """INSERT INTO trades(strategy,symbol,side,leverage,qty,entry_price,exit_price,
                   stop_initial,stop_final,target,margin_usd,notional_usd,entry_fee_usd,
                   exit_fee_usd,funding_usd,net_pnl_usd,entry_ms,exit_ms,exit_reason,rationale)
                   VALUES('regime_trend','BTC/USDT:USDT','long',10,0.1,100,?,95,95,NULL,10,100,
                   0.06,0.06,0.01,?,0,3600000,'TARGET','t')""", (100 + pnl, pnl))
        lstore.conn.execute("UPDATE strategies SET cash_usd=54, realized_pnl_usd=4 WHERE key='regime_trend'")
    lstore.close()
    client = TestClient(create_app(pro, lab, research))
    body = client.get('/api/strategies').json()
    assert body['count'] == 10
    labs = {s['lab'] for s in body['strategies']}
    assert labs == {'extreme', 'research'}         # cohort tags on the unified 10
    rt = next(s for s in body['strategies'] if s['key'] == 'regime_trend')
    assert rt['lab'] == 'research'                  # research cohort
    assert rt['trade_count'] == 3
    assert rt['win_rate_pct'] == pytest.approx(2 / 3 * 100)
    assert rt['realized_pnl_usd'] == pytest.approx(4.0)
    assert rt['profit_factor'] == pytest.approx(5.0)   # wins 5 / losses 1
    assert 'rank_by_net_pnl' in rt
    # ranking is dense and covers all ten
    ranks = sorted(s['rank_by_net_pnl'] for s in body['strategies'])
    assert ranks == list(range(1, 11))
    # incomplete-sample flag for small trade counts
    assert rt['sample'] == 'insufficient'


def test_research_stream_live_status(tmp_path):
    pro, lab, research = cfgs(tmp_path)
    state = {"ts_ms": int(time.time() * 1000),
             "published_at_ms": int(time.time() * 1000),
             "positions": [], "capital": {"equity_usd": 250.0, "complete": True},
             "locked": False}
    with open(research.live_state_path, 'w') as f:
        json.dump(state, f)
    client = TestClient(create_app(pro, lab, research))
    with client.stream('GET', '/api/research/stream?limit=1') as resp:
        for line in resp.iter_lines():
            if line.startswith('data:'):
                d = json.loads(line.split(':', 1)[1])
                assert d['live_status'] == 'LIVE'
                assert d['capital']['equity_usd'] == 250.0
                break
