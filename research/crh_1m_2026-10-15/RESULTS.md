# Crash Reversal Hunter: 1-minute experiments, 2026-10-15 (one UTC day)

> **HISTORICAL BACKTEST.** These are experiments, not the deployed strategy. Each run is one independent $50 sleeve, run alone through the unchanged `LabEngine`: $5 risk, 10× isolated, the same daily top-20 universe and archived Bybit L2 quotes. One day is an anecdote, not evidence.

| Run | Candles | Drop lookback | Signals (approved) | Trades | Final equity | Day P&L | Max DD | Fees + slippage |
|---|---|---|---|---|---|---|---|---|
| `CRH_1h` (deployed rules) | 1h | 24 bars = 24 h | 2 (2) | 0 closed, 2 open | **$75.30** | **+$25.30 unrealized** | 7.9% | $0.22 |
| `CRH_1m` (code unchanged) | 1m | 24 bars = **24 min** | 0 | 0 | $50.00 | $0 | 0% | $0 |
| `CRH_1m_24h` (**variant** `crh_1m_24h`) | 1m | **1,440 bars = 24 h** | 62 (42) | 42 closed | **$16.02** | **−$33.98 (−68%)** | 77.5% | $17.23 |

## What happened

- **1h (deployed):** two entries, ZEC at 07:00 and NEAR at 12:00. Both were still open at midnight, with stops already trailed above entry (ZEC stop 1172 vs entry 1094; NEAR 5.066 vs 4.594).
- **1m, code unchanged:** it can't fire. The worst 24-minute move of the day was −4.42% (ADA at 02:28), and the threshold is −8%.
- **1m with a 24h lookback (variant):** it lost 68% of the sleeve in one day.
  - ZEC and NEAR stayed more than 8% below their level of 24 hours earlier for most of the morning. During that time *any* 1-minute hammer candle re-triggered an entry: 30 ZEC and 12 NEAR longs.
  - A 2×ATR(14) stop on 1-minute bars is tiny, so most trades were stopped within 1–20 minutes. The re-entry cooldown is only one bar, which is now one minute.
  - Win rate was 21% (9 of 42).
  - Fees ($9.40) and slippage ($7.83) were about half of the loss.
  - By the time ZEC actually reversed (14:03 → 15:23, +$4.52), the sleeve had shrunk too far to size the trade meaningfully. The 1h version caught the same rebound for +$25.

## Why it behaves this way

Moving to 1-minute candles changes what the strategy's three ingredients mean:
- **Drop condition:** with a 24h lookback it stays true for hours, instead of marking a single moment.
- **Reversal candle:** a 1-minute hammer is a common, noisy pattern, not a capitulation signal.
- **Stops, trailing and cooldown:** these scale to 1-minute volatility, so the strategy turns into a high-frequency, fee-dominated scalper.

Only the lookback was changed, as requested. This result doesn't support a 1-minute version.

## Verification

- **No look-ahead:** the newest data timestamp served equals the end of the day.
- **Accounting:** the identity gap is 0.
- **Live system and deployed code untouched:** the variant overrides `CRASH_WINDOW` (deployed value 24 → 1,440) only inside the replay process. A test checks that the deployed value on disk is still 24, and the run's JSON records the override.
- **Tests:** `tests/pro/test_replay.py` passes 20/20.

## Files and reproduction

Run results: `CRH_1h.json`, `CRH_1m.json`, `CRH_1m_24h.json`.

Reproduce with:

```
python -m paperbot_pro.replay.run_week --run-id CRH_1m_24h --variant crh_1m_24h \
  --data research/replay_2026-09-18_30d/data --books research/replay_2026-09-18_30d/data/book_samples \
  --out research/crh_1m_2026-10-15 --t0 1792022400000 --t1 1792108800000 \
  --universe-file research/replay_2026-09-18_30d/universe_daily.json \
  --extra-instruments research/replay_2026-09-18_30d/extra_instruments.json
```
