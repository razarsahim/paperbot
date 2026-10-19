# 30-Day Historical Replay: 10-Strategy Extreme Lab

> **HISTORICAL BACKTEST. This is not live paper trading.** Thirty past days of virtual money replayed through the
> unchanged `LabEngine`. **A** (independent $50 sleeves) and **B** (combined shared $500 portfolio) are separate
> experiments: never add A results together or treat them as B. One past month is not validation, and nothing
> here predicts future returns.

- **Window:** 2026-09-18 00:00 UTC → 2026-10-18 00:00 UTC (end exclusive). Each run is 43,200 one-minute engine cycles and starts flat, with a 90-day 1h warm-up history available and no warm-up trades.
- **Engine and rules:** identical to the 7-day replay (`../replay_2026-10-11/REPORT.md` §1–§4). That includes stock `LabSettings`, 10× isolated leverage, $5 per-trade risk for the extreme cohort and $2 for the research cohort, 3 slots, $15 combined risk, the $50 trailing high-water-mark lock and the $30 research floor.
- **Exits:** only the implemented ones: 2×ATR initial stop and a 2.5×ATR trail on closed 1h candles. **The hybrid 50%-at-2R exit is still not implemented; no partial exits occurred.**
- **New in this window:** **daily universe membership.** The live universe refreshes every 24h from CoinGecko ranks, so the replay rebuilds the top-20 each UTC day (see §5).
- **Reproduce:** `research/replay_2026-09-18_30d/run_all.sh`. Dashboard: `/replay` → "30 days".

All the audit findings from the 7-day report still apply:
- F1: no hybrid exit.
- F2: Regime and Pullback are long-only as deployed because there is no HTF hook.
- F3: Order-Flow can't trade as deployed (no order-book hook).
- F4: the research "locked" status uses cash, not equity.
- F5: one 10× extreme position can consume a sleeve's cash.
- F6: Launch Sniper is structurally idle.
- F8: Range Reversion has no midpoint exit; Order-Flow has no trade-flow term.

## 1. Headline

| | Final equity | Return | Trades | Note |
|---|---|---|---|---|
| **B combined (archived L2 wired)** | **$522.15** | **+4.43%** | 31 | Peaked at **$572.63 (+14.5%) on Sep 21**. **Trailing-drawdown lock fired Sep 27 18:12** at $522.62. Locked and flat for the remaining 20 days; the replay applies no manual reset. |
| B combined (as-deployed wiring) | $512.03 | +2.41% | 30 | Same pattern: peak $562.56 on Sep 21, lock on Sep 27 14:28. |

The B result is **"9.75 days of trading, then the drawdown lock"**, not 30 days of strategy performance. The lock protected the remaining $22 gain, but it also means the last 20 days say nothing about B. In live use, a human `lab-reset` would have changed everything after Sep 27, and this replay doesn't model that.

## 2. A: independent $50 sleeves (30 days, each run alone)

Sorted by net return. Every position was closed by the window end except Range Reversion's 2.

