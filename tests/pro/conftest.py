import json
from datetime import datetime, timezone


def write_valid_artifact(cfg, **overrides):
    """A v2 validation artifact that passes every gate check (outcome MIXED,
    fresh, fingerprint matching cfg). Tests override fields to probe gates."""
    from paperbot_pro.validation import ARTIFACT_VERSION, params_fingerprint
    artifact = {
        'artifact_version': ARTIFACT_VERSION,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'params_fingerprint': params_fingerprint(cfg),
        'outcome': 'MIXED',
        'combined': {'total_trades': 100, 'markets_profitable': 9},
        'markets': [{'symbol': f'M{i}'} for i in range(16)],
        'summary': 'test artifact',
    }
    artifact.update(overrides)
    with open(cfg.validation_report_path, 'w') as f:
        json.dump(artifact, f)
    return artifact
