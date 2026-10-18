#!/bin/bash
# Reproduce every replay run (HISTORICAL BACKTEST). Requires data/ + book_samples/.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv/bin/python
OUT=research/replay_2026-10-11/runs
mkdir -p "$OUT"
{
  for s in breakout launch_sniper squeeze trend crash_reversal regime_trend \
           volatility_breakout trend_pullback range_reversion orderflow_imbalance; do
    echo "--run-id A_$s --strategies $s"
  done
  echo "--run-id B_combined"
  echo "--run-id B_deployed --no-orderbook"
} | xargs -P 6 -L 1 $PY -m paperbot_pro.replay.run_week --out "$OUT" > "$OUT/runs.log" 2>&1
$PY -m paperbot_pro.replay.report
