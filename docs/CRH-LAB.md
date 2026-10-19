# Crash Reversal Hunter (CRH) Trading Lab

**PAPER ONLY.** Historical backtests on archived public Bybit data, a read-only forward-paper view of the running Extreme Lab sleeve, and a live-data signal scanner. No orders, keys, balances or real money anywhere in this code.

## Start / stop

```bash
# 1. CRH Lab API (separate process on 127.0.0.1:8778; the dashboard API on 8777 is untouched)
.venv/bin/propaper crh-api            # add --seed on first use to import research/*/data into the cache
# 2. Dashboard
cd web && npm run dev                 # http://localhost:3000/crh   (or the port you run it on)
```
Stop either with Ctrl-C. The API keeps results in `state/crh_lab.sqlite` + `state/crh_runs/*.json.gz` and market data in `cache/` (both git-ignored). Nothing in `state/*.sqlite` belonging to the live engines is written.

Dashboard URL: **http://localhost:3000/crh** (left nav: "CRH Lab").

## What the page does

| Tab | Content | Label |
|---|---|---|
| Backtest | Controls (range presets 24h/48h/7d/30d/90d or custom UTC dates; top 20/50/100 or explicit coins; capital $50–$5,000; 1–25× isolated; risk % of capital; optional strategy loss trigger; 1h or experimental 1m signals; exact vs approximate execution data), Run / Re-run / Stop with live progress and stage, overview tiles, equity curve with lock threshold, daily realised vs mark-to-market P&L, interactive 1h chart (entries, initial→trailed stop band, exits with P&L, signal candles, volume, ATR pane; click a trade row to focus it), filterable trade history incl. open trades and rejected signals, JSON/CSV export, audit block (sources, fidelity, universe eligibility, config, risk events) | HISTORICAL BACKTEST |
| Compare | Pick 2+ stored runs: side-by-side metrics, overlaid equity curves, flags when windows/fidelity/universe/capital/leverage differ, descriptive risk-adjusted verdict (return ÷ max drawdown) | HISTORICAL BACKTEST |
| Signal scanner | Per-coin drop/hammer status; historical (per run, with near-misses and rejection reasons) or current (last closed 1h candle from public klines; never trades) | HISTORICAL BACKTEST / LIVE MARKET DATA |
| Forward paper | The live Extreme Lab `crash_reversal` sleeve read directly from its DB in read-only mode: equity, realised/unrealised, positions, trades, lock state | FORWARD PAPER |

Historical figures are never mixed with the forward-paper balance.

## Baseline vs experiments

The default is the deployed sleeve's rules, verbatim (`src/paperbot_pro/crh/config.py::CRHConfig`): 1h candles, ≤ −8% over 24 bars, bullish hammer on the closed candle, 2.0×ATR(14) initial stop, 2.5×ATR trail on each closed candle (never widened), no fixed target, 0.05% slippage, 0.06% taker, 0.3% spread gate, 90 s quote freshness. Rails scale with capital in the deployed proportions ($5 risk / $15 combined / $50 trailing drawdown on $50 → 10% / 30% / 100% of capital). Changing capital or leverage keeps the label "BASELINE rules, capital/leverage scaled"; changing a rule (1m signals, thresholds, loss trigger, approximate data) labels the run EXPERIMENT. Nothing is auto-optimised against the test window.

## How the fast replay works (and why it is exact)

`src/paperbot_pro/crh/engine.py` replays the live `LabEngine` cycle order (tick path → monitor → locks → trail/scan/entry → equity/HWM) but walks by signal candle and only drops to 1-minute resolution while a position is open. All formulas are imported from `perp.py`; the signal is a parameterised copy of the deployed evaluator with a parity test. `tests/pro/crh/test_equivalence.py` runs the original minute loop on real Oct 15–16 2026 data and asserts trade-for-trade, signal-for-signal and minute-by-minute equity equality (max diff 1.4e-14).

**Measured benchmark** (`research/crh_lab_benchmark.py`, Oct 15–19 2026, 16 instruments, same archived data):

| | Original minute loop | Fast engine, cached | Fast engine, 2nd identical run |
|---|---|---|---|
| Wall time | 195.5 s replay + 11.4 s data load | **0.62 s** whole pipeline (replay 0.13 s) | 0.23 s |
| Cycles | 5,760 | 2,007 | — |
| Result | 2 trades, $67.3325 | 2 trades, $67.3325 | identical |

A first run on a new window pays for data: 1h/1m/funding candles via Bybit REST (concurrent, cached forever), the CoinGecko universe (rate-limited ≈2.2 s per coin, cached per coin per day; a top-50 window costs ≈5 min the first time, then ≈0 s), and L2 archives only for the symbol-days a signal/position actually needs (≈100–160 MB each, downloaded → sampled → deleted; the sample is cached).

## Data fidelity

- **exact**: archived Bybit L2 (`orderbook.200`) best bid/ask at every engine cycle + 1m price path for stops/liquidation; funding from settled history; this is what the equivalence test certifies.
- **exact-with-gaps**: as above but some symbol-days had no archive file; those are listed in the run's warnings.
- **approximate**: no L2; entries/monitoring use the 1-minute open ± a synthetic 0.05% half-spread. Always labelled; never merged with exact results.

## Risk/accounting checks stored in every run

Look-ahead guard (newest served timestamp ≤ clock, asserted in-process), accounting identity (cash + margin + uPnL = equity, gap stored), stops never widened, mark-price liquidation cross-check (exchange liquidates on mark; mismatches listed), unmonitored cycles, funding events, daily realised vs mark-to-market split, open positions preserved at window end.

Finding on the "$50 sleeve below $30" question: the $30 floor exists only for the research cohort; the deployed CRH (extreme cohort) has no per-strategy floor by design. The lab exposes an explicit, labelled loss trigger (default none = deployed).

## Universe

Daily top-N by CoinGecko market cap at 00:00 UTC (last reading at or before midnight), engine exclusions (stablecoins, wrapped, liquid-staking), mapped to Bybit USDT perps `{SYM}USDT` or `1000{SYM}USDT` (contract multiplier recorded), eligible only if active, listed before that day and with public tier-1 maintenance margin. Every ineligible coin is listed with its reason. **Limitations:** candidates are the 3N coins ranked highest *today*, so a coin that was top-N but has since fallen below rank 3N is missed; delisted contracts cannot be verified from Bybit's public API; the fee is the engine default 0.06% (Bybit's base taker is 0.055%, slightly conservative).

## Tests

`tests/pro/crh/`: signal parity, prescan/near-miss, warm-up, closed-candle boundaries, no quote at signal, trailing, liquidation-over-stop on gaps, funding boundaries, fees/slippage, slot/combined/cash limits, trailing-drawdown lock + emergency exits, loss trigger, multiday carry, accounting identity, approximate mode, cancel; cache coverage/incremental/offline/resume/seed; universe mapping; API job lifecycle/cancel/reuse/exports/compare/scanner/forward; offline regression fixtures ($67.33 Oct 15–19 top-20; $59.28 top-50 Oct 17–19 with ENA open); original-vs-fast equivalence on real data.
