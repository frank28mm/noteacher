from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from homework_agent.services.quota_service import load_wallet
from homework_agent.utils.profile_context import ensure_default_profile, require_profile_id
from homework_agent.utils.supabase_client import get_worker_storage_client
from homework_agent.utils.user_context import require_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me", tags=["me"])


class QuotaResponse(BaseModel):
    cp_left: int = Field(ge=0, description="Remaining CP (integer, derived from spendable BT).")
    report_coupons_left: int = Field(ge=0, description="Remaining report coupons.")
    trial_expires_at: Optional[str] = None
    plan_tier: Optional[str] = None
    data_retention_tier: Optional[str] = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_table(name: str):
    storage = get_worker_storage_client()
    return storage.client.table(name)


@router.get("/quota", response_model=QuotaResponse)
def get_me_quota(
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    wallet = load_wallet(user_id=user_id)
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="wallet_not_found"
        )
    return QuotaResponse(
        cp_left=int(wallet.cp_left),
        report_coupons_left=int(wallet.report_coupons),
        trial_expires_at=wallet.trial_expires_at,
        plan_tier=wallet.plan_tier,
        data_retention_tier=wallet.data_retention_tier,
    )


class ProfileItem(BaseModel):
    profile_id: str
    display_name: str
    avatar_url: Optional[str] = None
    is_default: bool = False
    created_at: Optional[str] = None


class ProfilesResponse(BaseModel):
    default_profile_id: str
    profiles: List[ProfileItem] = Field(default_factory=list)


@router.get("/profiles", response_model=ProfilesResponse)
def list_me_profiles(
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_profile_id: Optional[str] = Header(default=None, alias="X-Profile-Id"),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    # Resolve default profile (creates one if missing).
    default_profile_id = ensure_default_profile(user_id=user_id)
    # Best-effort: if caller has an explicit X-Profile-Id, validate it to surface ownership errors early.
    if x_profile_id:
        require_profile_id(user_id=user_id, x_profile_id=x_profile_id)

    resp = (
        _safe_table("child_profiles")
        .select("profile_id,display_name,avatar_url,is_default,created_at")
        .eq("user_id", str(user_id))
        .order("created_at", desc=False)
        .limit(50)
        .execute()
    )
    rows = getattr(resp, "data", None)
    profiles: List[ProfileItem] = []
    if isinstance(rows, list):
        for r in rows:
            if not isinstance(r, dict):
                continue
            pid = str(r.get("profile_id") or "").strip()
            name = str(r.get("display_name") or "").strip()
            if not pid or not name:
                continue
            profiles.append(
                ProfileItem(
                    profile_id=pid,
                    display_name=name,
                    avatar_url=(str(r.get("avatar_url")).strip() if r.get("avatar_url") else None),
                    is_default=bool(r.get("is_default")),
                    created_at=(str(r.get("created_at")).strip() if r.get("created_at") else None),
                )
            )
    if not profiles:
        # Should not happen if ensure_default_profile succeeded, but keep the API stable.
        profiles = [
            ProfileItem(
                profile_id=default_profile_id,
                display_name="默认",
                avatar_url=None,
                is_default=True,
            )
        ]
    return ProfilesResponse(default_profile_id=default_profile_id, profiles=profiles)


class CreateProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=30)
    avatar_url: Optional[str] = Field(default=None, max_length=500)


