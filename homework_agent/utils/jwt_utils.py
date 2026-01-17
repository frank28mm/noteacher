from __future__ import annotations

import time
from typing import Any, Dict, Optional

import jwt
from fastapi import HTTPException, status

from homework_agent.utils.settings import get_settings


def issue_access_token(*, user_id: str, phone: Optional[str] = None) -> str:
    settings = get_settings()
    secret = str(getattr(settings, "jwt_secret", "") or "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET is not configured")

    now = int(time.time())
    exp = now + int(getattr(settings, "jwt_access_token_ttl_seconds", 0) or 0)
    if exp <= now:
        exp = now + 7 * 24 * 3600

    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "iss": str(getattr(settings, "jwt_issuer", "noteacher") or "noteacher"),
        "iat": now,
        "exp": exp,
        "role": "user",
    }
    if phone:
        payload["phone"] = str(phone)

    return jwt.encode(payload, secret, algorithm="HS256")


def verify_access_token(token: str) -> Dict[str, Any]:
    settings = get_settings()
    secret = str(getattr(settings, "jwt_secret", "") or "").strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET is not configured",
        )
    try:
        decoded = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "sub"]},
            issuer=str(getattr(settings, "jwt_issuer", "noteacher") or "noteacher"),
        )
        if not isinstance(decoded, dict):
            raise ValueError("invalid token payload")
        return decoded
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid auth token"
        )

