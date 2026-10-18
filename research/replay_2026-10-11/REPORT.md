# Seven-Day Historical Replay: 10-Strategy Extreme Lab

> **HISTORICAL BACKTEST. This is not live paper trading.** One past week of virtual money replayed through the
> unchanged `LabEngine`. Every sleeve has fewer than 30 completed trades, so nothing here is statistically
> validated or predictive. **A** (independent $50 sleeves) and **B** (combined shared $500 portfolio) are separate
> experiments: never add A results together, and never treat them as B.

- **Window:** 2026-10-11 00:00 UTC → 2026-10-18 00:00 UTC (end exclusive). There were 10,080 one-minute engine cycles per run. Each run started flat, so no warm-up trades exist to exclude.
- **Engine:** the real `paperbot_pro.lab.engine.LabEngine.run_cycle`, unmodified. It runs with the stock `LabSettings` (10× isolated leverage, $5 risk per trade for the extreme cohort and $2 for the research cohort, 3 open slots, $15 combined planned risk, $50 trailing high-water-mark lock, $30 research equity floor, 2×ATR initial stop, 2.5×ATR trailing stop, 0.05% slippage, 0.06% taker fee, 0.3% spread gate, 90 s quote freshness).
- **Harness:** `src/paperbot_pro/replay/` (fetch → order-book sampler → point-in-time market → runner → extract → report).
- **Dashboard:** `/replay` in the web app, payload `web/public/replay/replay-2026-10-11.json`.
- **Reproduce:** `research/replay_2026-10-11/run_all.sh`.

## 1. Audit findings (read before the numbers)

| # | Finding | Effect on this replay |
|---|---|---|
| F1 | **Hybrid 50%-at-2R exit is still NOT implemented.** Every position opens with `with_target=False` and exits in full via the ATR trail, a gap stop, liquidation or a lock exit. | The implemented exits were replayed. **No partial exits occurred.** The hybrid exit remains a proposed separate experiment. |
| F2 | **`MarketData` has no `htf_trend()` hook**, so `_scan_context` always defaults `htf_trend_4h` and `htf_trend_1h` to `"up"`. | As deployed, Regime-Aware Trend and Trend Pullback are **long-only** with no real higher-timeframe filter. Both were replayed as deployed: 0 shorts. |
| F3 | **`MarketData` has no `orderbook()` hook**, so as deployed Order-Flow Imbalance can **never** trade. | Main runs wire in the authentic archived L2 book to test the logic itself. `B_deployed` keeps the true deployed wiring. |
| F4 | **Bug: the research-cohort "locked (equity floor)" check uses *cash*, not *equity*** (`LabStore.strategy_status`). Opening a 10× position moves margin out of cash (cash ≈ $50 − ~$33). The sleeve then reports "locked" and rejects new entries while its equity is still ~$50. | This is deployed behaviour, so it was kept. It caused 1,870 Order-Flow, 107 Volatility-Breakout and 10 Trend-Pullback rejections in A. It is a real defect and should be fixed with its own tests. |
| F5 | At 10× with $5 risk, **one extreme-cohort position can consume the whole $50 sleeve's cash**. Later signals fail with "position too small after margin/lot constraints". | 63 Breakout and 104 Trend Rider rejections in A. |
| F6 | **Launch Sniper is structurally unable to fire.** "Young" means fewer than 200 one-hour bars; `min_bars` = 60; the universe is the top-20 market caps only. | 0 eligible decision points in the window (see §6). |
| F7 | **The Squeeze thresholds were unreachable this week.** It needs \|funding\| ≥ 0.03%/8h; the maximum observed on any symbol was 0.01%. | 0 signals. This is not tuned away; it is reported as is. |
| F8 | Range Mean Reversion's described "exit to midpoint/VWAP" is **not implemented**. Order-Flow's described "aggressive flow" term is **not implemented** (it uses depth imbalance only). | The code as written was replayed. |

## 2. A: independent $50 sleeves (each run alone)

Sorted by net return. Final equity includes mark-to-market of positions still open at 00:00 UTC on Oct 18. "Unreal." is the uPnL net of entry fees and funding already paid.

