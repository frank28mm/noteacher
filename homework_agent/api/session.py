from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status

from homework_agent.core.qbank import _normalize_question_number
from homework_agent.core.qindex import build_question_index_for_pages
from homework_agent.utils.cache import BaseCache, get_cache_store
from homework_agent.utils.observability import log_event

logger = logging.getLogger(__name__)

router = APIRouter()

# 缓存：可配置 Redis，默认进程内存
cache_store: BaseCache = get_cache_store()

# 常量
# 取消硬性 5 轮上限；仅保留计数用于提示递进
MAX_SOCRATIC_TURNS = 999999
SESSION_TTL_HOURS = 24 * 7
IDP_TTL_HOURS = 24
SESSION_TTL_SECONDS = SESSION_TTL_HOURS * 3600


def _ensure_session_id(value: Optional[str]) -> str:
    """Ensure we always have a stable session_id for grade→chat delivery."""
    v = (value or "").strip()
    if v:
        return v
    return f"session_{uuid.uuid4().hex[:8]}"


def _count_questions_with_options(bank: Dict[str, Any]) -> int:
    qs = bank.get("questions")
    if not isinstance(qs, dict):
        return 0
    n = 0
    for q in qs.values():
        if isinstance(q, dict) and q.get("options"):
            n += 1
    return n


def persist_question_bank(
    *,
    session_id: str,
    bank: Dict[str, Any],
    grade_status: str,
    grade_summary: str,
    grade_warnings: List[str],
    request_id: Optional[str] = None,
    timings_ms: Optional[Dict[str, int]] = None,
) -> None:
    """Persist the canonical qbank snapshot that /chat must rely on."""
    if not session_id:
        return
    now = datetime.now().isoformat()
    meta = bank.get("meta") if isinstance(bank.get("meta"), dict) else {}
    meta.update(
        {
            "updated_at": now,
            "grade_status": grade_status,
            "grade_summary": grade_summary,
            "warnings": grade_warnings or [],
        }
    )
    if timings_ms:
        meta["timings_ms"] = {
            str(k): int(v) for k, v in timings_ms.items() if v is not None
        }
    # Derived stats for acceptance checks
    try:
        meta["vision_raw_len"] = int(len(bank.get("vision_raw_text") or ""))
        meta["questions_count"] = (
            int(len(bank.get("questions") or {}))
            if isinstance(bank.get("questions"), dict)
            else 0
        )
        meta["questions_with_options"] = int(_count_questions_with_options(bank))
    except Exception as e:
        logger.debug(f"Meta stats calculation failed: {e}")
    bank["meta"] = meta
    save_question_bank(session_id, bank)
    try:
        log_event(
            logger,
            "qbank_saved",
            request_id=request_id,
            session_id=session_id,
            status=grade_status,
            questions=meta.get("questions_count"),
            questions_with_options=meta.get("questions_with_options"),
            vision_raw_len=meta.get("vision_raw_len"),
            timings_ms=meta.get("timings_ms"),
        )
    except Exception as e:
        logger.debug(f"qbank_saved log_event failed: {e}")


