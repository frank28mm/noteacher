from __future__ import annotations

import os
import uuid

import pytest

from homework_agent.services.grade_queue import (
    enqueue_grade_job,
    load_job_request,
    queue_key,
)
from homework_agent.utils.cache import get_cache_store


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


def test_grade_queue_enqueues_and_persists_job_payload(monkeypatch) -> None:
    client = _redis_client()
    if client is None:
        pytest.skip("Redis unavailable (set REDIS_URL to run this integration test)")

    prefix = f"test:{uuid.uuid4().hex[:8]}:"
    monkeypatch.setenv("CACHE_PREFIX", prefix)

    qk = queue_key()
    cache = get_cache_store()

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    ttl = 60

    # Minimal GradeRequest-like payload; queue layer should not validate deeply.
    grade_request = {
        "images": [{"url": "https://example.com/a.jpg"}],
        "subject": "math",
        "batch_id": None,
        "session_id": "sess_x",
        "vision_provider": "doubao",
        "llm_provider": "ark",
        "mode": "normal",
        "upload_id": None,
    }
    try:
        client.delete(qk)
        cache.delete(f"job:{job_id}")
        cache.delete(f"jobreq:{job_id}")

        ok = enqueue_grade_job(
            job_id=job_id,
            grade_request=grade_request,
            provider="ark",
            request_id="req_x",
            session_id="sess_x",
            user_id="user_x",
            ttl_seconds=ttl,
            grade_image_input_variant="data_url_first_page",
        )
        assert ok is True

        # Queue ordering exists in Redis list.
        raw = client.lrange(qk, 0, 5) or []
        assert raw, "grade queue list should have at least one item"

        # Request payload persisted in shared cache.
        stored_req = load_job_request(job_id)
        assert isinstance(stored_req, dict)
        assert isinstance(stored_req.get("grade_request"), dict)
        assert stored_req.get("provider") == "ark"
        assert stored_req.get("grade_image_input_variant") == "data_url_first_page"

        # Job status persisted.
        job_obj = cache.get(f"job:{job_id}")
        assert isinstance(job_obj, dict)
        assert job_obj.get("status") in {"processing", "running", "done", "failed"}
    finally:
        try:
            client.delete(qk)
        except Exception:
            pass
        try:
            cache.delete(f"job:{job_id}")
            cache.delete(f"jobreq:{job_id}")
        except Exception:
            pass