| Strategy | Fidelity | Trades (+open) | Win% | Avg win / loss | PF | Expectancy | Realised | Unreal. | Final equity | Return | Max DD | Fees | Funding | Slippage (est.) | Liq. | Largest win / loss | Long / short P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Crash Reversal Hunter | HIGH | 5 | 40% | 8.67 / −1.61 | 3.58 | +2.50 | +12.49 | 0.00 | **62.49** | **+24.98%** | 24.5% ($13.87) | 0.59 | 0.10 | 0.49 | 0 | +9.61 / −2.16 | 5L +12.49 / 0S |
| Range Mean Reversion | HIGH | 6 (+3) | 50% | 3.99 / −1.96 | 2.03 | +1.02 | +6.09 | +5.24 | **61.33** | **+22.67%** | 17.2% ($10.30) | 1.11 | −0.05 | 0.92 | 0 | +7.94 / −2.00 | 0L / 6S +6.09 |
| Order-Flow Imbalance* | MEDIUM (archived L2) | 13 (+2) | 38% | 1.84 / −1.38 | 0.83 | −0.14 | −1.83 | +2.58 | 50.75 | +1.50% | 22.7% ($12.34) | 2.02 | −0.02 | 1.69 | 0 | +3.74 / −1.99 | 8L −5.86 / 5S +4.03 |
| New Coin Launch Sniper | NOT TESTABLE | 0 | — | — | — | — | 0 | 0 | 50.00 | 0.00% | 0 | 0 | 0 | 0 | 0 | — | — |
| Liquidation Squeeze Hunter | LIMITED (proxy) | 0 | — | — | — | — | 0 | 0 | 50.00 | 0.00% | 0 | 0 | 0 | 0 | 0 | — | — |
| Regime-Aware Trend | MEDIUM (as deployed, long-only) | 6 | 33% | 1.67 / −1.96 | 0.43 | −0.75 | −4.49 | 0.00 | 45.51 | −8.99% | 22.3% ($12.79) | 0.98 | 0.05 | 0.82 | 0 | +3.20 / −2.00 | 6L −4.49 / 0S |
| Trend Rider | HIGH | 14 (+3) | 36% | 3.14 / −3.04 | 0.57 | −0.83 | −11.66 | +3.57 | 41.91 | −16.18% | **59.5% ($32.27)** | 3.62 | 0.24 | 3.02 | 0 | +10.46 / −5.06 | 6L −13.97 / 8S +2.31 |
| Volatility Breakout | HIGH | 13 (+1) | 23% | 0.65 / −1.26 | 0.15 | −0.82 | −10.70 | −0.86 | 38.44 | −23.11% | 27.7% ($14.16) | 2.14 | 0.14 | 1.78 | 0 | +0.90 / −1.91 | 8L −8.50 / 5S −2.20 |
| Trend Pullback | MEDIUM (as deployed, long-only) | 12 (+1) | 17% | 1.41 / −1.73 | 0.16 | −1.21 | −14.53 | +1.69 | 37.17 | −25.67% | 37.3% ($19.51) | 2.20 | 0.13 | 1.83 | 0 | +2.13 / −2.02 | 12L −14.53 / 0S |
| Explosive Breakout Hunter | HIGH | 13 (+2) | 15% | 0.69 / −1.86 | 0.07 | −1.47 | −19.13 | −3.20 | **27.67** | **−44.65%** | 45.8% ($23.31) | 3.43 | 0.23 | 2.85 | 0 | +0.99 / −5.00 | 6L −13.91 / 7S −5.22 |

\* Order-Flow trades only because this replay wired the archived book in. As deployed it makes 0 trades (F3).

**Rankings (all small-sample; none statistically validated):**
- **By net return:** Crash Reversal > Range Reversion > Order-Flow > (Launch Sniper = Squeeze, no trades) > Regime Trend > Trend Rider > Volatility Breakout > Trend Pullback > Breakout.
- **By risk-adjusted return** (return ÷ max(DD%, 0.5)): Range Reversion (+1.32) > Crash Reversal (+1.02) > Order-Flow (+0.07) > no-trade sleeves (0) > Trend Rider (−0.27) > Regime Trend (−0.40) > Trend Pullback (−0.69) > Volatility Breakout (−0.83) > Breakout (−0.97).
- **By lowest drawdown:** the no-trade sleeves, then Range Reversion 17.2% … Trend Rider 59.5%.
- **Concentration warning:** Crash Reversal's entire gain is **2 trades on one day** (Oct 15: ZEC +7.72, NEAR +9.61); its other 3 trades lost. Range Reversion's realised gain is mostly **1 trade** (LTC +7.94). Both are single-event outcomes.
- **Rejection reasons:**
  - Breakout and Trend Rider: "position too small after margin/lot constraints" (F5).
  - Volatility Breakout, Order-Flow and Trend Pullback: "locked (equity floor)" while a position is open (F4 bug).
  - Regime Trend: re-entry cooldown.
