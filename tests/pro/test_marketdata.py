from paperbot_pro.marketdata import TTLCache


def test_ttl_cache_serves_within_ttl_and_refetches_after():
    clock = {'t': 1000.0}
    cache = TTLCache(clock=lambda: clock['t'])
    calls = {'n': 0}

    def fetch():
        calls['n'] += 1
        return [['candle', calls['n']]]

    first, age1 = cache.get('k', ttl_seconds=60, fetch=fetch)
    again, age2 = cache.get('k', ttl_seconds=60, fetch=fetch)
    assert calls['n'] == 1 and first == again and age2 >= 0
    clock['t'] += 61
    third, _ = cache.get('k', ttl_seconds=60, fetch=fetch)
    assert calls['n'] == 2 and third == [['candle', 2]]


def test_ttl_cache_serves_stale_on_fetch_failure_with_flag():
    clock = {'t': 1000.0}
    cache = TTLCache(clock=lambda: clock['t'])
    cache.get('k', ttl_seconds=10, fetch=lambda: ['good'])
    clock['t'] += 999

    def broken():
        raise ConnectionError('exchange down')
    value, age = cache.get('k', ttl_seconds=10, fetch=broken)
    assert value == ['good'] and age == 999  # stale data clearly aged, never hidden
