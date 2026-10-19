"""EXPERIMENT universe: daily top-50 (engine exclusion rules) mapped to Bybit
USDT linear perps exactly the way the engine resolves instruments: the coin's
own ticker as {SYMBOL}USDT, an active LinearPerpetual, listed before the day,
with public tier-1 maintenance margin, tick and lot size. Anything else is
NOT ELIGIBLE (reason recorded). Deployed engine scans only the top 20."""
import calendar
import json
import time
from pathlib import Path

import requests

D = Path(__file__).parent
B = "https://api.bybit.com/v5/market"
top = json.loads((D / "raw/meta/coingecko_top50.json").read_text())["top50"]

rows, cursor = [], ""
while True:
    r = requests.get(f"{B}/instruments-info", params={"category": "linear", "limit": 1000,
                                                      "cursor": cursor}, timeout=30).json()
    rows += r["result"]["list"]
    cursor = r["result"].get("nextPageCursor") or ""
    if not cursor:
        break
(D / "raw/meta/instruments_info_linear.json").write_text(json.dumps(
    {"fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rows": rows}))
by = {r["symbol"]: r for r in rows}

universe, instruments, ineligible = {}, {}, {}
for day, coins in top.items():
    day_ms = calendar.timegm(time.strptime(day, "%Y-%m-%d")) * 1000
    universe[day] = []
    for rank, c in enumerate(coins, 1):
        sym = c["symbol"] + "USDT"
        r = by.get(sym)
        if r is None:
            ineligible[c["id"]] = f"no Bybit linear perp {sym}"
            continue
        if r["contractType"] != "LinearPerpetual" or r["status"] != "Trading":
            ineligible[c["id"]] = f"{sym} not an active linear perpetual"
            continue
        if int(r["launchTime"]) >= day_ms:
            ineligible[c["id"]] = f"{sym} listed after {day}"
            continue
        ccxt = f"{c['symbol']}/USDT:USDT"
        if ccxt not in instruments:
            rl = requests.get(f"{B}/risk-limit", params={"category": "linear", "symbol": sym},
                              timeout=30).json()["result"]["list"]
            rl = sorted([x for x in rl if x["symbol"] == sym], key=lambda x: float(x["riskLimitValue"]))
            if not rl or not rl[0].get("maintenanceMargin"):
                ineligible[c["id"]] = f"{sym} maintenance margin unavailable"
                continue
            instruments[ccxt] = {
                "coingecko_id": c["id"], "exchange": "bybit", "symbol": ccxt, "eligible": 1,
                "reason": None, "taker_fee": 0.0006,
                "maint_margin_rate": float(rl[0]["maintenanceMargin"]),
                "tick_size": float(r["priceFilter"]["tickSize"]),
                "lot_size": float(r["lotSizeFilter"]["qtyStep"]), "updated_ms": 0,
                "source": "Bybit public instruments-info + risk-limit tier 1; fee = engine default"}
            time.sleep(0.1)
        universe[day].append(ccxt)

(D / "universe_daily.json").write_text(json.dumps(universe, indent=1))
(D / "instruments.json").write_text(json.dumps(list(instruments.values()), indent=1))
(D / "raw/meta/ineligible.json").write_text(json.dumps(ineligible, indent=1, sort_keys=True))
print({d: len(u) for d, u in universe.items()}, "instruments", len(instruments),
      "ineligible", len(ineligible))
