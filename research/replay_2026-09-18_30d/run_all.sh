#!/bin/bash
# Reproduce every 30-day replay run (HISTORICAL BACKTEST, 2026-09-18 -> 2026-10-18 UTC).
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv/bin/python
D=research/replay_2026-09-18_30d
T0=1789689600000
T1=1792281600000
mkdir -p "$D/runs"
{
  for s in breakout launch_sniper squeeze trend crash_reversal regime_trend \
           volatility_breakout trend_pullback range_reversion orderflow_imbalance; do
    echo "--run-id A_$s --strategies $s"
  done
  echo "--run-id B_combined"
  echo "--run-id B_deployed --no-orderbook"
} | xargs -P 8 -L 1 $PY -m paperbot_pro.replay.run_week --data "$D/data" \
    --books "$D/data/book_samples" --out "$D/runs" --t0 $T0 --t1 $T1 \
    --universe-file "$D/universe_daily.json" --extra-instruments "$D/extra_instruments.json" \
    > "$D/runs/runs.log" 2>&1
$PY -m paperbot_pro.replay.report --runs "$D/runs" --data "$D/data" \
    --books "$D/data/book_samples" --out web/public/replay/replay-2026-09-18_30d.json --t0 $T0 --t1 $T1 \
    --universe-file "$D/universe_daily.json"
