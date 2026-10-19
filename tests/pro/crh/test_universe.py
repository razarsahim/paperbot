"""Point-in-time universe mapping: exclusions, 1000X contracts, listing
dates, missing metadata -> NOT ELIGIBLE with a reason; no network."""
import json
from pathlib import Path

from paperbot_pro.crh.data import Cache
from paperbot_pro.crh.universe import UniverseBuilder, day_ms, days_between


def _inst(sym, launch="2021-01-01", status="Trading", ctype="LinearPerpetual"):
    return {"symbol": sym, "contractType": ctype, "status": status, "launchTime": str(day_ms(launch)),
            "priceFilter": {"tickSize": "0.01"}, "lotSizeFilter": {"qtyStep": "0.1"}}


def test_map_instruments_rules(tmp_path):
    c = Cache(tmp_path, offline=True)
    (c.root / "bybit" / "instruments").mkdir(parents=True)
    (c.root / "bybit" / "instruments" / "latest.json").write_text(json.dumps({"rows": [
        _inst("BTCUSDT"), _inst("1000PEPEUSDT"), _inst("NEWUSDT", launch="2026-10-18"),
        _inst("DEADUSDT", status="Closed"), _inst("NOMMUSDT")]}))
    rl = c.root / "bybit" / "risk_limit"; rl.mkdir()
    for s in ("BTCUSDT", "1000PEPEUSDT", "NEWUSDT"):
        (rl / f"{s}.json").write_text(json.dumps({"maintenanceMargin": "0.005"}))
    (rl / "NOMMUSDT.json").write_text(json.dumps({}))
    daily = {"2026-10-17": [{"id": "bitcoin", "symbol": "BTC", "cap": 1, "rank": 1},
                            {"id": "pepe", "symbol": "PEPE", "cap": 1, "rank": 2},
                            {"id": "new", "symbol": "NEW", "cap": 1, "rank": 3},
                            {"id": "dead", "symbol": "DEAD", "cap": 1, "rank": 4},
                            {"id": "nomm", "symbol": "NOMM", "cap": 1, "rank": 5},
                            {"id": "leo-token", "symbol": "LEO", "cap": 1, "rank": 6}],
             "2026-10-19": [{"id": "new", "symbol": "NEW", "cap": 1, "rank": 1}]}
    uni, inst, inel = UniverseBuilder(c).map_instruments(daily)
    assert uni["2026-10-17"] == ["BTC/USDT:USDT", "1000PEPE/USDT:USDT"]
    assert uni["2026-10-19"] == ["NEW/USDT:USDT"]                  # listed before the 19th
    assert inst["1000PEPE/USDT:USDT"]["contract_multiplier"] == 1000
    assert inst["1000PEPE/USDT:USDT"]["bybit_symbol"] == "1000PEPEUSDT"
    assert "listed after" in inel["new"] or "new" not in inel      # ineligible on 17th only
    assert "not an active" in inel["dead"] and "maintenance margin" in inel["nomm"]
    assert "no Bybit linear perp" in inel["leo-token"]


def test_days_between_is_utc_midnight_aligned():
    t0 = day_ms("2026-10-17") + 5 * 3_600_000
    assert days_between(t0, day_ms("2026-10-19")) == ["2026-10-17", "2026-10-18"]
