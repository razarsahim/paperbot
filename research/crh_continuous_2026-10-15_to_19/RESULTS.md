# Crash Reversal Hunter: continuous replay, 2026-10-15 00:00 → 2026-10-19 00:00 UTC

> **HISTORICAL BACKTEST, not live paper.** This is one $50 Crash Reversal sleeve on its own, with deployed rules and 1-hour signals. It was a **single continuous engine run** over 5,760 one-minute cycles. Cash, open positions, trailing stops and funding carried across every midnight; nothing was reset between days.
>
> Universe: the daily top-20 (16 eligible Bybit perpetuals, the same coins on all 4 days). Entry quotes come from archived Bybit L2 order books. Two trades is an anecdote, not evidence.

## Result

| | |
|---|---|
| Start → end equity | $50.00 → **$67.33 (+34.7%)**, all realised |
| Completed trades | 2 (both wins, both stopped out by the trailing stop) |
| Max drawdown | $13.48 (16.7%): the peak of $80.81 on Oct 15 gave back to the exit level |
| Costs | fees $0.24, slippage $0.20 (estimated), funding $0.07 (7 funding payments) |
| Liquidations / locks | none |

| Day (UTC) | Equity at 00:00 | Intraday min / max | What happened |
|---|---|---|---|
| Oct 15 | $50.00 | $47.53 / $80.81 | Opened ZEC long at 07:00 and NEAR long at 12:00. Stops trailed up every hour. |
| Oct 16 | **$75.27** (both positions carried over midnight) | $67.33 / $79.51 | Both stops were hit together at 15:23. |
| Oct 17 | $67.33 | flat | No signal: no coin was down 8% or more with a reversal candle. |
| Oct 18 | $67.33 | flat | ZEC fell −8.55% / −8.40% (candles closing 20:00 and 21:00) but neither candle was a reversal candle, so there was no entry. |
| Oct 19 00:00 | **$67.33** | | Flat, no open positions. |

## Trades

| Coin | Entry (UTC) | Exit (UTC) | Entry → exit | Initial stop → final stop | Peak gain while open | Net P&L |
|---|---|---|---|---|---|---|
| ZEC long, qty 0.09 | Oct 15 07:00 | Oct 16 15:23 | 1093.57 → 1181.20 | 1041.84 → 1181.79 | +14.6% | **+$7.72** |
| NEAR long, qty 20.8 | Oct 15 12:00 | Oct 16 15:23 | 4.5943 → 5.0635 | 4.3624 → 5.0661 | +18.0% | **+$9.61** |

## Checks

- **No look-ahead:** the newest data served matches the clock at every step.
- **Accounting:** the identity gap is $0.00.
- **Stops:** stops only ever moved up, never widened. No liquidation estimate was reached.
- **Data:** complete. Across 16 coins there are 0 missing or duplicate 1-hour and 1-minute bars, and 0 stale order-book samples. That covers 64 day-files: Oct 15–17 from the 30-day dataset and Oct 18 from the 48-hour dataset.
- **Live system untouched:** the live engines and databases were not touched. The main database was read only for instrument metadata.

Reproduce with `research/crh_continuous_2026-10-15_to_19/run.sh`. The run result is `runs/CRH_continuous_96h.json`.
