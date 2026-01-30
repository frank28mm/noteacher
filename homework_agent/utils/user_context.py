from __future__ import annotations
import os
from typing import Optional

import httpx
from fastapi import HTTPException, status

from homework_agent.utils.settings import get_settings
from homework_agent.utils import jwt_utils


def verify_access_token(token: str) -> dict:
    # Keep a stable symbol for tests/monkeypatching.
    return jwt_utils.verify_access_token(token)


def get_user_id(x_user_id: Optional[str]) -> str:
    """
    Dev-time user identity hook.

    Production should replace this with real auth (e.g. Supabase Auth / JWT) and derive user_id from token.
    """
    v = (x_user_id or "").strip()
    if v:
        return v
    return (os.getenv("DEV_USER_ID") or "dev_user").strip() or "dev_user"


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    s = str(authorization).strip()
    if not s:
        return None
    if not s.lower().startswith("bearer "):
        return None
    token = s.split(" ", 1)[1].strip()
    return token or None


def _verify_supabase_jwt(token: str) -> Optional[str]:
    """
    Verify a Supabase Auth JWT and return user_id (jwt.sub) via GoTrue /auth/v1/user endpoint.
    This avoids embedding the JWT secret in our backend.
    """
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY") or "").strip()
    if not url or not key or not token:
        return None
    base = url.rstrip("/")
    endpoint = f"{base}/auth/v1/user"
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            r = client.get(
                endpoint, headers={"apikey": key, "Authorization": f"Bearer {token}"}
            )
        if r.status_code != 200:
            return None
        data = r.json() if r.content else {}
        if not isinstance(data, dict):
            return None
        uid = (data.get("id") or "").strip()
        if uid:
            return uid
        user = data.get("user")
        if isinstance(user, dict):
            uid2 = (user.get("id") or "").strip()
            return uid2 or None
        return None
    except Exception:
        return None


def require_user_id(
    *, authorization: Optional[str], x_user_id: Optional[str] = None
) -> str:
    """
    User identity:
    - If Authorization Bearer token exists:
      - AUTH_MODE=local: verify locally-issued JWT (phone login)
      - AUTH_MODE=supabase: verify Supabase Auth JWT via /auth/v1/user endpoint
    - Otherwise fall back to dev user id (unless AUTH_REQUIRED=1).
    """
    token = _extract_bearer_token(authorization)
    if token:
        settings = get_settings()
        mode = str(getattr(settings, "auth_mode", "dev") or "dev").strip().lower()
        if mode == "local":
            decoded = verify_access_token(token)
            uid = str(decoded.get("sub") or "").strip()
            if uid:
                return uid
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid auth token"
            )
        # Default: keep compatibility with existing Supabase Auth flow.
        uid = _verify_supabase_jwt(token)
        if uid:
            return uid
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid auth token"
        )

    settings = get_settings()
    if bool(getattr(settings, "auth_required", False)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization bearer token",
        )

    # Dev mode fallback is only allowed when AUTH_REQUIRED=0.
    return get_user_id(x_user_id)
