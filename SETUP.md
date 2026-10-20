# PaperBot Pro + CRH Trading Lab — setup on a new machine

PAPER ONLY. Nothing here places orders or needs exchange keys.

## Requirements
- Python 3.12 (3.11+ should work), Node.js 20+ with npm, `sqlite3` CLI (optional), `curl`.
- Internet access for public market data (Bybit v5 REST, Bybit order-book archive, CoinGecko).

## 1. Python
```bash
cd paperbot
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e '.[dev,pro]'
python -m pytest -q                 # expect all tests to pass (one real-data test skips without local data)
```

## 2. CRH Lab API (port 8778)
```bash
.venv/bin/propaper crh-api --seed   # --seed imports research/*/data into cache/ on first start
```
The zip already ships `cache/` (≈125 MB of verified Bybit/CoinGecko history for Sep–Oct 2026),
so the regression fixtures and any backtest inside that span run offline and in seconds.

## 3. Dashboard (port 3000)
```bash
cd web
npm install
npm run dev                         # http://localhost:3000/crh  (CRH Lab)
```
Other pages: `/replay` (historical replay windows), `/lab`, `/strategies`, etc. They need the
main read-only API (`propaper api`, port 8777) and the paper engines; see README.md.

## 4. Optional: the main paper engines
```bash
propaper universe                   # top-20 universe + instrument metadata into state/paperbot_pro.sqlite
propaper api                        # read-only dashboard API on 127.0.0.1:8777
propaper lab-run                    # Extreme Lab forward-paper engine (auto-entry OFF by default)
```
`state/` is created fresh on this machine; the original machine's live paper balances are NOT included
(their DB snapshots from 2026-10-19 are in `backups/2026-10-19-crh-lab/` for reference only).

## Where things are
- `src/paperbot_pro/crh/` — CRH engine, cache, universe, runner, jobs, API
- `web/src/app/crh/page.tsx` — CRH dashboard
- `docs/CRH-LAB.md`, `docs/CRH-LAB-ARCHITECTURE.md` — guide + architecture/findings
- `research/` — all published replay results and reports (`REPORT.md` / `RESULTS.md` per folder)
- `research/crh_lab_benchmark.py` — original-vs-fast benchmark