| Strategy | Fidelity | Trades | Win% | Avg win / loss | PF | Expectancy | Final equity | Return | Max DD | Fees | Funding | Slippage | Liq. | Locks | Long / short P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Crash Reversal Hunter | HIGH | 19 ⚠ | 47% | 7.32 / −3.54 | 1.86 | +1.61 | **80.57** | **+61.14%** | 52.5% ($39.34) | 2.38 | 0.45 | 1.99 | 0 | — | 19L +30.57 / 0S |
| Trend Rider | HIGH | 24 ⚠ | 33% | 5.13 / −2.53 | 1.01 | +0.02 | 50.53 | +1.05% | 50.0% ($50.48) | 6.32 | 0.55 | 5.26 | 0 | **trailing DD Sep 27** (peak $101.01) | 16L +23.09 / 8S −22.56 |
| Range Mean Reversion | HIGH | 32 (+2 open) | 38% | 2.58 / −1.64 | 0.94 | −0.06 | 50.49 | +0.98% | 39.3% ($21.44) | 4.26 | −0.01 | 3.55 | 0 | — | 14L −5.04 / 18S +3.11 |
| New Coin Launch Sniper | NOT TESTABLE | 0 | — | — | — | — | 50.00 | 0.00% | 0 | 0 | 0 | 0 | 0 | — | — |
| Liquidation Squeeze Hunter | LIMITED (proxy) | 1 ⚠ | 0% | — / −4.32 | 0.00 | −4.32 | 45.68 | −8.64% | 15.3% | 0.14 | −0.10 | 0.12 | 0 | — | 0L / 1S −4.32 |
| Regime-Aware Trend | MEDIUM (long-only as deployed) | 55 | 33% | 2.35 / −1.46 | 0.78 | −0.21 | 38.18 | −23.65% | 56.7% ($48.94) | 6.53 | 0.78 | 5.44 | 0 | — | 55L −11.82 / 0S |
| Trend Pullback | MEDIUM (long-only as deployed) | 57 | 28% | 2.50 / −1.46 | 0.67 | −0.35 | 30.02 | −39.96% | 62.8% ($50.63) | 8.47 | 0.51 | 7.06 | 0 | **trailing DD Oct 15** (peak $80.65) | 57L −19.98 / 0S |
| Volatility Breakout | HIGH | 46 | 30% | 1.93 / −1.48 | 0.57 | −0.44 | 29.82 | −40.36% | 57.4% ($40.17) | 5.41 | 0.63 | 4.51 | 0 | **$30 floor Oct 5** | 26L −0.76 / 20S −19.42 |
| Order-Flow Imbalance* | MEDIUM (archived L2) | 48 | 25% | 2.27 / −1.32 | 0.57 | −0.43 | 29.60 | −40.80% | 58.2% ($41.24) | 5.56 | 0.14 | 4.64 | 0 | **$30 floor Oct 4** | 23L +3.99 / 25S −24.39 |
| Explosive Breakout Hunter | HIGH | 26 ⚠ | 31% | 4.65 / −3.45 | 0.60 | −0.96 | 25.07 | −49.85% | 66.9% ($50.73) | 6.20 | 0.62 | 5.17 | 0 | **trailing DD Sep 28** (peak $75.81) | 20L −13.48 / 6S −11.45 |

⚠ = fewer than 30 completed trades (small sample). \* Order-Flow trades only because the replay wires in the archived L2 book; as deployed it cannot trade.

**Rankings. None is statistically validated: a 30-day sample, several fewer than 30 trades, and no out-of-sample test.**
- **By net return:** Crash Reversal > Trend Rider > Range Reversion > (Launch Sniper = 0) > Squeeze > Regime Trend > Trend Pullback > Volatility Breakout > Order-Flow > Breakout.
- **By return ÷ max drawdown:** Crash Reversal (+1.16) > Range Reversion (+0.02) ≈ Trend Rider (+0.02) > Launch Sniper (0) > Regime Trend (−0.42) > Squeeze (−0.56) > Trend Pullback (−0.64) > Order-Flow (−0.70) > Volatility Breakout (−0.70) > Breakout (−0.75).

**What the numbers say, honestly:**
- **Crash Reversal** is the only sleeve clearly positive (PF 1.86), and it stays slightly positive (+$2.23) even without its 2 best trades. But it has only 19 trades, all long, clustered in **three crash episodes** (Sep 20 XMR; Oct 8–9 ADA/ZEC/NEAR; Oct 15 ZEC/NEAR). Its drawdown hit 52%. This is one regime-dependent pattern, not a demonstrated edge.
- **Trend Rider** doubled to $101 by Sep 27, then gave it all back and hit its own trailing-drawdown lock. That's +1% net with a 50% drawdown.
- **Range Reversion** finished flat (+0.98%, PF 0.94). Its strong 7-day result was not representative of the month.
- **Regime, Pullback, Volatility Breakout, Order-Flow and Breakout all lost 24–50%**, with PF 0.57–0.78 over 26–57 trades each. These are the largest samples and the clearest negative evidence.
- **Squeeze** fired once this month (a short; funding crossed ±0.03% on BNB/TRX/XMR) and lost $4.32. **Launch Sniper** had no eligible market (F6).
- **Rejections:**
  - Research sleeves are dominated by the F4 cash-vs-equity "locked" bug: Regime 1,089, Order-Flow 7,150, Volatility 301, Pullback 94, Range 33.
  - Extreme sleeves are dominated by "position too small" (F5) and, after their trailing locks, "Lab locked".

