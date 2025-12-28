"""
QIndex job queue abstraction (Redis-backed).

This is used to offload Baidu OCR + crop/upload slice generation from the API process.
Worker pulls jobs from a Redis list and stores results back into cache keys:
- qindex:{session_id}
"""

from __future__ import annotations

import json
import os
import time
import logging
from dataclasses import dataclass
from typing import Any, Optional

from homework_agent.utils.settings import get_settings
from homework_agent.utils.observability import log_event, redact_url
from homework_agent.utils.cache import get_cache_store

logger = logging.getLogger(__name__)

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover
    redis = None


@dataclass(frozen=True)
class QIndexJob:
    session_id: str
    request_id: Optional[str]
    page_urls: list[str]
    # Optional allowlist: only slice/index these question numbers (best-effort).
    question_numbers: list[str]
    enqueued_at: float

    def to_json(self) -> str:
        return json.dumps(
            {
                "session_id": self.session_id,
                "request_id": self.request_id,
                "page_urls": self.page_urls,
                "question_numbers": self.question_numbers,
                "enqueued_at": self.enqueued_at,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def from_json(data: str) -> "QIndexJob":
        obj = json.loads(data)
        return QIndexJob(
            session_id=str(obj.get("session_id")),
            request_id=str(obj.get("request_id") or "").strip() or None,
            page_urls=[str(u) for u in (obj.get("page_urls") or []) if u],
            question_numbers=[
                str(q) for q in (obj.get("question_numbers") or []) if str(q).strip()
            ],
            enqueued_at=float(obj.get("enqueued_at") or time.time()),
        )


def get_redis_client() -> Optional["redis.Redis"]:
    if redis is None:
        return None
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return None
    try:
        client = redis.Redis.from_url(redis_url)
        client.ping()
        return client
    except Exception as e:  # pragma: no cover
        logger.warning("Redis unavailable for qindex queue: %s", e)
        return None


def queue_key() -> str:
    settings = get_settings()
    prefix = os.getenv("CACHE_PREFIX", "")
    return f"{prefix}{settings.qindex_queue_name}"


def enqueue_qindex_job(
    session_id: str,
    page_urls: list[str],
    *,
    question_numbers: Optional[list[str]] = None,
    request_id: Optional[str] = None,
) -> bool:
    client = get_redis_client()
    if client is None:
        log_event(
            logger,
            "qindex_enqueue_skipped",
            level="warning",
            request_id=request_id,
            session_id=session_id,
            reason="redis_unavailable",
        )
        return False
    job = QIndexJob(
        session_id=session_id,
        request_id=str(request_id).strip() or None,
        page_urls=page_urls,
        question_numbers=[str(q) for q in (question_numbers or []) if str(q).strip()],
        enqueued_at=time.time(),
    )
    client.lpush(queue_key(), job.to_json())
    log_event(
        logger,
        "qindex_enqueued",
        request_id=request_id,
        session_id=session_id,
        pages=len(page_urls or []),
        questions=len(job.question_numbers),
        page_image_urls=(
            [redact_url(u) for u in (page_urls or [])[:3]] if page_urls else None
        ),
    )
    return True


def store_qindex_result(
    session_id: str,
    index: dict[str, Any],
    *,
    ttl_seconds: int,
    request_id: Optional[str] = None,
) -> None:
    """Store qindex in the same shape as routes.save_question_index()."""
    if not session_id:
        return
    cache_store = get_cache_store()
    payload = {"index": index, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        cache_store.set(f"qindex:{session_id}", payload, ttl_seconds=ttl_seconds)
    except Exception:
        # Best-effort: storing qindex should not crash the worker loop.
        return
    try:
        questions = index.get("questions") if isinstance(index, dict) else None
        qn = len(questions or {}) if isinstance(questions, dict) else None
        log_event(
            logger,
            "qindex_stored",
            request_id=request_id,
            session_id=session_id,
            questions=qn,
            ttl_seconds=ttl_seconds,
        )
    except Exception:
        return
