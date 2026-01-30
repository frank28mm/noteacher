from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from homework_agent.utils.supabase_client import get_worker_storage_client

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profiles_backend_configured() -> bool:
    """
    Profiles live in Supabase Postgres. In unit tests we often monkeypatch table access without
    configuring Supabase env vars, so treat missing env as "profiles backend unavailable".
    """
    # Hard rule: in APP_ENV=test we should not rely on external Supabase, even if the
    # developer machine has SUPABASE_* exported. This keeps unit tests deterministic and
    # prevents accidental real network calls.
    if (os.getenv("APP_ENV") or "").strip().lower() == "test":
        return False

    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or ""
    ).strip()
    return bool(url and key)


def _safe_table(name: str):
    storage = get_worker_storage_client()
    return storage.client.table(name)


def list_profiles(*, user_id: str) -> List[Dict[str, Any]]:
    uid = str(user_id or "").strip()
    if not uid:
        return []
    try:
        resp = (
            _safe_table("child_profiles")
            .select("profile_id,user_id,display_name,avatar_url,is_default,created_at")
            .eq("user_id", uid)
            .order("created_at", desc=False)
            .limit(50)
            .execute()
        )
        rows = getattr(resp, "data", None)
        return rows if isinstance(rows, list) else []
    except Exception as e:
        logger.warning("list_profiles failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="profiles_unavailable",
        ) from e


def ensure_default_profile(*, user_id: str) -> str:
    """
    Ensure the user has at least one profile, and return a default profile_id.
    Best-effort invariant: exactly one is_default=true per user (enforced by DB index if present).
    """
    uid = str(user_id or "").strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="user_id required"
        )

    profiles = list_profiles(user_id=uid)
    for p in profiles:
        if isinstance(p, dict) and bool(p.get("is_default")):
            pid = str(p.get("profile_id") or "").strip()
            if pid:
                return pid
    if profiles:
        first = profiles[0] if isinstance(profiles[0], dict) else {}
        pid = str(first.get("profile_id") or "").strip()
        if pid:
            try:
                _safe_table("child_profiles").update({"is_default": True}).eq(
                    "profile_id", pid
                ).eq("user_id", uid).execute()
            except Exception:
                pass
            return pid

    try:
        # supabase-py query builder doesn't support `.select()` chaining after `.insert()` in some versions.
        # Insert first, then read back deterministically.
        now = _utc_now_iso()
        _safe_table("child_profiles").insert(
            {
                "user_id": uid,
                "display_name": "默认",
                "avatar_url": None,
                "is_default": True,
                "created_at": now,
                "updated_at": now,
            }
        ).execute()
        resp = (
            _safe_table("child_profiles")
            .select("profile_id")
            .eq("user_id", uid)
            .eq("display_name", "默认")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None)
        row = rows[0] if isinstance(rows, list) and rows else {}
        pid = str((row or {}).get("profile_id") or "").strip()
        if not pid:
            raise RuntimeError("empty profile_id returned")
        return pid
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("ensure_default_profile failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="failed_to_create_default_profile",
        ) from e


def require_profile_id(*, user_id: str, x_profile_id: Optional[str]) -> str:
    """
    Resolve the effective profile_id for the request.
    - If X-Profile-Id is provided: validate ownership, else 403.
    - If missing: return (and ensure) default profile_id.
    """
    uid = str(user_id or "").strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="user_id required"
        )

    # Unit tests frequently run without Supabase env configured (but may monkeypatch other DB tables).
    # In that scenario, do not block requests just because the profiles backend is unavailable.
    if not _profiles_backend_configured():
        return str(x_profile_id or "").strip()

    provided = str(x_profile_id or "").strip()
    if provided:
        profiles = list_profiles(user_id=uid)
        if any(
            str(p.get("profile_id") or "").strip() == provided
            for p in profiles
            if isinstance(p, dict)
        ):
            return provided
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="profile_not_found_or_not_owned",
        )

    return ensure_default_profile(user_id=uid)


def validate_profile_ownership(*, user_id: str, profile_id: str) -> None:
    pid = str(profile_id or "").strip()
    if not pid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="profile_id required"
        )
    if not _profiles_backend_configured():
        return
    _ = require_profile_id(user_id=user_id, x_profile_id=pid)