## 3. B: combined $500 portfolio (shared rails)

| Run | Trades | Win% | Avg win / loss | PF | Final equity | Return | Max DD | Fees | Funding | Slippage | Liq. | Long / short P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **B_combined** (archived L2) | 31 | 25.8% | 7.39 / −1.61 | 1.60 | **522.15** | **+4.43%** | 8.82% ($50.48) | 5.30 | 0.71 | 4.41 | 0 | 17L **+45.51** / 14S −23.36 |
| B_deployed | 30 | 30.0% | 6.07 / −2.03 | 1.28 | 512.03 | +2.41% | 8.98% ($50.53) | 5.78 | 0.80 | 4.82 | 0 | 20L +37.80 / 10S −25.77 |

**Per-strategy contribution in B_combined:**
- Trend +25.09 (5 trades; the top 2 are ETH longs: +18.17 and +13.27)
- Regime Trend +11.58 (8 trades)
- Breakout −3.90
- Volatility Breakout −3.47
- Order-Flow −7.15 (14 trades)
- Squeeze, Crash Reversal, Range Reversion, Trend Pullback and Launch Sniper: 0 trades. They were slot-blocked before Sep 27 and lock-blocked after it.

**Timeline:**
1. The gain came almost entirely from Sep 18–21 trend longs.
2. Equity then bled $50 from the $572.63 peak.
3. The trailing-drawdown breach on Sep 27 locked all strategies and emergency-exited 3 open positions at observed quotes.
4. No further entries were possible: there were 6,252 "Lab locked" rejections for Order-Flow alone.

So the +4.43% is a lock-protected early gain, not evidence of sustained performance. **A rankings do not carry over to B:** the best A sleeve (Crash Reversal) made **zero** trades in B.

## 4. Accounting, costs and verification

- **Accounting identity:** holds in every run (|gap| ≤ 4e-14 USD). The per-cycle integrity monitor never engaged.
- **Costs** (B_combined): fees $5.30, slippage $4.41 (estimated), funding $0.71 paid. Entries used archived best bid/ask.
- **Liquidations:** 0 in all runs. The **mark-price cross-check** found no trade whose 1m mark crossed its liquidation estimate (0 mismatches).
- **No look-ahead:**
  - Every served datum is checked against the clock, and the max served timestamp equals the window end.
  - **Truncation test:** B rerun with all data after day 10 deleted is **identical** before the cutoff (4,874/4,874 signals, 31/31 trades, 14,400/14,400 equity points).
- **Tests:** `pytest -q` passes 275 tests, including 16 replay tests; one new test covers daily universe switching. The frontend passes `tsc` and `eslint`.
- **Live system unchanged:** `live_baseline_before.txt` and `live_baseline_after.txt` are byte-identical (same PIDs, start times, trade/position counts and ledgers). The replay opens `state/` only read-only.

## 5. Data and universe

| Dataset | Coverage |
|---|---|
| 1h OHLCV, 90-day warm-up | 19 symbols × 2,880 bars; **0 missing, duplicate or malformed**; in-window 1h bars equal their 1m aggregates (0 mismatches) |
| 1m OHLCV + 1m mark | 43,260 each per symbol; 0 missing |
| Funding / OI (1h) | 360 funding prints per symbol, all on the 8h grid; 2,880 OI rows per symbol (OI is context only) |
| L2 order book (Bybit ob200 archive) | **520 day-files**: 17 symbols × 30 days, plus CC and BTW × 5 days from their universe entry to the window end. 360.8M messages replayed; max gap 16.8 s; 10 gaps >15 s; **0 crossed books; 0 stale or missing samples** at cycle times. To fit on disk each zip was **downloaded → sampled → deleted**; its URL and SHA-256 are kept in `data/book_samples/manifest_books.json`. |

