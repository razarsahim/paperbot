#!/bin/bash
# 24-hour replay (HISTORICAL BACKTEST) of all 10 strategies on 2026-10-15 UTC,
# reusing the 30-day dataset (same data, daily universe, archived L2).
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv/bin/python
S=research/replay_2026-09-18_30d
D=research/replay_2026-10-15_24h
T0=1792022400000
T1=1792108800000
mkdir -p "$D/runs"
{
  for s in breakout launch_sniper squeeze trend crash_reversal regime_trend \
           volatility_breakout trend_pullback range_reversion orderflow_imbalance; do
    echo "--run-id A_$s --strategies $s"
  done
  echo "--run-id B_combined"
  echo "--run-id B_deployed --no-orderbook"
} | xargs -P 8 -L 1 $PY -m paperbot_pro.replay.run_week --data "$S/data" \
    --books "$S/data/book_samples" --out "$D/runs" --t0 $T0 --t1 $T1 \
    --universe-file "$S/universe_daily.json" --extra-instruments "$S/extra_instruments.json" \
    > "$D/runs/runs.log" 2>&1
$PY -m paperbot_pro.replay.report --runs "$D/runs" --data "$S/data" \
    --books "$S/data/book_samples" --out web/public/replay/replay-2026-10-15_24h.json \
    --t0 $T0 --t1 $T1 --universe-file "$S/universe_daily.json"