- **Locks:** no research sleeve reached the real $30 equity floor. No trailing-drawdown lock fired in A.

## 3. B: combined $500 portfolio (shared rails, separate from A)

| Run | Wiring | Trades (+open) | Win% | PF | Realised | Unreal. | Final equity | Return | Max DD | Fees | Funding | Slippage (est.) | Liq. | Long / short P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **B_combined** | archived L2 wired (all 10 strategies active) | 29 (+3) | 27.6% | 0.59 | −15.15 | −6.14 | **478.72** | **−4.26%** | 6.11% ($31.17) | 6.50 | −0.03 (net received) | 5.41 | 0 | 16L −13.53 / 13S −1.61 |
| B_deployed | exact deployed wiring (no order book) | 26 (+3) | 38.5% | 0.85 | −3.90 | −5.20 | 490.90 | −1.82% | 3.70% ($18.62) | 6.26 | +0.26 | 5.22 | 0 | 13L −8.90 / 13S +5.01 |

- The $50 trailing-drawdown lock **did not trigger**: the peak was $509.77 and the trough $478.60.
- No strategy lock, liquidation or integrity lock occurred.
- **Shared rails dominate the outcome.** With 3 slots, the first strategy in catalogue order to signal on a symbol takes it. Order-Flow fires every minute, so in B_combined it took **16 of 32 entries** and the slot limit rejected other strategies 399+ times.
- The two best A sleeves, **Crash Reversal and Range Reversion, made 0 trades in B_combined** because every slot was full when they signalled. A rankings therefore do not carry over to B.
- B per-strategy contribution (B_combined): Order-Flow −13.32, Breakout −11.59, Trend +1.94, Volatility Breakout +1.46, Regime Trend +1.22, Trend Pullback −1.00, all others 0.

The B_combined trade list (exit times are UTC; fees include entry and exit):

