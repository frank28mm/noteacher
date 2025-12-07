"""
Cache abstraction with optional Redis support.
- If REDIS_URL is set and redis package is available, use Redis.
- Otherwise fallback to in-memory cache (process-local, not for production).
"""

import json
import os
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple
import logging

try:
    import redis  # type: ignore
except ImportError:
    redis = None  # Redis optional


class BaseCache:
    def get(self, key: str) -> Optional[Any]:
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


class InMemoryCache(BaseCache):
    def __init__(self):
        self.store: dict[str, Tuple[Any, Optional[datetime]]] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self.store.get(key)
        if not item:
            return None
        value, expires_at = item
        if expires_at and datetime.now() > expires_at:
            self.delete(key)
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        expires_at = datetime.now() + timedelta(seconds=ttl_seconds) if ttl_seconds else None
        self.store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


class RedisCache(BaseCache):
    def __init__(self, url: str, prefix: str = ""):
        if not redis:
            raise RuntimeError("redis package not installed")
        self.client = redis.Redis.from_url(url)
        self.prefix = prefix

    def _k(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def get(self, key: str) -> Optional[Any]:
        data = self.client.get(self._k(key))
        if data is None:
            return None
        try:
            return json.loads(data)
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        data = json.dumps(value)
        self.client.set(self._k(key), data, ex=ttl_seconds)

    def delete(self, key: str) -> None:
        self.client.delete(self._k(key))


def get_cache_store() -> BaseCache:
    redis_url = os.getenv("REDIS_URL")
    prefix = os.getenv("CACHE_PREFIX", "")
    if redis_url and redis:
        try:
            cache = RedisCache(redis_url, prefix=prefix)
            cache.client.ping()  # Verify connection immediately
            return cache
        except Exception as e:
            logging.warning("Redis configured but unavailable (ping failed), falling back to in-memory cache: %s", e)
            return InMemoryCache()
    if redis_url and not redis:
        logging.warning("REDIS_URL set but redis package not installed; using in-memory cache")
    return InMemoryCache()
