from dataclasses import replace
from paperbot_pro.config import ProSettings
from paperbot_pro.store import ProStore
from paperbot_pro.universe import (apply_universe, refresh_universe,
                                   resolve_instruments, select_top)


def cg(id_, sym, rank, price=100.0):
    return {"id": id_, "symbol": sym, "name": id_.title(), "market_cap_rank": rank,
            "current_price": price, "price_change_percentage_24h": 1.0,
            "market_cap": 1e9 / rank, "total_volume": 1e8}


MARKETS = [cg("bitcoin", "btc", 1), cg("ethereum", "eth", 2), cg("tether", "usdt", 3),
           cg("binancecoin", "bnb", 4), cg("usd-coin", "usdc", 5),
           cg("wrapped-bitcoin", "wbtc", 6), cg("solana", "sol", 7),
           cg("staked-ether", "steth", 8), cg("dai", "dai", 9), cg("cardano", "ada", 10),
           cg("dogecoin", "doge", 11), cg("newstable", "xusd", 12)]
EXCLUDED = {"tether", "usd-coin", "dai", "newstable",        # stablecoins category
            "wrapped-bitcoin", "staked-ether"}               # wrapped/LST categories


def test_select_top_excludes_by_classification_not_symbol_list():
    top = select_top(MARKETS, EXCLUDED, size=5)
    ids = [c.coingecko_id for c in top]
    assert ids == ["bitcoin", "ethereum", "binancecoin", "solana", "cardano"]
    # 'xusd' is NOT in any hardcoded symbol list but is excluded by category
    assert "newstable" not in ids


def test_apply_universe_records_membership_changes(tmp_path):
    cfg = ProSettings()
    store = ProStore(str(tmp_path / 'pro.sqlite'), cfg)
    first = select_top(MARKETS, EXCLUDED, 5)
    apply_universe(store, first, now_ms=1_000)
    shuffled = [m for m in MARKETS if m["id"] != "cardano"] + [cg("avalanche", "avax", 10)]
    second = select_top(shuffled, EXCLUDED, 5)
    apply_universe(store, second, now_ms=90_000_000)
    rows = [dict(r) for r in store.conn.execute("SELECT * FROM universe ORDER BY rank")]
    assert len(rows) == 5
    changes = [dict(r) for r in store.conn.execute("SELECT * FROM universe_changes")]
    assert len(changes) == 2  # initial population + one diff
    assert 'avalanche' in changes[-1]['added'] and 'cardano' in changes[-1]['removed']


def test_refresh_failure_keeps_previous_universe(tmp_path):
    cfg = ProSettings()
    store = ProStore(str(tmp_path / 'pro.sqlite'), cfg)
    apply_universe(store, select_top(MARKETS, EXCLUDED, 5), now_ms=1_000)

    def broken_fetcher():
        raise ConnectionError('coingecko 429')
    ok = refresh_universe(store, cfg, fetcher=broken_fetcher, now_ms=2_000)
    assert ok is False
    rows = [dict(r) for r in store.conn.execute("SELECT * FROM universe")]
    assert len(rows) == 5 and all(r['updated_ms'] == 1_000 for r in rows)
    assert any('universe' in a['category'] for a in store.audit_log())


def perp_market(base, quote='USDT', mm=None, taker=0.00055):
    m = {"symbol": f"{base}/{quote}:{quote}", "base": base, "quote": quote,
         "swap": True, "linear": True, "active": True, "contract": True,
         "taker": taker, "precision": {"price": 0.1, "amount": 0.001},
         "limits": {"amount": {"min": 0.001}}, "info": {}}
    if mm is not None:
        m["info"]["maintMarginPercent"] = str(mm * 100)
    return m


def test_resolve_instruments_requires_real_contract_metadata():
    coins = select_top(MARKETS, EXCLUDED, 5)  # btc eth bnb sol ada
    markets_by_exchange = {"bybit": {
        "BTC/USDT:USDT": perp_market("BTC"),
        "ETH/USDT:USDT": perp_market("ETH", mm=0.005),
        "SOL/USDT:USDT": perp_market("SOL"),
    }}
    tiers = {"bybit": {"BTC/USDT:USDT": [{"maintenanceMarginRate": 0.005}],
                       "SOL/USDT:USDT": []}}  # SOL: perp exists, NO mm data
    out = resolve_instruments(coins, markets_by_exchange, tiers, ProSettings())
    by_id = {r['coingecko_id']: r for r in out}
    assert by_id['bitcoin']['eligible'] is True
    assert by_id['bitcoin']['maint_margin_rate'] == 0.005
    assert by_id['ethereum']['eligible'] is True        # mm from market info
    assert by_id['solana']['eligible'] is False
    assert 'maintenance margin' in by_id['solana']['reason']
    assert by_id['binancecoin']['eligible'] is False    # no perp anywhere
    assert 'no linear perp' in by_id['binancecoin']['reason']
    assert by_id['bitcoin']['tick_size'] == 0.1
    assert by_id['bitcoin']['taker_fee'] == 0.00055
