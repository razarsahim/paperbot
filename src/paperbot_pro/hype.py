"""Hype Radar: evidence-based scoring of new/trending tokens. WATCH ONLY.

Hard rules: no token scored here is ever ELIGIBLE for simulated leverage —
new launches have no verified perp market, so the status is WATCH_ONLY at
best and REJECTED on structural red flags. Hype is never treated as proof of
future growth; every score ships with its evidence and an explanation.
Data source: GeckoTerminal public pools API (no key, read-only).
"""
from __future__ import annotations
import json
import math
import time
from datetime import datetime, timezone
from .config import ProSettings

GECKOTERMINAL = "https://api.geckoterminal.com/api/v2"

HARD_MIN_LIQUIDITY_USD = 10_000.0
HARD_MIN_POOL_AGE_H = 1.0
WASH_VOL_LIQ_RATIO = 50.0
SOFT_LOW_LIQUIDITY_USD = 50_000.0
SOFT_YOUNG_POOL_H = 24.0
SOFT_VOL_LIQ_RATIO = 20.0


def score_token(token: dict) -> dict:
    """Deterministic score + flags + status for one candidate token dict with
    keys: symbol, name, chain, contract, pool_age_hours, liquidity_usd,
    volume_24h_usd, price_change_24h_pct."""
    flags: list[str] = []
    hard_reject: list[str] = []
    liq = token.get("liquidity_usd") or 0.0
    vol = token.get("volume_24h_usd") or 0.0
    age = token.get("pool_age_hours")
    change = token.get("price_change_24h_pct") or 0.0
    ratio = (vol / liq) if liq > 0 else float("inf")

    if not token.get("contract"):
        hard_reject.append("unverifiable contract: no address resolvable")
    if liq < HARD_MIN_LIQUIDITY_USD:
        hard_reject.append(f"insufficient liquidity (${liq:,.0f} < ${HARD_MIN_LIQUIDITY_USD:,.0f})")
    if age is not None and age < HARD_MIN_POOL_AGE_H:
        hard_reject.append(f"pool too young ({age:.1f}h)")
    if ratio > WASH_VOL_LIQ_RATIO:
        hard_reject.append(f"volume/liquidity ratio {ratio:.0f}x suggests wash trading")

    if liq < SOFT_LOW_LIQUIDITY_USD:
        flags.append("low liquidity depth")
    if age is not None and age < SOFT_YOUNG_POOL_H:
        flags.append("pool younger than 24h")
    if abs(change) > 50:
        flags.append(f"extreme volatility ({change:+.0f}%/24h)")
    if SOFT_VOL_LIQ_RATIO < ratio <= WASH_VOL_LIQ_RATIO:
        flags.append(f"elevated volume/liquidity ratio ({ratio:.0f}x)")
    flags.append("smart contract not audited here — honeypot risk cannot be excluded")
    flags = hard_reject + flags

    # Score: liquidity depth 30, real volume 20, pool maturity 15,
    # structure sanity 15, volatility moderation 10, evidence 10.
    score = 0.0
    score += min(30.0, 6.0 * math.log10(max(liq, 1) / 1_000)) if liq > 1_000 else 0.0
    score += min(20.0, 4.0 * math.log10(max(vol, 1) / 1_000)) if vol > 1_000 else 0.0
    if age is not None:
        score += min(15.0, age / 168.0 * 15.0)  # a week of history maxes maturity
    score += 15.0 if ratio <= SOFT_VOL_LIQ_RATIO else (7.0 if ratio <= WASH_VOL_LIQ_RATIO else 0.0)
    score += 10.0 if abs(change) <= 50 else 3.0
    evidence = [
        {"source": "geckoterminal", "note": f"liquidity ${liq:,.0f} observed"},
        {"source": "geckoterminal", "note": f"24h volume ${vol:,.0f} observed"},
        {"source": "geckoterminal", "note": f"pool age {age:.1f}h" if age is not None
                                            else "pool age unknown"},
    ]
    score += min(10.0, 3.0 * len(evidence))
    status = "REJECTED" if hard_reject else "WATCH_ONLY"
    if status == "REJECTED":
        explanation = "Rejected: " + "; ".join(hard_reject)
        score = min(score, 25.0)
    else:
        explanation = (f"Observed on-chain activity (liquidity ${liq:,.0f}, volume ${vol:,.0f}, "
                       f"age {age:.0f}h). WATCH ONLY: no verified perp market exists and hype "
                       "is not evidence of future growth.")
    return {"status": status, "score": round(min(score, 100.0), 1), "flags": flags,
            "evidence": evidence, "explanation": explanation}


def map_geckoterminal_pool(pool: dict, now_iso: str | None = None) -> dict:
    attrs = pool.get("attributes", {})
    name = attrs.get("name", "?")
    symbol = name.split("/")[0].strip() if "/" in name else name.strip()
    base = (pool.get("relationships", {}).get("base_token", {}).get("data", {}) or {}).get("id", "")
    chain, _, contract = base.partition("_")
    created = attrs.get("pool_created_at")
    age_h = None
    if created:
        now = (datetime.fromisoformat(now_iso.replace("Z", "+00:00")) if now_iso
               else datetime.now(timezone.utc))
        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        age_h = (now - created_dt).total_seconds() / 3600.0
    def flt(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    return {"symbol": symbol, "name": name, "chain": chain or "?",
            "contract": contract or None, "pool_age_hours": age_h,
            "liquidity_usd": flt(attrs.get("reserve_in_usd")),
            "volume_24h_usd": flt((attrs.get("volume_usd") or {}).get("h24")),
            "price_change_24h_pct": flt((attrs.get("price_change_percentage") or {}).get("h24"))}


def refresh_hype(store, cfg: ProSettings, http_get) -> list[dict]:
    """One bounded call to trending pools; score and persist. WATCH ONLY."""
    now_ms = int(time.time() * 1000)
    try:
        payload = http_get(f"{GECKOTERMINAL}/networks/trending_pools?page=1")
        pools = payload.get("data", [])[:20]
    except Exception as exc:
        store.audit("error", "hype", f"hype refresh failed: {type(exc).__name__}: {exc}")
        return []
    tokens = []
    with store.conn:
        store.conn.execute("DELETE FROM hype_tokens")
        for pool in pools:
            token = map_geckoterminal_pool(pool)
            result = score_token(token)
            store.conn.execute(
                """INSERT INTO hype_tokens(ts_ms, symbol, name, chain, contract,
                   pool_age_hours, liquidity_usd, volume_24h_usd, score, flags,
                   evidence, status, explanation) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (now_ms, token["symbol"], token["name"], token["chain"], token["contract"],
                 token["pool_age_hours"], token["liquidity_usd"], token["volume_24h_usd"],
                 result["score"], json.dumps(result["flags"]), json.dumps(result["evidence"]),
                 result["status"], result["explanation"]))
            tokens.append({**token, **result})
    store.audit("info", "hype", f"hype radar refreshed: {len(tokens)} tokens, all watch-only/rejected",
                ts_ms=now_ms)
    return tokens
