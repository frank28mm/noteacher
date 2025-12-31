"""
Derived facts extraction queue (Redis-backed).

Purpose:
- After /grade persists `submissions.grade_result`, enqueue a job to extract:
  - question_attempts
  - question_steps
This decouples report-ready facts from request latency.
"""

from __future__ import annotations

import json
import os
import time
import logging
from dataclasses import dataclass
from typing import Optional

from homework_agent.utils.observability import log_event
from homework_agent.utils.settings import get_settings

logger = logging.getLogger(__name__)

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover
    redis = None


@dataclass(frozen=True)
class FactsJob:
    submission_id: str
    user_id: str
    session_id: Optional[str]
    request_id: Optional[str]
    enqueued_at: float

    def to_json(self) -> str:
        return json.dumps(
            {
                "submission_id": self.submission_id,
                "user_id": self.user_id,
                "session_id": self.session_id,
                "request_id": self.request_id,
                "enqueued_at": self.enqueued_at,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def from_json(data: str) -> "FactsJob":
        obj = json.loads(data)
        return FactsJob(
            submission_id=str(obj.get("submission_id") or ""),
            user_id=str(obj.get("user_id") or ""),
            session_id=str(obj.get("session_id") or "").strip() or None,
            request_id=str(obj.get("request_id") or "").strip() or None,
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
        logger.warning("Redis unavailable for facts queue: %s", e)
        return None


def queue_key() -> str:
    settings = get_settings()
    prefix = os.getenv("CACHE_PREFIX", "")
    return f"{prefix}{getattr(settings, 'facts_queue_name', 'facts:queue')}"


def enqueue_facts_job(
    *,
    submission_id: str,
    user_id: str,
    session_id: Optional[str],
    request_id: Optional[str],
) -> bool:
    client = get_redis_client()
    if client is None:
        log_event(
            logger,
            "facts_enqueue_skipped",
            level="warning",
            request_id=request_id,
            session_id=session_id,
            submission_id=submission_id,
            reason="redis_unavailable",
        )
        return False

    job = FactsJob(
        submission_id=str(submission_id),
        user_id=str(user_id),
        session_id=str(session_id).strip() or None,
        request_id=str(request_id).strip() or None,
        enqueued_at=time.time(),
    )
    client.lpush(queue_key(), job.to_json())
    log_event(
        logger,
        "facts_enqueued",
        request_id=request_id,
        session_id=session_id,
        submission_id=submission_id,
    )
    return True

