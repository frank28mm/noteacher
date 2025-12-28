"""
Grade job queue abstraction (Redis-backed).

Why:
- Replace FastAPI BackgroundTasks for long-running /grade jobs.
- Make job status queryable from any API instance via shared cache (Redis).
"""

from __future__ import annotations

import json
import os
import time
import logging
from dataclasses import dataclass
from typing import Any, Optional

from homework_agent.utils.cache import get_cache_store
from homework_agent.utils.observability import log_event
from homework_agent.utils.settings import get_settings

logger = logging.getLogger(__name__)

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover
    redis = None


@dataclass(frozen=True)
class GradeJob:
    job_id: str
    request_id: Optional[str]
    session_id: str
    user_id: str
    provider: str
    enqueued_at: float

    def to_json(self) -> str:
        return json.dumps(
            {
                "job_id": self.job_id,
                "request_id": self.request_id,
                "session_id": self.session_id,
                "user_id": self.user_id,
                "provider": self.provider,
                "enqueued_at": self.enqueued_at,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def from_json(data: str) -> "GradeJob":
        obj = json.loads(data)
        return GradeJob(
            job_id=str(obj.get("job_id") or ""),
            request_id=str(obj.get("request_id") or "").strip() or None,
            session_id=str(obj.get("session_id") or ""),
            user_id=str(obj.get("user_id") or ""),
            provider=str(obj.get("provider") or ""),
            enqueued_at=float(obj.get("enqueued_at") or time.time()),
        )


def _require_redis_enabled() -> bool:
    return os.getenv("REQUIRE_REDIS", "").strip().lower() in {"1", "true", "yes"}


def get_redis_client() -> Optional["redis.Redis"]:
    if redis is None:
        if _require_redis_enabled():
            raise RuntimeError("REQUIRE_REDIS=1 but redis package not installed")
        return None
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        if _require_redis_enabled():
            raise RuntimeError("REQUIRE_REDIS=1 but REDIS_URL is not set")
        return None
    try:
        client = redis.Redis.from_url(redis_url)
        client.ping()
        return client
    except Exception as e:  # pragma: no cover
        if _require_redis_enabled():
            raise RuntimeError(f"REQUIRE_REDIS=1 but Redis ping failed: {e}")
        logger.warning("Redis unavailable for grade queue: %s", e)
        return None


def queue_key() -> str:
    settings = get_settings()
    prefix = os.getenv("CACHE_PREFIX", "")
    return f"{prefix}{getattr(settings, 'grade_queue_name', 'grade:queue')}"


def save_job_request(job_id: str, payload: dict[str, Any], *, ttl_seconds: int) -> None:
    if not job_id:
        return
    cache = get_cache_store()
    cache.set(f"jobreq:{job_id}", payload, ttl_seconds=ttl_seconds)


def load_job_request(job_id: str) -> Optional[dict[str, Any]]:
    if not job_id:
        return None
    cache = get_cache_store()
    data = cache.get(f"jobreq:{job_id}")
    return data if isinstance(data, dict) else None


def set_job_status(
    job_id: str,
    payload: dict[str, Any],
    *,
    ttl_seconds: int,
) -> None:
    if not job_id:
        return
    cache = get_cache_store()
    cache.set(f"job:{job_id}", payload, ttl_seconds=ttl_seconds)


def enqueue_grade_job(
    *,
    job_id: str,
    grade_request: dict[str, Any],
    provider: str,
    request_id: Optional[str],
    session_id: str,
    user_id: str,
    ttl_seconds: int,
) -> bool:
    """
    Enqueue a grade job. Returns True if queued, False if Redis is unavailable.

    Notes:
    - Uses shared cache keys for API/worker consistency:
      - job:{job_id}  (status/result/error)
      - jobreq:{job_id} (request payload)
    """
    client = get_redis_client()
    if client is None:
        log_event(
            logger,
            "grade_enqueue_skipped",
            level="warning",
            request_id=request_id,
            session_id=session_id,
            reason="redis_unavailable",
            job_id=job_id,
        )
        return False

    save_job_request(
        job_id,
        {"grade_request": grade_request, "provider": str(provider or "").strip()},
        ttl_seconds=ttl_seconds,
    )
    set_job_status(
        job_id,
        {
            "status": "processing",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "request": grade_request,
            "result": None,
        },
        ttl_seconds=ttl_seconds,
    )

    job = GradeJob(
        job_id=job_id,
        request_id=str(request_id).strip() or None,
        session_id=str(session_id),
        user_id=str(user_id),
        provider=str(provider),
        enqueued_at=time.time(),
    )
    client.lpush(queue_key(), job.to_json())
    log_event(
        logger,
        "grade_enqueued",
        request_id=request_id,
        session_id=session_id,
        job_id=job_id,
        provider=str(provider),
    )
    return True

