import pytest
from material_search_cache import MaterialSearchCache


def test_version_change_and_expiration_rebuild_cached_evidence():
    time = [0]
    calls = []
    cache = MaterialSearchCache(ttl=30, clock=lambda: time[0])
    def build():
        calls.append(1)
        return {'build': len(calls)}
    assert cache.get('db', 'p', (1, 1), build)['build'] == 1
    assert cache.get('db', 'p', (1, 1), build)['build'] == 1
    assert cache.get('db', 'p', (2, 2), build)['build'] == 2
    time[0] = 30
    assert cache.get('db', 'p', (2, 2), build)['build'] == 3


def test_cache_is_bounded_and_scoped_by_database_and_project():
    cache = MaterialSearchCache(capacity=2)
    assert cache.get('a', 'p', 1, lambda: {'scope': 'a'})['scope'] == 'a'
    assert cache.get('b', 'p', 1, lambda: {'scope': 'b'})['scope'] == 'b'
    cache.get('b', 'other', 1, lambda: {})
    assert len(cache.entries) == 2
    assert ('a', 'p') not in cache.entries


def test_failed_build_can_retry():
    cache = MaterialSearchCache()
    def fail():
        raise RuntimeError('offline')
    with pytest.raises(RuntimeError):
        cache.get('db', 'p', 1, fail)
    assert cache.get('db', 'p', 1, lambda: {'ok': True})['ok']
