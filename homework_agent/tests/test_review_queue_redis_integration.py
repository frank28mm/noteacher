from __future__ import annotations

import os
import uuid

import pytest

from homework_agent.services.review_queue import (
    enqueue_review_item,
    list_review_items,
    resolve_review_item,
)
from homework_agent.utils.cache import InMemoryCache

pytestmark = pytest.mark.integration


def _redis_client():
    try:
        import redis  # type: ignore
    except Exception:  # pragma: no cover
        return None
    url = str(os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        client = redis.Redis.from_url(url)
        client.ping()
        return client
    except Exception:
        return None


def test_review_queue_uses_redis_list_when_available(monkeypatch) -> None:
    client = _redis_client()
    if client is None:
        pytest.skip("Redis unavailable (set REDIS_URL to run this integration test)")

    prefix = f"test:{uuid.uuid4().hex[:8]}:"
    monkeypatch.setenv("CACHE_PREFIX", prefix)
    queue_key = f"{prefix}review:queue"

    # Use in-memory cache for item bodies; Redis is only used for ordering.
    cache = InMemoryCache()
    try:
        client.delete(queue_key)
        item_id = enqueue_review_item(
            request_id="req_x",
            session_id="sess_x",
            subject="math",
            warning_codes=["needs_review", "diagram_roi_not_found"],
            evidence_urls=["https://example.com/a.png?access_token=abc"],
            run_versions={"prompt_id": "autonomous", "prompt_version": "v1"},
            cache_store=cache,
        )
        assert item_id

        # Ensure Redis list ordering exists
        ids = [
            x.decode("utf-8", errors="ignore")
            for x in (client.lrange(queue_key, 0, 10) or [])
            if x
        ]
        assert item_id in ids

        # list_review_items should read IDs from Redis and hydrate from cache.
        items = list_review_items(status="open", limit=10, cache_store=cache)
        assert any(it.get("item_id") == item_id for it in items)

        ok = resolve_review_item(
            item_id=item_id, resolved_by="tester", note="ok", cache_store=cache
        )
        assert ok is True

        open_items = list_review_items(status="open", limit=10, cache_store=cache)
        assert all(it.get("item_id") != item_id for it in open_items)
        resolved_items = list_review_items(
            status="resolved", limit=10, cache_store=cache
        )
        assert any(
            it.get("item_id") == item_id and it.get("status") == "resolved"
            for it in resolved_items
        )
    finally:
        try:
            client.delete(queue_key)
        except Exception:
            pass
