"""API streaming of the live state file: lab_live SSE, staleness semantics,
multiple concurrent clients, no SQLite polling in the hot path."""
import json
import time
import pytest
from dataclasses import replace
from fastapi.testclient import TestClient
from paperbot_pro.api import create_app
from paperbot_pro.config import ProSettings
from paperbot_pro.lab.config import LabSettings


def make_cfg(tmp_path):
    cfg = replace(ProSettings(),
                  db_path=str(tmp_path / 'pro.sqlite'),
                  legacy_db_path=str(tmp_path / 'paper.sqlite'),
                  validation_report_path=str(tmp_path / 'validation.json'))
    lab_cfg = replace(LabSettings(), db_path=str(tmp_path / 'lab.sqlite'),
                      main_db_path=cfg.db_path,
                      live_state_path=str(tmp_path / 'lab_live.json'))
    return cfg, lab_cfg


def write_live(path, equity=250.0, age_ms=0, **extra):
    state = {"ts_ms": int(time.time() * 1000) - age_ms,
             "exchange_ts_ms": int(time.time() * 1000) - age_ms - 50,
             "published_at_ms": int(time.time() * 1000) - age_ms,
             "locked": False, "breached": False,
             "positions": [], "capital": {"equity_usd": equity, "complete": True}}
    state.update(extra)
    with open(path, 'w') as f:
        json.dump(state, f)


def read_events(client, url, want):
    got = []
    with client.stream('GET', url) as response:
        event_name = None
        for line in response.iter_lines():
            if line.startswith('event:'):
                event_name = line.split(':', 1)[1].strip()
            elif line.startswith('data:') and event_name:
                got.append((event_name, json.loads(line.split(':', 1)[1])))
                event_name = None
            if len(got) >= want:
                break
    return got


def test_lab_live_sse_streams_fresh_state(tmp_path):
    cfg, lab_cfg = make_cfg(tmp_path)
    write_live(lab_cfg.live_state_path, equity=261.5)
    client = TestClient(create_app(cfg, lab_cfg))
    events = read_events(client, '/api/lab/stream?limit=2', want=2)
    assert all(name == 'lab_live' for name, _ in events)
    assert events[0][1]['capital']['equity_usd'] == 261.5
    assert events[0][1]['live_status'] == 'LIVE'
    assert 'server_ts_ms' in events[0][1]


def test_lab_live_sse_marks_stale_and_disconnected(tmp_path):
    cfg, lab_cfg = make_cfg(tmp_path)
    write_live(lab_cfg.live_state_path, age_ms=5 * 60_000)   # 5 minutes old
    client = TestClient(create_app(cfg, lab_cfg))
    events = read_events(client, '/api/lab/stream?limit=1', want=1)
    assert events[0][1]['live_status'] == 'STALE'

    cfg2, lab_cfg2 = make_cfg(tmp_path / 'b')                # file never written
    client2 = TestClient(create_app(cfg2, lab_cfg2))
    events2 = read_events(client2, '/api/lab/stream?limit=1', want=1)
    assert events2[0][1]['live_status'] == 'DISCONNECTED'


def test_multiple_clients_receive_the_same_stream(tmp_path):
    cfg, lab_cfg = make_cfg(tmp_path)
    write_live(lab_cfg.live_state_path, equity=255.5)
    app = create_app(cfg, lab_cfg)
    a = read_events(TestClient(app), '/api/lab/stream?limit=1', want=1)
    b = read_events(TestClient(app), '/api/lab/stream?limit=1', want=1)
    assert a[0][1]['capital']['equity_usd'] == 255.5
    assert b[0][1]['capital']['equity_usd'] == 255.5
