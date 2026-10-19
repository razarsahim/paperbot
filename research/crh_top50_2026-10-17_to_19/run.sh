#!/bin/bash
# EXPERIMENT (widened universe): Crash Reversal Hunter ONLY, 1h signals, top-50 daily
# universe, ONE continuous run 2026-10-17 00:00 -> 2026-10-19 00:00 UTC.
# Contract metadata for all 41 eligible perps from Bybit public endpoints (instruments.json).
# Order books downloaded only for symbols where the strategy fires (see prescan.py).
set -euo pipefail
cd "$(dirname "$0")/../.."
D=research/crh_top50_2026-10-17_to_19
.venv/bin/python -m paperbot_pro.replay.run_week --run-id CRH_top50_48h \
  --strategies crash_reversal --timeframe 1h --data "$D/data" --books "$D/data/book_samples" \
  --out "$D/runs" --t0 1792195200000 --t1 1792368000000 \
  --universe-file "$D/universe_daily.json" --main-db "$D/no_main_db" \
  --extra-instruments "$D/instruments.json"
