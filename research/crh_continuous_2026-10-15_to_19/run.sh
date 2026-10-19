#!/bin/bash
# Crash Reversal Hunter ONLY, 1h signals, ONE continuous run 2026-10-15 00:00 -> 2026-10-19 00:00 UTC.
# Single engine + single SQLite: balance, open positions and trailing stops carry across days.
set -euo pipefail
cd "$(dirname "$0")/../.."
D=research/crh_continuous_2026-10-15_to_19
.venv/bin/python -m paperbot_pro.replay.run_week --run-id CRH_continuous_96h \
  --strategies crash_reversal --timeframe 1h --data "$D/data" --books "$D/data/book_samples" \
  --out "$D/runs" --t0 1792022400000 --t1 1792368000000 \
  --universe-file "$D/universe_daily.json" \
  --extra-instruments research/replay_2026-09-18_30d/extra_instruments.json