| Strategy | Sym | Side | Entry | Exit | Entry px | Exit px | Reason | Fees | Funding | Net |
|---|---|---|---|---|---|---|---|---|---|---|
| trend | SOL | short | 10-11 00:00 | 10-11 15:41 | 109.975 | 110.436 | STOP | 0.54 | −0.020 | −2.41 |
| breakout | ETH | long | 10-11 16:00 | 10-11 21:16 | 2537.1 | 2521.55 | STOP | 0.58 | 0.000 | −3.53 |
| orderflow | BTC | long | 10-11 00:00 | 10-11 21:17 | 82990.1 | 83288.2 | STOP | 0.40 | +0.004 | +0.79 |
| orderflow | ADA | short | 10-11 21:20 | 10-12 04:58 | 0.250775 | 0.255761 | STOP | 0.11 | −0.010 | −1.99 |
| orderflow | BTC | long | 10-12 05:00 | 10-12 08:18 | 84145.5 | 83495.6 | STOP | 0.20 | +0.010 | −1.51 |
| orderflow | XLM | long | 10-11 21:27 | 10-12 11:38 | 0.201701 | 0.199581 | STOP | 0.13 | +0.013 | −1.31 |
| regime_trend | NEAR | long | 10-11 00:00 | 10-12 11:49 | 5.29665 | 5.59408 | STOP | 0.07 | +0.025 | +3.20 |
| orderflow | SOL | long | 10-12 08:24 | 10-12 12:33 | 111.736 | 110.424 | STOP | 0.13 | 0.000 | −1.45 |
| orderflow | ZEC | long | 10-12 12:00 | 10-12 16:47 | 1291.4 | 1251.35 | STOP | 0.06 | +0.005 | −1.67 |
| regime_trend | NEAR | long | 10-12 12:00 | 10-12 16:52 | 5.65082 | 5.40034 | STOP | 0.05 | +0.004 | −1.98 |
| orderflow | ETH | long | 10-12 17:00 | 10-12 22:41 | 2515.6 | 2480.31 | STOP | 0.15 | 0.000 | −1.91 |
| orderflow | XRP | short | 10-12 16:54 | 10-13 02:04 | 1.36362 | 1.35469 | STOP | 0.14 | +0.008 | +0.62 |
| breakout | BTC | short | 10-12 13:00 | 10-13 02:12 | 82669.4 | 82616.9 | STOP | 0.50 | −0.008 | −0.22 |
| breakout | ETH | short | 10-13 00:00 | 10-13 02:12 | 2446.31 | 2473.77 | STOP | 0.03 | 0.000 | −0.30 |
| trend | XMR | short | 10-13 04:00 | 10-13 07:37 | 531.704 | 542.51 | STOP | 0.28 | 0.000 | −4.92 |
| orderflow | LTC | long | 10-13 02:06 | 10-13 10:43 | 61.2506 | 60.7958 | STOP | 0.09 | −0.001 | −0.63 |
| orderflow | ADA | short | 10-13 10:44 | 10-13 14:18 | 0.232384 | 0.239048 | STOP | 0.08 | 0.000 | −1.99 |
| orderflow | DOGE | long | 10-13 02:13 | 10-14 12:31 | 0.0831415 | 0.083391 | STOP | 0.09 | +0.014 | +0.12 |
| trend | XLM | short | 10-13 08:00 | 10-15 14:49 | 0.194303 | 0.182792 | STOP | 0.24 | −0.039 | +12.05 |
| orderflow | BTC | short | 10-13 15:00 | 10-15 14:49 | 83451 | 81697.9 | STOP | 0.10 | −0.015 | +1.67 |
| volatility_breakout | ETH | short | 10-14 13:00 | 10-15 15:04 | 2474.65 | 2404.49 | STOP | 0.12 | −0.010 | +2.70 |
| orderflow | BNB | long | 10-15 15:00 | 10-16 15:23 | 729.805 | 723.069 | STOP | 0.12 | +0.014 | −1.08 |
| volatility_breakout | ETH | long | 10-15 16:00 | 10-16 16:01 | 2440.38 | 2425.7 | STOP | 0.09 | +0.013 | −0.54 |
| orderflow | XLM | long | 10-16 15:53 | 10-16 17:19 | 0.18079 | 0.178728 | STOP | 0.12 | 0.000 | −1.31 |
| orderflow | DOGE | short | 10-16 17:19 | 10-16 23:03 | 0.0794702 | 0.0810677 | STOP | 0.11 | 0.000 | −2.00 |
| trend_pullback | BCH | long | 10-17 00:00 | 10-17 09:39 | 277.159 | 274.467 | STOP | 0.11 | −0.002 | −1.00 |
| trend | TRX | long | 10-16 17:00 | 10-17 15:35 | 0.334567 | 0.335134 | STOP | 0.65 | −0.004 | +0.27 |
| volatility_breakout | LINK | short | 10-17 13:00 | 10-17 20:35 | 12.038 | 12.0945 | STOP | 0.14 | −0.001 | −0.70 |
| breakout | BNB | short | 10-17 16:00 | 10-17 20:56 | 713.893 | 719.544 | STOP | 0.54 | 0.000 | −4.10 |

Positions open at the end of the window (mark-to-market only): orderflow BTC short +0.35 uPnL; breakout ETH short −3.23; trend BNB short −2.78.

Full trade lists for every run (A and B), including quantities, stops, margin, MFE/MAE, rationale and every signal/rejection, are in `runs/<run>.json` and on the dashboard.

## 4. Financial accounting and cost breakdown

- **Accounting identity.** For every run, cash + margin + uPnL equals initial capital + realised + net unrealised to within 1.4e-14 USD. `reconcile_lab` and the per-cycle integrity monitor ran inside the engine every cycle and **never engaged the integrity lock**.
- **Costs** (B_combined): fees $6.50, slippage $5.41 (estimated, 0.05% each side), funding −$0.03 (net received). That is **$11.88 of costs against a −$21.28 net result**. Costs are 56% of the loss, so even zero-cost execution would have lost money.
- **Spread** is real, not modelled:
  - Entries filled at the archived best ask (longs) or bid (shorts), plus slippage.
  - Tick-path stops used trade-price extremes adjusted by the observed half-spread.
- **Funding** used the actual settled Bybit rates at each 00/08/16 UTC boundary. All 16 symbols are on 8h funding, matching the engine's assumption.
- **Liquidations:** 0 in all runs. Cross-check against Bybit's **mark price** (which Bybit liquidates on): no trade's 1m mark ever crossed its liquidation estimate, so the simulation and the exchange agree.

## 5. Data sources and coverage

All data is public and read-only, with no API keys. Every file records its URL/params and fetch time, with SHA-256 in `data/manifest_rest.json` and `data/book_samples/manifest_books.json`.

