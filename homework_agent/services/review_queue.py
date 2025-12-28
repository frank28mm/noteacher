from __future__ import annotations

import os
import time
import uuid
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from homework_agent.utils.cache import BaseCache, get_cache_store
from homework_agent.utils.observability import log_event
from homework_agent.security.safety import (
    redact_url_query_params,
    sanitize_text_for_log,
)
from homework_agent.utils.settings import get_settings

logger = logging.getLogger(__name__)

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover
    redis = None


@dataclass(frozen=True)
class ReviewItem:
    item_id: str
    created_at: float
    status: str  # open|resolved
    request_id: str
    session_id: str
    subject: Optional[str]
    warning_codes: List[str]
    evidence_urls: List[str]
    run_versions: Dict[str, Any]
    note: Optional[str] = None
    resolved_at: Optional[float] = None
    resolved_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "created_at": self.created_at,
            "status": self.status,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "subject": self.subject,
            "warning_codes": list(self.warning_codes or []),
            "evidence_urls": list(self.evidence_urls or []),
            "run_versions": dict(self.run_versions or {}),
            "note": self.note,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
        }


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for it in items or []:
        s = str(it or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _sanitize_urls(urls: List[str]) -> List[str]:
    out: List[str] = []
    for u in urls or []:
        s = str(u or "").strip()
        if not s:
            continue
        if s.startswith("data:image/"):
            # Avoid persisting base64 blobs; use session_id to retrieve artifacts instead.
            continue
        if s.startswith(("http://", "https://")):
            out.append(redact_url_query_params(s))
    return _dedupe(out)


def _get_redis_client() -> Optional["redis.Redis"]:
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
        logger.warning("Redis unavailable for review queue: %s", e)
        return None


def _queue_key() -> str:
    prefix = os.getenv("CACHE_PREFIX", "")
    return f"{prefix}review:queue"


def _item_key(item_id: str) -> str:
    prefix = os.getenv("CACHE_PREFIX", "")
    return f"{prefix}review:item:{item_id}"


def enqueue_review_item(
    *,
    request_id: str,
    session_id: str,
    subject: Optional[str],
    warning_codes: List[str],
    evidence_urls: Optional[List[str]] = None,
    run_versions: Optional[Dict[str, Any]] = None,
    note: Optional[str] = None,
    cache_store: Optional[BaseCache] = None,
) -> Optional[str]:
    """
    Best-effort: record a needs_review item for reviewer workflow.
    - Uses Redis list for ordering when available.
    - Stores item payload under `review:item:{id}` with TTL.
    """
    rid = str(request_id or "").strip()
    sid = str(session_id or "").strip()
    if not rid or not sid:
        return None

    settings = get_settings()
    ttl = int(getattr(settings, "review_item_ttl_seconds", 7 * 24 * 3600))
    item_id = f"rev_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    item = ReviewItem(
        item_id=item_id,
        created_at=time.time(),
        status="open",
        request_id=rid,
        session_id=sid,
        subject=str(subject).strip().lower() if subject else None,
        warning_codes=_dedupe(
            [str(c).strip() for c in (warning_codes or []) if str(c).strip()]
        ),
        evidence_urls=_sanitize_urls(list(evidence_urls or [])),
        run_versions=run_versions or {},
        note=sanitize_text_for_log(note or "") if note else None,
    )

    cache = cache_store or get_cache_store()
    try:
        cache.set(_item_key(item_id), item.to_dict(), ttl_seconds=ttl)
    except Exception:
        return None

    client = _get_redis_client()
    if client is not None:
        try:
            client.lpush(_queue_key(), item_id)
            client.ltrim(_queue_key(), 0, 9999)
        except Exception:
            pass
    else:
        # Fallback ordering list in cache (best-effort, non-atomic).
        try:
            key = "review:queue:fallback"
            cur = cache.get(key)
            ids = cur if isinstance(cur, list) else []
            ids = [str(x) for x in ids if str(x).strip()]
            ids.insert(0, item_id)
            cache.set(key, ids[:1000], ttl_seconds=ttl)
        except Exception:
            pass

    log_event(
        logger,
        "review_item_enqueued",
        request_id=rid,
        session_id=sid,
        item_id=item_id,
        warning_codes=item.warning_codes,
        subject=item.subject,
    )
    return item_id


def get_review_item(
    item_id: str, *, cache_store: Optional[BaseCache] = None
) -> Optional[Dict[str, Any]]:
    cache = cache_store or get_cache_store()
    obj = cache.get(_item_key(str(item_id or "").strip()))
    return obj if isinstance(obj, dict) else None


def list_review_items(
    *,
    status: str = "open",
    limit: int = 50,
    cache_store: Optional[BaseCache] = None,
) -> List[Dict[str, Any]]:
    cache = cache_store or get_cache_store()
    limit = max(1, min(int(limit), 200))
    want = str(status or "open").strip().lower()

    ids: List[str] = []
    client = _get_redis_client()
    if client is not None:
        try:
            raw = client.lrange(_queue_key(), 0, limit * 3)
            ids = [x.decode("utf-8", errors="ignore") for x in raw if x]
        except Exception:
            ids = []
    if not ids:
        try:
            cur = cache.get("review:queue:fallback")
            if isinstance(cur, list):
                ids = [str(x) for x in cur if str(x).strip()]
        except Exception:
            ids = []

    out: List[Dict[str, Any]] = []
    for item_id in ids:
        if len(out) >= limit:
            break
        obj = get_review_item(item_id, cache_store=cache)
        if not isinstance(obj, dict):
            continue
        if want and str(obj.get("status") or "").strip().lower() != want:
            continue
        out.append(obj)
    return out


def resolve_review_item(
    *,
    item_id: str,
    resolved_by: str,
    note: Optional[str] = None,
    cache_store: Optional[BaseCache] = None,
) -> bool:
    cache = cache_store or get_cache_store()
    obj = get_review_item(item_id, cache_store=cache)
    if not isinstance(obj, dict):
        return False
    obj["status"] = "resolved"
    obj["resolved_at"] = time.time()
    obj["resolved_by"] = sanitize_text_for_log(resolved_by or "")[:128]
    if note:
        obj["note"] = sanitize_text_for_log(note)[:500]

    settings = get_settings()
    ttl = int(getattr(settings, "review_item_ttl_seconds", 7 * 24 * 3600))
    try:
        cache.set(_item_key(str(item_id)), obj, ttl_seconds=ttl)
    except Exception:
        return False
    log_event(
        logger,
        "review_item_resolved",
        item_id=str(item_id),
        resolved_by=obj.get("resolved_by"),
    )
    return True
