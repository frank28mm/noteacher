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

logger = logging.getLogger(__name__)

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover
    redis = None


@dataclass(frozen=True)
class QIndexJob:
    session_id: str
    page_urls: list[str]
    enqueued_at: float

    def to_json(self) -> str:
        return json.dumps(
            {
                "session_id": self.session_id,
                "page_urls": self.page_urls,
                "enqueued_at": self.enqueued_at,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def from_json(data: str) -> "QIndexJob":
        obj = json.loads(data)
        return QIndexJob(
            session_id=str(obj.get("session_id")),
            page_urls=[str(u) for u in (obj.get("page_urls") or []) if u],
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


def enqueue_qindex_job(session_id: str, page_urls: list[str]) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    job = QIndexJob(session_id=session_id, page_urls=page_urls, enqueued_at=time.time())
    client.lpush(queue_key(), job.to_json())
    return True


def store_qindex_result(session_id: str, index: dict[str, Any], *, ttl_seconds: int) -> None:
    """Store qindex in the same shape as routes.save_question_index()."""
    client = get_redis_client()
    if client is None:
        return
    prefix = os.getenv("CACHE_PREFIX", "")
    key = f"{prefix}qindex:{session_id}"
    payload = {"index": index, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    client.set(key, json.dumps(payload, ensure_ascii=False), ex=ttl_seconds)