| Dataset | Source | Coverage |
|---|---|---|
| 1h OHLCV (signals) | `api.bybit.com/v5/market/kline` | 16 symbols × 2,328 bars (90-day warm-up + window). **0 missing, 0 duplicate, 0 malformed.** Every in-window 1h bar equals the aggregate of its 60 one-minute bars (0 mismatches). |
| 1m OHLCV (forming bar, stop/tick path) | same, interval 1 | 16 × 10,140. 0 missing. Zero-volume minutes are real quiet minutes (e.g. TRX 1,377) and are left as recorded. |
| 1m mark price | `/v5/market/mark-price-kline` | 16 × 10,140. 0 missing. Used for the liquidation cross-check. |
| Funding | `/v5/market/funding/history` | 291 prints per symbol (21 in window), all on the 8h grid. |
| Open interest (1h) | `/v5/market/open-interest` | 16 × 2,328. Archived as context only; no strategy's code reads OI. |
| L2 order book | Bybit public archive `quote-saver.bycsi.com/orderbook/linear/…_ob200.data.zip` (recorded `orderbook.200` WS stream) | **112/112 day-files (16 × 7)**, 77.1M messages replayed in order. Max inter-message gap 16.8 s; 6 gaps >15 s across the week. **0 crossed books; 0 stale or missing samples** at cycle times. |
| Contract metadata | `/v5/market/instruments-info`, `/v5/market/risk-limit` | Tier-1 maintenance margin matches the engine's stored metadata for all 16. |
| Universe eligibility | CoinGecko `/coins/{id}/history?date=11-10-2026` | Ranked by market cap at 00:00 UTC Oct 11 with the engine's exclusion rules. **Same 20 coins as the deployed universe**; the same 16 have Bybit linear perps, all launched 2018–2024. No survivorship difference. |
| Prior-evidence artifact | `state/validation_report.json` (read-only) | See §8. |

**Untested or limited, stated honestly:**
- **Launch Sniper: NOT TESTABLE.** The only crypto USDT perps listed near the window were DRVUSDT and DNAUSDT (both 2026-10-16, verified by Bybit `launchTime`). They never reached the code's 60 closed bars before the window ended. Other listings (Oct 8–13) were tokenized stocks/ETFs, not coins, and are outside the CoinGecko top-20 universe anyway. Bybit's listing API does not return delisted instruments, so a listing-then-delisting inside the window could be missing; none is known.
- **Squeeze: LIMITED (proxy).** The code never uses liquidation data. It uses wick size plus funding. No authentic historical liquidation feed was used: Bybit's `allLiquidation` stream is live-only, and the code doesn't consume it. The replay feeds the last *settled* funding rate; the live engine reads the predicted rate, which is not archived.
- **Order-Flow: real archived L2** (not reconstructed from candles), sampled at each 60 s cycle with true age and spread. No archived trade-flow was needed because the code doesn't use it. As deployed it cannot trade (F3).

## 6. Verification and testing evidence

- **Python suite:** `pytest -q` passed **274 tests**, including the legacy 40 and 15 new `tests/pro/test_replay.py` tests. The new tests cover:
  - no unfinished or future bars, and future-served data raises;
  - funding visible only after settlement;
  - an optional order-book hook;
  - conservative ambiguous-bar sequencing: a crossed stop fills at the stop, a gap through the stop fills at the open, and reaching liquidation inside a bar is a liquidation, long and short;
  - positions not checked against bars before they opened;
  - isolated sleeve ledgers;
  - a full-run reconciliation;
  - a point-in-time order-book sampler.
- **Frontend:** `tsc --noEmit` clean, `eslint` clean (whole app), `npm run test:scanner` passes. `/replay` was rendered and exercised in a browser on a temporary dev server: slider, equity at cursor, candles truncated at the cursor, entry/exit markers. That server was then stopped.
- **No look-ahead:**
  1. Every datum the market adapter serves is checked against the simulated clock (it raises on violation). The newest timestamp served in every run equals `t1`.
  2. **Truncation test:** the B replay re-run with every byte after day 3 deleted gives **identical** results before the cutoff (948/948 signals, 17/17 trades, 4,320/4,320 equity points).
