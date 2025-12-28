"""
Cache abstraction with optional Redis support.
- If REDIS_URL is set and redis package is available, use Redis.
- Otherwise fallback to in-memory cache (process-local, not for production).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple
import logging

try:
    import redis  # type: ignore
except ImportError:
    redis = None  # Redis optional

_CACHED_STORE: BaseCache | None = None
_CACHED_STORE_CONFIG: tuple[str | None, str, bool, bool] | None = None


def _json_default(obj: Any):
    """Make cache payload JSON-serializable (best-effort)."""
    try:
        # Pydantic models
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
    except Exception:
        pass
    # Datetime/date
    if isinstance(obj, datetime):
        return obj.isoformat()
    # Common URL-ish / path-ish objects
    try:
        return str(obj)
    except Exception:
        return repr(obj)


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
        expires_at = (
            datetime.now() + timedelta(seconds=ttl_seconds) if ttl_seconds else None
        )
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
        data = json.dumps(value, ensure_ascii=False, default=_json_default)
        self.client.set(self._k(key), data, ex=ttl_seconds)

    def delete(self, key: str) -> None:
        self.client.delete(self._k(key))


def get_cache_store() -> BaseCache:
    global _CACHED_STORE, _CACHED_STORE_CONFIG
    redis_url = os.getenv("REDIS_URL")
    prefix = os.getenv("CACHE_PREFIX", "")
    require_redis = os.getenv("REQUIRE_REDIS", "").strip() in {
        "1",
        "true",
        "TRUE",
        "yes",
        "YES",
    }
    config = (redis_url, prefix, require_redis, bool(redis))
    if _CACHED_STORE is not None and _CACHED_STORE_CONFIG == config:
        return _CACHED_STORE
    if redis_url and redis:
        try:
            cache = RedisCache(redis_url, prefix=prefix)
            cache.client.ping()  # Verify connection immediately
            _CACHED_STORE = cache
            _CACHED_STORE_CONFIG = config
            return cache
        except Exception as e:
            if require_redis:
                raise RuntimeError(f"REQUIRE_REDIS=1 but Redis ping failed: {e}")
            logging.warning(
                "Redis configured but unavailable (ping failed), falling back to in-memory cache: %s",
                e,
            )
            _CACHED_STORE = InMemoryCache()
            _CACHED_STORE_CONFIG = config
            return _CACHED_STORE
    if redis_url and not redis:
        if require_redis:
            raise RuntimeError("REQUIRE_REDIS=1 but redis package not installed")
        logging.warning(
            "REDIS_URL set but redis package not installed; using in-memory cache"
        )
    if require_redis and not redis_url:
        raise RuntimeError("REQUIRE_REDIS=1 but REDIS_URL is not set")
    _CACHED_STORE = InMemoryCache()
    _CACHED_STORE_CONFIG = config
    return _CACHED_STORE
