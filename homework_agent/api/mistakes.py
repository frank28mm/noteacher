from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from homework_agent.services.mistakes_service import (
    MistakesServiceError,
    compute_knowledge_tag_stats,
    exclude_mistake,
    list_mistakes,
    restore_mistake,
)
from homework_agent.utils.user_context import require_user_id

logger = logging.getLogger(__name__)

router = APIRouter()


class MistakeItem(BaseModel):
    submission_id: str
    session_id: Optional[str] = None
    subject: Optional[str] = None
    created_at: Optional[str] = None
    item_id: str
    question_number: Optional[str] = None
    reason: Optional[str] = None
    severity: Optional[str] = None
    knowledge_tags: List[str] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)


class MistakesListResponse(BaseModel):
    items: List[MistakeItem] = Field(default_factory=list)
    next_before_created_at: Optional[str] = None


class ExcludeMistakeRequest(BaseModel):
    submission_id: str
    item_id: str
    reason: Optional[str] = None


@router.get("/mistakes", response_model=MistakesListResponse)
def get_mistakes_history(
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    limit_submissions: int = Query(default=20, ge=1, le=50),
    before_created_at: Optional[str] = Query(default=None),
    include_excluded: bool = Query(default=False),
):
    """
    历史错题查询（跨 submission 聚合）。
    说明：当前以 `submissions.grade_result.wrong_items` 作为 durable snapshot。
    """
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    try:
        mistakes, next_before = list_mistakes(
            user_id=user_id,
            limit_submissions=limit_submissions,
            before_created_at=before_created_at,
            include_excluded=include_excluded,
        )
    except MistakesServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e

    items = [
        MistakeItem(
            submission_id=m.submission_id,
            session_id=m.session_id,
            subject=m.subject,
            created_at=m.created_at,
            item_id=m.item_id,
            question_number=m.question_number,
            reason=m.reason,
            severity=m.severity,
            knowledge_tags=m.knowledge_tags,
            raw=m.raw,
        )
        for m in mistakes
    ]
    return MistakesListResponse(items=items, next_before_created_at=next_before)


@router.get("/mistakes/stats")
def get_mistakes_stats(
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    limit_submissions: int = Query(default=50, ge=1, le=50),
    before_created_at: Optional[str] = Query(default=None),
):
    """按 knowledge_tags 聚合的基础统计（MVP）。"""
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    try:
        mistakes, next_before = list_mistakes(
            user_id=user_id,
            limit_submissions=limit_submissions,
            before_created_at=before_created_at,
            include_excluded=False,
        )
    except MistakesServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e

    return {
        "next_before_created_at": next_before,
        "knowledge_tag_counts": compute_knowledge_tag_stats(mistakes),
    }


@router.post("/mistakes/exclusions")
def post_mistake_exclusion(
    req: ExcludeMistakeRequest,
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    """错题排除（只影响统计/报告，不改历史事实）。"""
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    try:
        exclude_mistake(
            user_id=user_id,
            submission_id=req.submission_id,
            item_id=req.item_id,
            reason=req.reason,
        )
    except MistakesServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    return {"ok": True}


@router.delete("/mistakes/exclusions/{submission_id}/{item_id}")
def delete_mistake_exclusion(
    submission_id: str,
    item_id: str,
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    """错题恢复（撤销排除）。"""
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    try:
        restore_mistake(user_id=user_id, submission_id=submission_id, item_id=item_id)
    except MistakesServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    return {"ok": True}
