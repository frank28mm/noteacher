"""
Review cards queue abstraction (Redis-backed).

Purpose:
- Implement Layer 3 "Review Cards" without blocking /grade completion.
- Grade worker enqueues review tasks for visually risky items.
- Review worker consumes tasks and updates `job:{job_id}.question_cards[]`.
"""

from __future__ import annotations

import json
import os
import time
import logging
from dataclasses import dataclass
from typing import Optional

from homework_agent.utils.settings import get_settings
from homework_agent.utils.observability import log_event

logger = logging.getLogger(__name__)

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover
    redis = None


@dataclass(frozen=True)
class ReviewCardJob:
    job_id: str
    session_id: str
    request_id: Optional[str]
    subject: str
    page_index: int
    question_number: str
    item_id: str
    page_image_url: Optional[str]
    question_content: Optional[str]
    review_reasons: list[str]
    attempt: int
    enqueued_at: float

    def to_json(self) -> str:
        return json.dumps(
            {
                "job_id": self.job_id,
                "session_id": self.session_id,
                "request_id": self.request_id,
                "subject": self.subject,
                "page_index": int(self.page_index),
                "question_number": self.question_number,
                "item_id": self.item_id,
                "page_image_url": self.page_image_url,
                "question_content": self.question_content,
                "review_reasons": list(self.review_reasons or []),
                "attempt": int(self.attempt),
                "enqueued_at": float(self.enqueued_at),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def from_json(data: str) -> "ReviewCardJob":
        obj = json.loads(data)
        return ReviewCardJob(
            job_id=str(obj.get("job_id") or ""),
            session_id=str(obj.get("session_id") or ""),
            request_id=str(obj.get("request_id") or "").strip() or None,
            subject=str(obj.get("subject") or "math"),
            page_index=int(obj.get("page_index") or 0),
            question_number=str(obj.get("question_number") or ""),
            item_id=str(obj.get("item_id") or ""),
            page_image_url=(
                str(obj.get("page_image_url")).strip()
                if obj.get("page_image_url") is not None
                and str(obj.get("page_image_url")).strip()
                else None
            ),
            question_content=(
                str(obj.get("question_content")).strip()
                if obj.get("question_content") is not None
                and str(obj.get("question_content")).strip()
                else None
            ),
            review_reasons=[
                str(x) for x in (obj.get("review_reasons") or []) if str(x).strip()
            ],
            attempt=int(obj.get("attempt") or 0),
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
        logger.warning("Redis unavailable for review cards queue: %s", e)
        return None


def queue_key() -> str:
    settings = get_settings()
    prefix = os.getenv("CACHE_PREFIX", "")
    name = getattr(settings, "review_cards_queue_name", "review_cards:queue")
    return f"{prefix}{name}"


def _lock_key(*, job_id: str, item_id: str) -> str:
    prefix = os.getenv("CACHE_PREFIX", "")
    return f"{prefix}review_cards:lock:{job_id}:{item_id}"


def enqueue_review_card_job(
    *,
    job_id: str,
    session_id: str,
    request_id: Optional[str],
    subject: str,
    page_index: int,
    question_number: str,
    item_id: str,
    review_reasons: list[str],
    page_image_url: Optional[str] = None,
    question_content: Optional[str] = None,
    attempt: int = 0,
) -> bool:
    client = get_redis_client()
    if client is None:
        log_event(
            logger,
            "review_cards_enqueue_skipped",
            level="warning",
            request_id=request_id,
            session_id=session_id,
            job_id=job_id,
            reason="redis_unavailable",
        )
        return False

    # De-dupe: avoid enqueueing the same item repeatedly.
    try:
        lk = _lock_key(job_id=job_id, item_id=item_id)
        if client.set(lk, "1", nx=True, ex=10 * 60) is None:
            return True
    except Exception:
        pass

    job = ReviewCardJob(
        job_id=str(job_id),
        session_id=str(session_id),
        request_id=str(request_id).strip() or None,
        subject=str(subject or "math"),
        page_index=int(page_index),
        question_number=str(question_number),
        item_id=str(item_id),
        page_image_url=(
            str(page_image_url).strip()
            if page_image_url and str(page_image_url).strip()
            else None
        ),
        question_content=(
            str(question_content).strip()
            if question_content and str(question_content).strip()
            else None
        ),
        review_reasons=[str(x) for x in (review_reasons or []) if str(x).strip()],
        attempt=int(attempt),
        enqueued_at=time.time(),
    )
    client.lpush(queue_key(), job.to_json())
    log_event(
        logger,
        "review_cards_enqueued",
        request_id=request_id,
        session_id=session_id,
        job_id=job_id,
        item_id=item_id,
        page_index=int(page_index),
        question_number=str(question_number),
        reasons=job.review_reasons[:6],
    )
    return True