def _merge_bank_meta(bank: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(bank, dict):
        return bank
    meta = bank.get("meta") if isinstance(bank.get("meta"), dict) else {}
    meta.update({k: v for k, v in (extra or {}).items() if v is not None})
    bank["meta"] = meta
    return bank


def _now_ts() -> float:
    return time.time()


def _coerce_ts(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, datetime):
        return float(v.timestamp())
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return float(s)
        except Exception as e:
            logger.debug(f"Parsing float timestamp failed: {e}")
        try:
            return float(datetime.fromisoformat(s).timestamp())
        except Exception:
            return None
    return None


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    data = cache_store.get(f"sess:{session_id}")
    if not isinstance(data, dict):
        return None
    # Normalize timestamps for runtime logic.
    for k in ("created_at", "updated_at"):
        ts = _coerce_ts(data.get(k))
        if ts is not None:
            data[k] = ts
    return data


def save_session(session_id: str, data: Dict[str, Any]) -> None:
    copy = dict(data or {})
    copy["created_at"] = _coerce_ts(copy.get("created_at")) or _now_ts()
    copy["updated_at"] = _coerce_ts(copy.get("updated_at")) or _now_ts()
    try:
        from homework_agent.security.safety import sanitize_session_data_for_persistence

        sanitize_session_data_for_persistence(copy)
    except Exception as e:
        logger.debug(f"Sanitizing session for persistence failed (best-effort): {e}")
    cache_store.set(f"sess:{session_id}", copy, ttl_seconds=SESSION_TTL_SECONDS)


def delete_session(session_id: str) -> None:
    cache_store.delete(f"sess:{session_id}")


def save_mistakes(session_id: str, wrong_items: List[Dict[str, Any]]) -> None:
    """缓存错题列表供辅导上下文使用，仅限当前批次，会话 TTL 同步。"""
    # 为每个 wrong_item 补充本地索引与稳定 item_id，便于后续检索
    enriched = []
    for idx, item in enumerate(wrong_items):
        enriched_item = dict(item)
        # ensure question_number preserved as string
        qn = _normalize_question_number(
            enriched_item.get("question_number") or enriched_item.get("question_index")
        )
        if qn is not None:
            enriched_item["question_number"] = qn
        item_id = enriched_item.get("item_id") or enriched_item.get("id")
        if not item_id:
            item_id = f"item-{idx}"
        enriched_item["item_id"] = str(item_id)
        enriched_item.setdefault("id", idx)
        enriched.append(enriched_item)
    cache_store.set(
        f"mistakes:{session_id}",
        {"wrong_items": enriched, "ts": datetime.now().isoformat()},
        ttl_seconds=SESSION_TTL_SECONDS,
    )


def get_mistakes(session_id: str) -> Optional[List[Dict[str, Any]]]:
    data = cache_store.get(f"mistakes:{session_id}")
    if not data:
        return None
    return data.get("wrong_items")


def save_question_index(session_id: str, index: Dict[str, Any]) -> None:
    cache_store.set(
        f"qindex:{session_id}",
        {"index": index, "ts": datetime.now().isoformat()},
        ttl_seconds=SESSION_TTL_SECONDS,
    )


def get_question_index(session_id: str) -> Optional[Dict[str, Any]]:
    data = cache_store.get(f"qindex:{session_id}")
    if not data:
        return None
    idx = data.get("index")
    return idx if isinstance(idx, dict) else None


def save_qindex_placeholder(session_id: str, warning: str) -> bool:
    """
    Persist a client-visible qindex status placeholder, without overwriting real results.
    Returns True if placeholder was written.
    """
    if not session_id or not warning:
        return False
    current = get_question_index(session_id)
    if isinstance(current, dict):
        # Do not overwrite real results or an existing queued marker.
        if current.get("questions"):
            return False
        ws = current.get("warnings") or []
        if isinstance(ws, list) and any("queued" in str(w) for w in ws):
            return False
    save_question_index(session_id, {"questions": {}, "warnings": [str(warning)]})
    return True


def save_question_bank(session_id: str, bank: Dict[str, Any]) -> None:
    cache_store.set(
        f"qbank:{session_id}",
        {"bank": bank, "ts": datetime.now().isoformat()},
        ttl_seconds=SESSION_TTL_SECONDS,
    )


def get_question_bank(session_id: str) -> Optional[Dict[str, Any]]:
    data = cache_store.get(f"qbank:{session_id}")
    if not data:
        return None
    bank = data.get("bank")
    return bank if isinstance(bank, dict) else None


def save_grade_progress(
    session_id: str, stage: str, message: str, extra: Optional[Dict[str, Any]] = None
) -> None:
    """Persist best-effort grade progress for UI polling during long /grade calls."""
    if not session_id:
        return
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "stage": str(stage),
        "message": str(message),
        "ts": datetime.now().isoformat(),
    }
    if isinstance(extra, dict) and extra:
        payload["extra"] = extra
    cache_store.set(
        f"grade_progress:{session_id}",
        {"progress": payload},
        ttl_seconds=SESSION_TTL_SECONDS,
    )


def get_grade_progress(session_id: str) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None
    data = cache_store.get(f"grade_progress:{session_id}")
    if not isinstance(data, dict):
        return None
    p = data.get("progress")
    return p if isinstance(p, dict) else None


def _build_question_index_for_pages(
    page_urls: List[str], *, session_id: str | None = None
) -> Dict[str, Any]:
    """Backward-compatible wrapper for worker/session imports."""
    # Keep this symbol stable, but route implementation to shared module to avoid path drift.
    return build_question_index_for_pages(page_urls, session_id=session_id)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = cache_store.get(f"job:{job_id}")
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    return job


@router.get("/session/{session_id}/qbank")
async def get_session_qbank_meta(session_id: str):
    """
    验收/调试接口：查看本次批改是否已将“识别/判定/题目信息”写入 qbank（供 /chat 使用）。
    默认不返回整段 vision_raw_text，避免过大。
    """
    sid = _ensure_session_id(session_id)
    bank = get_question_bank(sid)
    if not bank:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="qbank not found for session_id",
        )

    questions = bank.get("questions") if isinstance(bank, dict) else None
    qnums: List[str] = []
    if isinstance(questions, dict):
        qnums = [str(k) for k in questions.keys()]

    meta = bank.get("meta") if isinstance(bank.get("meta"), dict) else {}
    out: Dict[str, Any] = {
        "session_id": sid,
        "subject": bank.get("subject"),
        "page_image_urls_count": (
            len(bank.get("page_image_urls") or [])
            if isinstance(bank.get("page_image_urls"), list)
            else 0
        ),
        "vision_raw_len": len(bank.get("vision_raw_text") or ""),
        "questions_count": len(qnums),
        "questions_with_options": _count_questions_with_options(bank),
        "question_numbers": sorted(qnums, key=len, reverse=False)[:300],
        "meta": meta,
    }
    qindex = get_question_index(sid)
    if isinstance(qindex, dict):
        out["qindex_available"] = bool(qindex.get("questions"))
        out["qindex_warnings"] = qindex.get("warnings") or []
    else:
        out["qindex_available"] = False
        out["qindex_warnings"] = []
    return out


@router.get("/session/{session_id}/progress")
async def get_session_progress(session_id: str):
    """UI 辅助接口：返回 /grade 的当前进度（best-effort，可能为空）。"""
    sid = _ensure_session_id(session_id)
    return get_grade_progress(sid) or {
        "session_id": sid,
        "stage": "unknown",
        "message": "no progress yet",
    }
