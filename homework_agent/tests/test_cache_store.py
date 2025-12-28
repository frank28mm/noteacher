from __future__ import annotations


from homework_agent.utils.cache import get_cache_store, InMemoryCache


def test_get_cache_store_inmemory_is_singleton_for_same_env(monkeypatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("CACHE_PREFIX", raising=False)
    monkeypatch.delenv("REQUIRE_REDIS", raising=False)

    a = get_cache_store()
    b = get_cache_store()
    assert a is b
    assert isinstance(a, InMemoryCache)