- **Execution sequencing:** signals only on bars whose close time ≤ the cycle time, entries at the next cycle's archived quote, and stops trail only on completed candles and never widen.
- **Live system unchanged.** Before and after snapshots (`live_baseline_before.txt` / `live_baseline_after.txt`) are identical: same PIDs and start times (`lab-run` 9085, `api` 9431, `run` 47046, `next-server` 3069), the same trade and position counts in all four live DBs, and the same Extreme Lab ledger and kv. The replay writes only to `research/replay_2026-10-11/runs/*.sqlite` and opens `state/paperbot_pro.sqlite` with `mode=ro` for instrument metadata.

## 7. Limitations

- **Sample size.** 7 days, 0–17 trades per sleeve. Results are dominated by 1–2 trades in the best sleeves. **No ranking is statistically meaningful.**
- **Stops.** Stops are evaluated from 1m extremes plus 60 s REST cycles. The live engine also uses WebSocket ticks, so fills here can be slightly worse (conservative). The live tick-path trailing-drawdown check with 2-reading confirmation was not emulated; the 60 s cycle check was used. The trailing-drawdown lock never came closer than $18.83 to its threshold (trough $478.60 vs threshold $459.77).
- **Squeeze funding input** is the last settled rate, not the predicted rate (see §5).
- **Fees** are the engine's 0.06% taker; Bybit's base taker is 0.055%, so fees are slightly conservative.
- **Liquidation** uses the engine's isolated estimate with tier-1 MMR. The mark-price cross-check found no disagreement.

## 8. Comparison with existing two-year evidence

- **`state/validation_report.json` (2026-10-16, outcome NEGATIVE).** This covers the same `generate_signal` logic as Trend Rider, on 8 markets over ~2 years: 474 trades, mean −1.75%, 3/8 markets profitable, PF 0.16–1.11, and 0/3 walk-forward windows per the plan of record.
  - This week's Trend Rider sleeve (−16.18%, PF 0.57) is **consistent with that negative evidence**.
  - The larger percentage swing comes from the Lab's sizing ($5 risk on a $50 sleeve = 10% per trade, versus 0.5% in the main engine). It is not a different edge.
- **Research cohort.** The README records "3 of 4 testable strategies lose heavily" over the long sample, but the numeric results were not persisted, so no quantitative comparison is possible.
  - This week Volatility Breakout and Trend Pullback lost heavily (−23%, −26%), consistent with that record.
  - Range Reversion gained (+22.7% on 6 closed + 3 open trades). A one-week gain does not overturn longer negative evidence.
- **No strategy has evidence of a durable edge.**

## 9. Recommendation for forward-paper testing (no profitability claim)

1. **Fix before more forward-paper data is collected,** otherwise the live lab measures defects, not strategies:
   - F4: the cash-vs-equity "locked" bug.
   - F2: no HTF trend, which makes Regime and Pullback long-only.
   - F3: no order-book hook.

   Each needs its own tests and should be a separate change.
2. **Candidates to keep forward-paper testing, as low-confidence hypotheses:** Range Mean Reversion and Crash Reversal. They were the only sleeves positive both net and risk-adjusted, but each result rests on 1–2 trades. Give them independent sleeves: they never got a slot in shared B.
3. **Order-Flow Imbalance** (archived-L2 test): near-flat in A, but it **hurt B** by monopolising slots (16/32 entries, −$13.32). Only worth testing after F3 is wired and with an explicit per-strategy entry-rate limit, decided before seeing more data.
4. **Do not prioritise** Breakout (−44.65%, PF 0.07), Trend Pullback, Volatility Breakout or Trend Rider. Each lost this week and has negative longer-run evidence.
5. **Launch Sniper and Squeeze** produced no evidence either way. Their eligibility thresholds and definitions should be reviewed as design questions, without tuning them to this week's data.
6. **The hybrid 50%-at-2R exit** should be implemented and tested as a separate, pre-registered experiment (`docs/PENDING-FEATURES.md`). It played no part in these results.

## 10. File index

- `REPORT.md`: this report.
- `run_all.sh`: reproduces every run.
- `runs/*.json`: per-run results, trades, signals and equity. The `*.sqlite` files are not committed.
- `data/manifest_rest.json`, `data/book_samples/manifest_books.json`: dataset IDs and SHA-256.
- `raw/meta/`: instrument snapshot and the CoinGecko rank check.
- `leakcheck/`: truncation run.
- `live_baseline_before.txt`, `live_baseline_after.txt`: live-system snapshots.
- The raw order-book zips (7.3 GB) and 1m/book-sample files are kept locally and git-ignored. They can be re-downloaded and SHA-verified from the manifests.
