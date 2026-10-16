from paperbot_pro.hype import score_token, map_geckoterminal_pool


def candidate(**kw):
    base = dict(symbol='NEWCOIN', name='New Coin', chain='solana',
                contract='So1aNaAddr111', pool_age_hours=72.0,
                liquidity_usd=250_000.0, volume_24h_usd=400_000.0,
                price_change_24h_pct=18.0)
    base.update(kw)
    return base


def test_reasonable_token_is_watch_only_never_eligible():
    result = score_token(candidate())
    assert result['status'] == 'WATCH_ONLY'
    assert 0 < result['score'] <= 100
    assert any('honeypot' in f.lower() for f in result['flags'])  # risk always disclosed
    assert result['evidence'] and all('source' in e for e in result['evidence'])
    assert 'explanation' in result and result['explanation']


def test_wash_trading_pattern_rejected():
    result = score_token(candidate(liquidity_usd=20_000.0, volume_24h_usd=2_000_000.0))
    assert result['status'] == 'REJECTED'
    assert any('wash' in f.lower() for f in result['flags'])


def test_tiny_liquidity_and_young_pool_rejected():
    assert score_token(candidate(liquidity_usd=5_000.0))['status'] == 'REJECTED'
    assert score_token(candidate(pool_age_hours=0.5))['status'] == 'REJECTED'


def test_missing_contract_rejected_as_unverifiable():
    result = score_token(candidate(contract=None))
    assert result['status'] == 'REJECTED'
    assert any('unverifiable' in f.lower() for f in result['flags'])


def test_geckoterminal_pool_mapping():
    pool = {"attributes": {
        "name": "WIF / SOL", "address": "poolAddr",
        "pool_created_at": "2026-10-14T12:00:00Z",
        "reserve_in_usd": "150000.5",
        "volume_usd": {"h24": "300000.1"},
        "price_change_percentage": {"h24": "42.5"}},
        "relationships": {"base_token": {"data": {"id": "solana_tokenAddr123"}}}}
    token = map_geckoterminal_pool(pool, now_iso="2026-10-16T12:00:00Z")
    assert token['symbol'] == 'WIF'
    assert token['chain'] == 'solana'
    assert token['contract'] == 'tokenAddr123'
    assert token['liquidity_usd'] == 150000.5
    assert abs(token['pool_age_hours'] - 48.0) < 0.1
