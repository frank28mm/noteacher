from __future__ import annotations

import os
from typing import Optional


def get_user_id(x_user_id: Optional[str]) -> str:
    """
    Dev-time user identity hook.

    Production should replace this with real auth (e.g. Supabase Auth / JWT) and derive user_id from token.
    """
    v = (x_user_id or "").strip()
    if v:
        return v
    return (os.getenv("DEV_USER_ID") or "dev_user").strip() or "dev_user"

