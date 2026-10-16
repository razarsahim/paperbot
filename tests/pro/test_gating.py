"""Auto-entry gating must depend on WHAT was validated, not file existence."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from paperbot_pro.config import ProSettings
from paperbot_pro.engine import ProEngine
from paperbot_pro.store import ProStore
from paperbot_pro.validation import params_fingerprint


def make(tmp_path, **kw):
    cfg = replace(ProSettings(), auto_entry=True,
                  db_path=str(tmp_path / 'pro.sqlite'),
                  validation_report_path=str(tmp_path / 'validation_report.json'), **kw)
    return ProEngine(ProStore(cfg.db_path, cfg), cfg), cfg


def write_artifact(cfg, **overrides):
    artifact = {
        'artifact_version': 2,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'params_fingerprint': params_fingerprint(cfg),
        'outcome': 'MIXED',
        'combined': {'total_trades': 100, 'markets_profitable': 9},
        'markets': [{'symbol': f'M{i}'} for i in range(16)],
        'summary': 'test',
    }
    artifact.update(overrides)
    with open(cfg.validation_report_path, 'w') as f:
        json.dump(artifact, f)
    return artifact


def test_matching_fresh_artifact_allows(tmp_path):
    engine, cfg = make(tmp_path)
    write_artifact(cfg)
    allowed, reason = engine.auto_entry_allowed()
    assert allowed, reason


def test_fingerprint_mismatch_gates(tmp_path):
    engine, cfg = make(tmp_path)
    write_artifact(cfg, params_fingerprint='deadbeef00000000')
    allowed, reason = engine.auto_entry_allowed()
    assert not allowed and 'parameters' in reason


def test_stale_artifact_gates(tmp_path):
    engine, cfg = make(tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat(timespec='seconds')
    write_artifact(cfg, generated_at_utc=old)
    allowed, reason = engine.auto_entry_allowed()
    assert not allowed and 'stale' in reason.lower()


def test_empty_market_set_gates(tmp_path):
    engine, cfg = make(tmp_path)
    write_artifact(cfg, markets=[])
    allowed, reason = engine.auto_entry_allowed()
    assert not allowed and 'market' in reason.lower()


def test_unparseable_or_legacy_artifact_gates(tmp_path):
    engine, cfg = make(tmp_path)
    with open(cfg.validation_report_path, 'w') as f:
        f.write('{"summary": "old v1 artifact without fingerprint"}')
    allowed, reason = engine.auto_entry_allowed()
    assert not allowed
    with open(cfg.validation_report_path, 'w') as f:
        f.write('not json {')
    allowed, reason = engine.auto_entry_allowed()
    assert not allowed and 'unreadable' in reason.lower()


def test_negative_outcome_needs_explicit_acknowledgement(tmp_path):
    engine, cfg = make(tmp_path)
    write_artifact(cfg, outcome='NEGATIVE')
    allowed, reason = engine.auto_entry_allowed()
    assert not allowed and 'negative' in reason.lower()

    engine2, cfg2 = make(tmp_path / 'ack', accept_negative_validation=True)
    write_artifact(cfg2, outcome='NEGATIVE')
    allowed, reason = engine2.auto_entry_allowed()
    assert allowed, reason
