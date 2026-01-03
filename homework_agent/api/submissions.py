from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from homework_agent.utils.supabase_client import get_storage_client
from homework_agent.utils.user_context import require_user_id

logger = logging.getLogger(__name__)

router = APIRouter()


def _safe_table(name: str):
    storage = get_storage_client()
    return storage.client.table(name)


def _parse_iso_utc_ts(value: str) -> Optional[str]:
    """
    Parse an ISO timestamp string and normalize to UTC ISO format for supabase filters.
    Returns None if invalid.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


class SubmissionSummary(BaseModel):
    total_items: int = Field(default=0, ge=0)
    wrong_count: int = Field(default=0, ge=0)
    uncertain_count: int = Field(default=0, ge=0)
    blank_count: int = Field(default=0, ge=0)
    score_text: Optional[str] = None


class SubmissionItem(BaseModel):
    submission_id: str
    created_at: str
    subject: Optional[str] = None
    total_pages: int = Field(default=0, ge=0)
    done_pages: int = Field(default=0, ge=0)
    session_id: Optional[str] = None
    summary: Optional[SubmissionSummary] = None


class ListSubmissionsResponse(BaseModel):
    items: List[SubmissionItem] = Field(default_factory=list)
    next_before: Optional[str] = None


class SubmissionDetailResponse(BaseModel):
    submission_id: str
    created_at: str
    subject: Optional[str] = None
    total_pages: int = Field(default=0, ge=0)
    done_pages: int = Field(default=0, ge=0)
    session_id: Optional[str] = None
    page_image_urls: List[str] = Field(default_factory=list)
    vision_raw_text: Optional[str] = None
    question_cards: List[Dict[str, Any]] = Field(default_factory=list)
    page_summaries: List[Dict[str, Any]] = Field(default_factory=list)


def _compute_summary_from_grade_result(grade_result: Any) -> Optional[SubmissionSummary]:
    if not isinstance(grade_result, dict) or not grade_result:
        return None
    questions = grade_result.get("questions")
    if not isinstance(questions, list):
        questions = []
    total_items = len(questions)
    wrong = 0
    uncertain = 0
    blank = 0
    for q in questions:
        if not isinstance(q, dict):
            continue
        verdict = str(q.get("verdict") or "").strip().lower()
        answer_state = str(q.get("answer_state") or "").strip().lower()
        if answer_state == "blank":
            blank += 1
            continue
        if verdict == "incorrect":
            wrong += 1
        elif verdict == "uncertain":
            uncertain += 1
    try:
        return SubmissionSummary(
            total_items=int(grade_result.get("total_items") or total_items or 0),
            wrong_count=int(grade_result.get("wrong_count") or wrong or 0),
            uncertain_count=int(grade_result.get("uncertain_count") or uncertain or 0),
            blank_count=int(grade_result.get("blank_count") or blank or 0),
            score_text=str(grade_result.get("score_text") or "").strip() or None,
        )
    except Exception:
        return SubmissionSummary(
            total_items=total_items,
            wrong_count=wrong,
            uncertain_count=uncertain,
            blank_count=blank,
            score_text=None,
        )


@router.get("/submissions", response_model=ListSubmissionsResponse)
def list_submissions(
    subject: Optional[str] = Query(default=None, min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    before: Optional[str] = Query(
        default=None, description="ISO timestamp; return items with created_at < before"
    ),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> ListSubmissionsResponse:
    """
    List durable submissions for Recent Activity / History.

    Source of truth: `submissions` table (do NOT infer from /mistakes).
    """
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    subj = (subject or "").strip().lower() or None
    before_iso = _parse_iso_utc_ts(before or "") if before else None
    if before and not before_iso:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid before timestamp (expect ISO 8601)",
        )

    try:
        q = (
            _safe_table("submissions")
            .select(
                "submission_id,created_at,subject,session_id,page_image_urls,grade_result"
            )
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
            .limit(int(limit))
        )
        if subj:
            q = q.eq("subject", subj)
        if before_iso:
            q = q.lt("created_at", before_iso)
        res = q.execute()
        rows = res.data or []
    except Exception as e:
        logger.exception("list_submissions failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to list submissions: {e.__class__.__name__}",
        )

    items: List[SubmissionItem] = []
    next_before: Optional[str] = None
    for r in rows:
        if not isinstance(r, dict):
            continue
        sid = str(r.get("submission_id") or "").strip()
        created_at = str(r.get("created_at") or "").strip()
        if not sid or not created_at:
            continue
        page_urls = r.get("page_image_urls")
        total_pages = len(page_urls) if isinstance(page_urls, list) else 0
        summary = _compute_summary_from_grade_result(r.get("grade_result"))
        # If grade_result exists, treat as done; otherwise keep done_pages=0.
        done_pages = total_pages if summary is not None else 0
        items.append(
            SubmissionItem(
                submission_id=sid,
                created_at=created_at,
                subject=(str(r.get("subject") or "").strip() or None),
                total_pages=total_pages,
                done_pages=done_pages,
                session_id=(str(r.get("session_id") or "").strip() or None),
                summary=summary,
            )
        )

    if items:
        next_before = items[-1].created_at

    return ListSubmissionsResponse(items=items, next_before=next_before)


@router.get("/submissions/{submission_id}", response_model=SubmissionDetailResponse)
def get_submission_detail(
    submission_id: str,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> SubmissionDetailResponse:
    """
    Fetch a single submission snapshot for History Detail (Option B).
    Returns derived question_cards/page_summaries so the frontend can render without rebuilding a job.
    """
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    sid = (submission_id or "").strip()
    if not sid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="missing submission_id"
        )

    try:
        resp = (
            _safe_table("submissions")
            .select(
                "submission_id,created_at,subject,session_id,page_image_urls,vision_raw_text,grade_result,warnings"
            )
            .eq("user_id", str(user_id))
            .eq("submission_id", sid)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None)
        row = (
            rows[0]
            if isinstance(rows, list) and rows and isinstance(rows[0], dict)
            else None
        )
    except Exception as e:
        logger.exception("get_submission_detail failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to load submission: {e.__class__.__name__}",
        )

    if not isinstance(row, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="submission not found"
        )

    page_image_urls = row.get("page_image_urls")
    page_image_urls = (
        [str(u).strip() for u in page_image_urls if str(u).strip()]
        if isinstance(page_image_urls, list)
        else []
    )
    total_pages = len(page_image_urls)

    grade_result = row.get("grade_result") if isinstance(row.get("grade_result"), dict) else {}
    questions = grade_result.get("questions") if isinstance(grade_result.get("questions"), list) else []

    # Build derived question_cards from stored questions list (expects page_index; fallback to 0).
    from homework_agent.core.question_cards import (
        build_question_cards_from_questions_list,
        merge_question_cards,
        sort_question_cards,
    )

    cards_by_id: Dict[str, Dict[str, Any]] = {}
    page_summaries: List[Dict[str, Any]] = []
    max_page_index = -1
    pages_seen: Dict[int, List[Dict[str, Any]]] = {}
    for q in questions:
        if not isinstance(q, dict):
            continue
        pi = q.get("page_index")
        try:
            pi_i = int(pi) if pi is not None else 0
        except Exception:
            pi_i = 0
        max_page_index = max(max_page_index, pi_i)
        pages_seen.setdefault(pi_i, []).append(q)

    for page_index, qs in sorted(pages_seen.items(), key=lambda x: x[0]):
        verdict_cards, blank_count = build_question_cards_from_questions_list(
            page_index=int(page_index),
            questions=qs,
            card_state="verdict_ready",
        )
        cards_by_id = merge_question_cards(cards_by_id, verdict_cards)
        wrong_count = 0
        uncertain_count = 0
        for c in verdict_cards:
            if not isinstance(c, dict):
                continue
            if c.get("answer_state") == "blank":
                continue
            v = str(c.get("verdict") or "").strip().lower()
            if v == "incorrect":
                wrong_count += 1
            elif v == "uncertain":
                uncertain_count += 1
        page_summaries.append(
            {
                "page_index": int(page_index),
                "wrong_count": int(wrong_count),
                "uncertain_count": int(uncertain_count),
                "blank_count": int(blank_count),
                "needs_review": bool(uncertain_count > 0),
            }
        )

    # If total_pages is unknown but questions have page_index, infer it.
    if total_pages <= 0 and max_page_index >= 0:
        total_pages = int(max_page_index) + 1

    detail = SubmissionDetailResponse(
        submission_id=str(row.get("submission_id") or sid),
        created_at=str(row.get("created_at") or ""),
        subject=(str(row.get("subject") or "").strip() or None),
        total_pages=int(total_pages),
        done_pages=int(total_pages) if questions else 0,
        session_id=(str(row.get("session_id") or "").strip() or None),
        page_image_urls=page_image_urls,
        vision_raw_text=(str(row.get("vision_raw_text") or "").strip() or None),
        question_cards=sort_question_cards(cards_by_id),
        page_summaries=page_summaries,
    )
    return detail