**Daily universe** (`universe_daily.json`, built by `build_universe.py`):
- Built from CoinGecko market caps, taking the last point at or before 00:00 UTC each day so there's no look-ahead, with the engine's exclusion categories applied.
- BTC/ETH/BNB/XRP/SOL/TRX are members every day: they were far above the cutoff on both endpoint dates.
- Changes at the #20 boundary:
  - Sep 19: NEAR replaces LTC.
  - Oct 7: LTC replaces UNI.
  - Oct 13: Canton Network (CCUSDT) replaces LTC.
  - Oct 14: Bitway (BTWUSDT) replaces CC.
  - Oct 15: LTC returns.
- UNI, CC and BTW are absent from the live main DB. Their contract metadata comes from Bybit public `instruments-info` and `risk-limit`: MMR 0.67%, 2% and 5%. At 10×, BTW's 5% MMR puts liquidation 5% away, so ATR stops often fall beyond it and plans are correctly rejected.
- Caveats:
  - The candidate list came from coins currently in the top ~60, so a coin that was top-20 in September but has since fallen out of the top ~60 would be missed. None is known.
  - The 7-day replay used the static Oct-11 snapshot (LTC on Oct 13–14 instead of CC/BTW).

## 6. Comparison with the 7-day replay and the two-year evidence

| Strategy | 7-day A return | 30-day A return | Direction held? |
|---|---|---|---|
| Crash Reversal | +24.98% | +61.14% | yes (still small-sample) |
| Range Reversion | +22.67% | +0.98% | **no**: the week was the good part |
| Order-Flow | +1.50% | −40.80% | **no** |
| Trend Rider | −16.18% | +1.05% | mixed |
| Regime Trend | −8.99% | −23.65% | yes, negative |
| Volatility Breakout | −23.11% | −40.36% | yes, negative |
| Trend Pullback | −25.67% | −39.96% | yes, negative |
| Breakout | −44.65% | −49.85% | yes, negative |

The 7-day "top 3" didn't hold over 30 days for 2 of 3. This is the expected behaviour of tiny samples, and the reason no ranking here should drive capital decisions.

Against the two-year evidence: `state/validation_report.json` (Trend Rider's logic, 474 trades, mean −1.75%, outcome NEGATIVE) is consistent with Trend Rider's flat-with-huge-drawdown month. The README's record that most research-cohort strategies lose over the long sample is consistent with Regime, Pullback, Volatility Breakout and Order-Flow here.

## 7. Recommendation (no profitability claim)

1. **Fix F4 (cash-vs-equity lock), F2 (missing HTF trend) and F3 (missing order-book hook) first, as separate tested changes.** Most rejections in this month are F4 artefacts, so current forward-paper data partly measures that bug.
2. **Crash Reversal** is the only candidate with any positive signal across both windows. Keep forward-paper testing it in its own sleeve. It needs far more than 19 trades and several crash and non-crash regimes before any conclusion.
3. **Deprioritise** Breakout, Volatility Breakout, Trend Pullback, Regime Trend and Order-Flow. They had 26–57 trades each, consistently negative across both windows, and are consistent with the longer evidence.
4. **Review the shared-portfolio design separately:** the 3-slot first-come allocation and the irreversible trailing lock decided B's outcome more than any strategy did. Any change should be decided before looking at more data.
5. **The hybrid 50%-at-2R exit** remains a separate experiment to implement and pre-register.

## 8. Files

- `REPORT.md`, `run_all.sh`
- `build_universe.py`, `universe_daily.json`, `extra_instruments.json`
- `runs/*.json`: per-run trades, signals, equity and risk events (the `*.sqlite` files are git-ignored)
- `data/manifest_rest.json`, `data/book_samples/manifest_books.json`: dataset IDs and SHA-256
- `raw/meta/`: CoinGecko snapshots
- `leakcheck/`: the 10-day truncation run
- `live_baseline_*.txt`
- 1m data and book samples are local and git-ignored. No raw archive zips are kept; all of them can be re-downloaded and verified from the manifests.
