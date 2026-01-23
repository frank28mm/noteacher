from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from homework_agent.api.admin import _require_admin
from homework_agent.utils.user_context import require_user_id
from homework_agent.utils.supabase_client import get_worker_storage_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feedback"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_table(name: str):
    storage = get_worker_storage_client()
    return storage.client.table(name)


class FeedbackMessage(BaseModel):
    id: str
    user_id: str
    sender: str  # user | admin
    content: str
    is_read: bool
    created_at: str


class FeedbackListResponse(BaseModel):
    messages: List[FeedbackMessage] = Field(default_factory=list)


class SendFeedbackRequest(BaseModel):
    content: str = Field(..., min_length=1)
    images: List[str] = Field(default_factory=list)


class CheckUnreadResponse(BaseModel):
    has_unread: bool


# === User Endpoints ===


@router.post("/feedback", response_model=FeedbackMessage)
async def user_send_feedback(
    payload: SendFeedbackRequest,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    authorization: Optional[str] = Header(default=None),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)

    # Insert message
    msg = {
        "user_id": user_id,
        "sender": "user",
        "content": payload.content,
        "images": payload.images,
        "is_read": False,
        "created_at": _utc_now(),
    }
    resp = _safe_table("feedback_messages").insert(msg).execute()
    rows = getattr(resp, "data", [])
    if not rows:
        raise HTTPException(status_code=500, detail="insert failed")

    return FeedbackMessage(**rows[0])


@router.get("/feedback", response_model=FeedbackListResponse)
async def user_list_feedback(
    limit: int = 50,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    authorization: Optional[str] = Header(default=None),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)

    # 1. Get messages
    resp = (
        _safe_table("feedback_messages")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=False)  # Chat order: oldest first
        .limit(limit)
        .execute()
    )
    rows = getattr(resp, "data", [])

    # 2. Mark admin messages as read (side effect)
    admin_msg_ids = [
        r["id"] for r in rows if r["sender"] == "admin" and not r["is_read"]
    ]
    if admin_msg_ids:
        _safe_table("feedback_messages").update({"is_read": True}).in_(
            "id", admin_msg_ids
        ).execute()

    return FeedbackListResponse(messages=[FeedbackMessage(**r) for r in rows])


@router.get("/feedback/check_unread", response_model=CheckUnreadResponse)
async def user_check_unread(
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    authorization: Optional[str] = Header(default=None),
):
    try:
        user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    except HTTPException:
        return CheckUnreadResponse(has_unread=False)

    resp = (
        _safe_table("feedback_messages")
        .select("id", count="exact", head=True)
        .eq("user_id", user_id)
        .eq("sender", "admin")
        .eq("is_read", False)
        .execute()
    )
    count = getattr(resp, "count", 0)
    return CheckUnreadResponse(has_unread=bool(count and count > 0))


# === Admin Endpoints ===


@router.get("/admin/feedback/users")
def admin_list_feedback_users(
    limit: int = 20,
    only_unread: bool = False,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    _require_admin(token=x_admin_token)

    # Supabase doesn't support distinct on specific column easily via simple client in one go with order by date
    # Strategy: fetch distinct user_ids from feedback_messages, ordered by max(created_at)
    # Actually, simplistic approach: fetch recent messages, aggregate in python.

    q = (
        _safe_table("feedback_messages")
        .select("user_id,sender,is_read,created_at,content")
        .order("created_at", desc=True)
        .limit(200)
    )
    if only_unread:
        q = q.eq("sender", "user").eq("is_read", False)

    resp = q.execute()
    rows = getattr(resp, "data", [])

    # Aggregate by user
    users_map = {}
    for r in rows:
        uid = r["user_id"]
        if uid not in users_map:
            users_map[uid] = {
                "user_id": uid,
                "last_message": r["content"],
                "last_at": r["created_at"],
                "unread_count": 0,
            }

        if r["sender"] == "user" and not r["is_read"]:
            users_map[uid]["unread_count"] += 1

    # Sort by last_at desc
    result = sorted(users_map.values(), key=lambda x: x["last_at"], reverse=True)
    return {"items": result[:limit]}


@router.get("/admin/feedback/{user_id}", response_model=FeedbackListResponse)
def admin_get_conversation(
    user_id: str,
    limit: int = 50,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    _require_admin(token=x_admin_token)

    resp = (
        _safe_table("feedback_messages")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    rows = getattr(resp, "data", [])

    # Mark user messages as read
    user_msg_ids = [r["id"] for r in rows if r["sender"] == "user" and not r["is_read"]]
    if user_msg_ids:
        _safe_table("feedback_messages").update({"is_read": True}).in_(
            "id", user_msg_ids
        ).execute()

    return FeedbackListResponse(messages=[FeedbackMessage(**r) for r in rows])


@router.post("/admin/feedback/{user_id}", response_model=FeedbackMessage)
def admin_reply_feedback(
    user_id: str,
    payload: SendFeedbackRequest,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    _require_admin(token=x_admin_token)

    msg = {
        "user_id": user_id,
        "sender": "admin",
        "content": payload.content,
        "images": payload.images,
        "is_read": False,
        "created_at": _utc_now(),
    }
    resp = _safe_table("feedback_messages").insert(msg).execute()
    rows = getattr(resp, "data", [])
    if not rows:
        raise HTTPException(status_code=500, detail="insert failed")

    return FeedbackMessage(**rows[0])
