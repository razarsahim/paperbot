"""Build the daily top-20 universe (engine rules) for 2026-09-18..10-17 from
CoinGecko 00:00 UTC market-cap snapshots, and map it to Bybit perps with real
metadata. Coins far above the cutoff on both endpoint snapshots are treated as
members every day; boundary coins use their own daily snapshot."""
import json
from pathlib import Path

D = Path(__file__).parent
SIZE = 20
start = json.loads((D / "raw/meta/coingecko_rank_2026-09-18.json").read_text())["candidates"]
end = json.loads(Path("research/replay_2026-10-11/raw/meta/coingecko_rank_2026-10-11.json")
                 .read_text())["candidates"]
daily = json.loads((D / "raw/meta/coingecko_daily_boundary.json").read_text())["daily"]
boundary = set(next(iter(daily.values())))
# stable core: everything not in the boundary set that ranked in the top 20 on both dates
def top(c):
    return [k for _, k in sorted(((v["mcap_2026_10_11"] or 0), k) for k, v in c.items())[::-1][:SIZE]]
core = [k for k in top(start) if k in top(end) and k not in boundary]
perp = {  # CoinGecko id -> Bybit linear perp (ccxt id); None = no perp (NOT ELIGIBLE)
    "bitcoin": "BTC", "ethereum": "ETH", "binancecoin": "BNB", "ripple": "XRP", "solana": "SOL",
    "tron": "TRX", "zcash": "ZEC", "hyperliquid": "HYPE", "dogecoin": "DOGE", "monero": "XMR",
    "chainlink": "LINK", "cardano": "ADA", "near": "NEAR", "stellar": "XLM",
    "bitcoin-cash": "BCH", "litecoin": "LTC", "uniswap": "UNI",
    "canton-network": "CC", "bitway": "BTW",
}
universe, members = {}, {}
for day, caps in sorted(daily.items()):
    caps = {k: v for k, v in caps.items() if v}
    # core coins sit far above the cutoff; rank them first, then boundary by cap
    ranked = core + [k for k, _ in sorted(caps.items(), key=lambda kv: -kv[1])]
    ranked = list(dict.fromkeys(ranked))[:SIZE]
    members[day] = ranked
    universe[day] = [f"{perp[k]}/USDT:USDT" for k in ranked if perp.get(k)]
(D / "universe_daily.json").write_text(json.dumps(universe, indent=1))
(D / "raw/meta/universe_daily_members.json").write_text(json.dumps(members, indent=1))
changes = [(d, sorted(set(members[d]) ^ set(members[p])))
           for p, d in zip(sorted(members), sorted(members)[1:]) if set(members[d]) != set(members[p])]
print("core", core)
print("changes", changes)
print({d: len(u) for d, u in list(universe.items())[:3]})
