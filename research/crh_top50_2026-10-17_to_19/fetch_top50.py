"""Historical top-50 (engine exclusion rules) at 00:00 UTC on 2026-10-17 and 10-18."""
import json, time, requests, sys, bisect, datetime as dt
CG="https://api.coingecko.com/api/v3"; out=sys.argv[1]
def get(url):
    for i in range(10):
        try:
            r=requests.get(url,timeout=30)
            if r.status_code==200: return r.json()
        except requests.RequestException: pass
        time.sleep(20*(i+1))
    raise RuntimeError(url)
excluded=set()
for cat in ("stablecoins","wrapped-tokens","liquid-staking-tokens"):
    for page in (1,2):
        rows=get(f"{CG}/coins/markets?vs_currency=usd&category={cat}&order=market_cap_desc&per_page=250&page={page}")
        excluded.update(x["id"] for x in rows); time.sleep(6)
        if len(rows)<250: break
now=[]
for page in (1,2):
    now+=get(f"{CG}/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page={page}"); time.sleep(6)
cands=[m for m in now if m["id"] not in excluded][:80]
T0=int(dt.datetime(2026,10,16,tzinfo=dt.timezone.utc).timestamp()); T1=int(dt.datetime(2026,10,19,tzinfo=dt.timezone.utc).timestamp())
caps={}; syms={}
for m in cands:
    d=get(f"{CG}/coins/{m['id']}/market_chart/range?vs_currency=usd&from={T0}&to={T1}")
    caps[m["id"]]=d.get("market_caps") or []; syms[m["id"]]=m["symbol"].upper()
    print(m["id"],len(caps[m["id"]]),flush=True); time.sleep(7)
daily={}
for day in ("2026-10-17","2026-10-18"):
    ms=int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp()*1000)
    vals={}
    for cid,pts in caps.items():
        ts=[p[0] for p in pts]; i=bisect.bisect_right(ts,ms)-1
        if i>=0 and pts[i][1]: vals[cid]=pts[i][1]
    daily[day]=[{"id":c,"symbol":syms[c],"market_cap":v} for c,v in sorted(vals.items(),key=lambda kv:-kv[1])[:50]]
json.dump({"fetched_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"source":"CoinGecko /coins/markets (candidates, current top 200) + /coins/{id}/market_chart/range (last cap at/before 00:00 UTC)","excluded_categories":["stablecoins","wrapped-tokens","liquid-staking-tokens"],"candidates":len(cands),"top50":daily},open(out,"w"),indent=1)
print("DONE",{d:len(v) for d,v in daily.items()})
