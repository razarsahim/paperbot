# Crash Reversal Hunter on the TOP-50 universe, 2026-10-17 00:00 → 2026-10-19 00:00 UTC

> **HISTORICAL BACKTEST and EXPERIMENT (widened universe).** The deployed engine scans the top 20; this run scans the top 50. It is one $50 Crash Reversal sleeve run alone, with deployed rules and 1-hour signals, in **one continuous run**: no reset at midnight. A single trade is an anecdote, not evidence.

## Universe

- **Ranking:** daily top 50 by CoinGecko market cap, using the last value at or before 00:00 UTC, with the engine's exclusions (stablecoins, wrapped and liquid-staking tokens).
- **Eligibility:** each coin is mapped to `{SYMBOL}USDT` Bybit linear perpetuals the way the engine resolves instruments. Contract metadata comes from Bybit's public endpoints.
- **Eligible:** **39 coins on Oct 17 and 40 on Oct 18** (41 distinct). MORPHO and SKY entered on Oct 18; ICP dropped out.
- **Not eligible (11): no `{SYMBOL}USDT` perp on Bybit.**
  - Not crypto: tokenized funds and yield products (BUIDL, USYC, USDY, the Spiko EUR fund) and Figure HELOC.
  - Exchange tokens: LEO, WhiteBIT.
  - Others: Rain, PUMP.
  - PEPE and SHIB, which Bybit lists only as `1000PEPE`/`1000SHIB`; the engine's exact-symbol rule doesn't map these.
- **Edge cases the engine's rules allow:** gold-backed tokens XAUT and PAXG are not in the excluded categories, so they are included.

## Signals

The strategy's own evaluator was run on every closed 1-hour candle of all 41 coins (`prescan.py`). **Exactly one signal fired in two days: ENA, on the candle closing Oct 18 21:00 UTC.** ENA was down 8.6% over 24 hours, and the 20:00–21:00 candle was a hammer.

Archived Bybit L2 order books were downloaded only for ENA. The other 40 coins never produced a signal, so the engine skipped them for lack of a quote: 110,880 "data unavailable" skips in the audit log. Without a signal they could never have traded, so this changes no result.

## Result

| | |
|---|---|
| Start → end equity | $50.00 → **$59.28 (+18.6%)**: **all unrealised** (position still open at the window end) |
| Trade | ENA long, entered Oct 18 21:00 at **0.17632** (archived ask plus slippage), qty 785, notional $138.41, margin $13.84, planned risk $4.99 |
| Price path | 0.1761 (signal close) → 0.1862 (22:00 close) → **0.18824** (last 1-minute close before 00:00) |
| Stop | initial 0.17025 → trailed to **0.17753 (above entry)**. If stopped now, the trade would still make about +$0.95 before exit costs |
| Unrealised P&L | +$9.36 gross, **+$9.28 net** of entry fee |
| Max drawdown | $1.33 (2.3%), the low of $49.36 at 21:10 just after entry |
| Costs | entry fee $0.08, estimated slippage $0.07, funding $0 (no 8-hour boundary crossed) |

**Compared with the deployed top-20 run over the same two days:** that run made 0 trades and stayed at $50.00. The top-20's only near-miss was ZEC at −8.55%, which had no reversal candle. ENA ranks outside the top 20, so the wider universe is the only reason this trade exists.

## Checks

- **No look-ahead:** the newest data served equals the clock throughout.
- **Accounting:** the identity gap is $0.00.
- **Stops:** the stop never widened. No liquidation estimate was reached (estimate 0.16027).
- **Data:** 41 coins with no missing 1-hour or 1-minute bars. ENA's books have 0 crossed books and 0 gaps over 15 s.
- **Live system untouched:** no live engine or database was touched.

Reproduce with `run.sh` after `fetch_top50.py`, `build_universe.py`, `prescan.py` and the ENA book download. The run result is `runs/CRH_top50_48h.json`.