@router.post("/profiles", response_model=ProfileItem)
def create_me_profile(
    req: CreateProfileRequest,
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    name = str(req.display_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="display_name is required")
    # Enforce uniqueness under the same user_id.
    exists = (
        _safe_table("child_profiles")
        .select("profile_id")
        .eq("user_id", str(user_id))
        .eq("display_name", name)
        .limit(1)
        .execute()
    )
    rows = getattr(exists, "data", None)
    if isinstance(rows, list) and rows:
        raise HTTPException(status_code=409, detail="display_name_already_exists")

    now = _utc_now_iso()
    # supabase-py query builder doesn't support `.select()` chaining after `.insert()` in some versions.
    # Insert first, then read back deterministically.
    try:
        _safe_table("child_profiles").insert(
            {
                "user_id": str(user_id),
                "display_name": name,
                "avatar_url": (str(req.avatar_url).strip() if req.avatar_url else None),
                "is_default": False,
                "created_at": now,
                "updated_at": now,
            }
        ).execute()
    except Exception as e:
        logger.exception("create_me_profile insert failed")
        raise HTTPException(status_code=503, detail="failed_to_create_profile") from e

    resp = (
        _safe_table("child_profiles")
        .select("profile_id,display_name,avatar_url,is_default,created_at")
        .eq("user_id", str(user_id))
        .eq("display_name", name)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(resp, "data", None)
    row = rows[0] if isinstance(rows, list) and rows else {}
    pid = str((row or {}).get("profile_id") or "").strip()
    if not pid:
        raise HTTPException(status_code=503, detail="failed_to_create_profile")
    return ProfileItem(
        profile_id=pid,
        display_name=str(row.get("display_name") or name),
        avatar_url=(str(row.get("avatar_url")).strip() if row.get("avatar_url") else None),
        is_default=bool(row.get("is_default")),
        created_at=(str(row.get("created_at")).strip() if row.get("created_at") else now),
    )


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=30)
    avatar_url: Optional[str] = Field(default=None, max_length=500)


@router.patch("/profiles/{profile_id}", response_model=ProfileItem)
def update_me_profile(
    profile_id: str,
    req: UpdateProfileRequest,
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    pid = str(profile_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="profile_id is required")
    # Ensure ownership
    require_profile_id(user_id=user_id, x_profile_id=pid)

    update: Dict[str, Any] = {"updated_at": _utc_now_iso()}
    if req.display_name is not None:
        name = str(req.display_name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="display_name is required")
        # unique(user_id, display_name)
        exists = (
            _safe_table("child_profiles")
            .select("profile_id")
            .eq("user_id", str(user_id))
            .eq("display_name", name)
            .limit(1)
            .execute()
        )
        rows = getattr(exists, "data", None)
        if isinstance(rows, list) and rows:
            other = str(rows[0].get("profile_id") or "").strip() if isinstance(rows[0], dict) else ""
            if other and other != pid:
                raise HTTPException(status_code=409, detail="display_name_already_exists")
        update["display_name"] = name
    if req.avatar_url is not None:
        update["avatar_url"] = (str(req.avatar_url).strip() if req.avatar_url else None)

    # supabase-py query builder doesn't support `.select()` chaining after `.update()` in some versions.
    # Update first, then read back deterministically.
    try:
        _safe_table("child_profiles").update(update).eq("user_id", str(user_id)).eq(
            "profile_id", pid
        ).execute()
    except Exception as e:
        logger.exception("update_me_profile update failed")
        raise HTTPException(status_code=503, detail="failed_to_update_profile") from e

    resp = (
        _safe_table("child_profiles")
        .select("profile_id,display_name,avatar_url,is_default,created_at")
        .eq("user_id", str(user_id))
        .eq("profile_id", pid)
        .limit(1)
        .execute()
    )
    rows = getattr(resp, "data", None)
    row = rows[0] if isinstance(rows, list) and rows else {}
    if not isinstance(row, dict) or not str(row.get("profile_id") or "").strip():
        raise HTTPException(status_code=404, detail="profile_not_found")
    return ProfileItem(
        profile_id=str(row.get("profile_id")),
        display_name=str(row.get("display_name") or "").strip() or "默认",
        avatar_url=(str(row.get("avatar_url")).strip() if row.get("avatar_url") else None),
        is_default=bool(row.get("is_default")),
        created_at=(str(row.get("created_at")).strip() if row.get("created_at") else None),
    )


class SetDefaultResponse(BaseModel):
    ok: bool = True
    default_profile_id: str


@router.post("/profiles/{profile_id}/set_default", response_model=SetDefaultResponse)
def set_default_profile(
    profile_id: str,
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    pid = str(profile_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="profile_id is required")
    # Ensure it exists and belongs to user.
    require_profile_id(user_id=user_id, x_profile_id=pid)

    now = _utc_now_iso()
    # Unset all defaults, then set one (best-effort; DB partial unique index is the real guard).
    _safe_table("child_profiles").update({"is_default": False, "updated_at": now}).eq(
        "user_id", str(user_id)
    ).execute()
    _safe_table("child_profiles").update({"is_default": True, "updated_at": now}).eq(
        "user_id", str(user_id)
    ).eq("profile_id", pid).execute()
    return SetDefaultResponse(ok=True, default_profile_id=pid)


@router.delete("/profiles/{profile_id}")
def delete_me_profile(
    profile_id: str,
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    pid = str(profile_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="profile_id is required")

    # Load all profiles for this user.
    resp = (
        _safe_table("child_profiles")
        .select("profile_id,is_default")
        .eq("user_id", str(user_id))
        .order("created_at", desc=False)
        .limit(50)
        .execute()
    )
    rows = getattr(resp, "data", None)
    profiles = [r for r in (rows or []) if isinstance(r, dict)]
    if not profiles:
        raise HTTPException(status_code=404, detail="profile_not_found")

    if not any(str(p.get("profile_id") or "").strip() == pid for p in profiles):
        raise HTTPException(status_code=404, detail="profile_not_found")

    if len(profiles) <= 1:
        raise HTTPException(status_code=400, detail="cannot_delete_last_profile")

    was_default = any(
        str(p.get("profile_id") or "").strip() == pid and bool(p.get("is_default"))
        for p in profiles
    )

    _safe_table("child_profiles").delete().eq("user_id", str(user_id)).eq(
        "profile_id", pid
    ).execute()

    if was_default:
        # Promote the earliest remaining profile as default.
        remaining = [p for p in profiles if str(p.get("profile_id") or "").strip() != pid]
        next_pid = str((remaining[0] or {}).get("profile_id") or "").strip() if remaining else ""
        if next_pid:
            now = _utc_now_iso()
            _safe_table("child_profiles").update({"is_default": False, "updated_at": now}).eq(
                "user_id", str(user_id)
            ).execute()
            _safe_table("child_profiles").update({"is_default": True, "updated_at": now}).eq(
                "user_id", str(user_id)
            ).eq("profile_id", next_pid).execute()
    return {"ok": True}
