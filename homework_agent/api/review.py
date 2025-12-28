from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from homework_agent.services.review_queue import (
    list_review_items,
    resolve_review_item,
    get_review_item,
)
from homework_agent.utils.settings import get_settings
from homework_agent.utils.observability import log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/review", tags=["review"])


def _require_review_admin(*, token: Optional[str]) -> None:
    settings = get_settings()
    if not getattr(settings, "review_api_enabled", False):
        raise HTTPException(status_code=404, detail="review api disabled")
    expected = str(getattr(settings, "review_admin_token", "") or "").strip()
    if not expected:
        raise HTTPException(status_code=403, detail="review admin token not configured")
    if str(token or "").strip() != expected:
        raise HTTPException(status_code=403, detail="forbidden")


class ReviewListResponse(BaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)


class ResolveRequest(BaseModel):
    resolved_by: str = Field(..., min_length=1, max_length=128)
    note: Optional[str] = Field(default=None, max_length=500)


@router.get("/items", response_model=ReviewListResponse)
async def review_list(
    request: Request,  # noqa: ARG001
    status_filter: str = "open",
    limit: int = 50,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    _require_review_admin(token=x_admin_token)
    items = list_review_items(status=status_filter, limit=limit)
    return ReviewListResponse(items=items)


@router.get("/items/{item_id}")
async def review_get(
    item_id: str,
    request: Request,  # noqa: ARG001
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    _require_review_admin(token=x_admin_token)
    obj = get_review_item(item_id)
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return obj


@router.post("/items/{item_id}/resolve")
async def review_resolve(
    item_id: str,
    payload: ResolveRequest,
    request: Request,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    _require_review_admin(token=x_admin_token)
    ok = resolve_review_item(
        item_id=item_id, resolved_by=payload.resolved_by, note=payload.note
    )
    if not ok:
        raise HTTPException(status_code=404, detail="not found")
    req_id = getattr(getattr(request, "state", None), "request_id", None)
    log_event(
        logger,
        "review_resolve",
        request_id=req_id,
        item_id=item_id,
        resolved_by=payload.resolved_by,
    )
    return {"ok": True, "item_id": item_id}
