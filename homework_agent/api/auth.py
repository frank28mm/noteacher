from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from homework_agent.utils.cache import get_cache_store
from homework_agent.utils.jwt_utils import issue_access_token
from homework_agent.utils.observability import log_event
from homework_agent.utils.settings import get_settings
from homework_agent.utils.supabase_client import get_worker_storage_client
from homework_agent.utils.user_context import require_user_id
from homework_agent.utils.security import verify_password, get_password_hash
from homework_agent.services.sms_aliyun import (
    send_sms_verify_code,
    check_sms_verify_code,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def normalize_cn_phone(phone: str) -> str:
    """
    Normalize CN phone input to E.164-like format (+86XXXXXXXXXXX).
    Accepts:
    - 11-digit mainland numbers
    - +86 prefix
    - 86 prefix
    """
    raw = str(phone or "").strip()
    if not raw:
        raise ValueError("phone is required")
    digits = re.sub(r"[^0-9+]", "", raw)
    digits = digits.strip()

    if digits.startswith("+86"):
        n = digits[3:]
    elif digits.startswith("86") and len(digits) >= 13:
        n = digits[2:]
    else:
        n = digits.lstrip("+")

    n = re.sub(r"\\D", "", n)
    if len(n) != 11 or not n.startswith("1"):
        raise ValueError("invalid phone number")
    return f"+86{n}"


def _safe_table(name: str):
    """
    Use worker-safe client (service role preferred) for auth/account tables.
    This keeps us independent from Supabase Auth RLS while we're still iterating.
    """
    storage = get_worker_storage_client()
    return storage.client.table(name)


def _get_sms_code_cache_key(phone_e164: str) -> str:
    return f"auth:sms_code:{phone_e164}"


def _get_sms_cooldown_key(phone_e164: str) -> str:
    return f"auth:sms_cooldown:{phone_e164}"


def _issue_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def _check_send_cooldown(phone_e164: str) -> None:
    settings = get_settings()
    cache = get_cache_store()
    cooldown_key = _get_sms_cooldown_key(phone_e164)
    if cache.get(cooldown_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many requests",
        )
    cache.set(
        cooldown_key,
        {"ok": True},
        ttl_seconds=int(getattr(settings, "sms_send_cooldown_seconds", 60) or 60),
    )


class SmsSendRequest(BaseModel):
    phone: str = Field(min_length=6)


class SmsSendResponse(BaseModel):
    ok: bool
    expires_in_seconds: int
    # Dev-only: returned only when SMS_RETURN_CODE_IN_RESPONSE=1 and APP_ENV!=prod.
    code: Optional[str] = None


@router.post("/sms/send", response_model=SmsSendResponse)
async def send_sms_code(req: SmsSendRequest):
    settings = get_settings()
    try:
        phone = normalize_cn_phone(req.phone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _check_send_cooldown(phone)

    provider = str(getattr(settings, "sms_provider", "mock") or "mock").strip().lower()
    ttl = int(getattr(settings, "sms_code_ttl_seconds", 300) or 300)
    env = str(getattr(settings, "app_env", "dev") or "dev").strip().lower()
    include_code = bool(
        getattr(settings, "sms_return_code_in_response", False)
    ) and env not in {
        "prod",
        "production",
    }

    if provider == "aliyun":
        scheme_name = str(
            getattr(settings, "aliyun_sms_scheme_name", "默认方案") or "默认方案"
        )
        success, verify_code, message = await send_sms_verify_code(
            phone,
            scheme_name=scheme_name,
            code_length=6,
            valid_time=ttl,
            return_verify_code=include_code,
        )
        if not success:
            log_event(logger, "auth_sms_send_failed", phone=phone, error=message)
            if message == "FREQUENCY_FAIL":
                raise HTTPException(status_code=429, detail="too many requests")
            raise HTTPException(status_code=500, detail=f"sms send failed: {message}")

        log_event(
            logger,
            "auth_sms_code_issued",
            phone=phone,
            ttl_seconds=ttl,
            provider="aliyun",
        )
        return SmsSendResponse(
            ok=True,
            expires_in_seconds=ttl,
            code=(verify_code if include_code and verify_code else None),
        )

    elif provider == "mock":
        code = _issue_code()
        cache = get_cache_store()
        cache.set(_get_sms_code_cache_key(phone), {"code": code}, ttl_seconds=ttl)
        log_event(
            logger,
            "auth_sms_code_issued",
            phone=phone,
            ttl_seconds=ttl,
            provider="mock",
        )
        logger.info("DEV SMS code for %s: %s (ttl=%ss)", phone, code, ttl)
        return SmsSendResponse(
            ok=True, expires_in_seconds=ttl, code=(code if include_code else None)
        )

    else:
        raise HTTPException(
            status_code=500,
            detail="sms provider not configured (use SMS_PROVIDER=mock or aliyun)",
        )


class SmsVerifyRequest(BaseModel):
    phone: str = Field(min_length=6)
    code: str = Field(min_length=4, max_length=8)


class AuthUser(BaseModel):
    user_id: str
    phone: str
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None


class SmsVerifyResponse(BaseModel):
    access_token: str
    token_type: str = Field(default="bearer")
    expires_at: str
    user: AuthUser


def get_token_expires_at(settings) -> str:
    ttl = int(getattr(settings, "jwt_access_token_ttl_seconds", 0) or 0)
    if ttl <= 0:
        return "never"
    now = _utc_now()
    exp = now + timedelta(seconds=ttl)
    return _iso(exp)


def _ensure_user_and_wallet(*, phone_e164: str) -> Dict[str, Any]:
    now = _utc_now()
    _safe_table("users").upsert(
        {
            "phone": phone_e164,
            "last_login_at": _iso(now),
        },
        on_conflict="phone",
    ).execute()

    resp = (
        _safe_table("users")
        .select("user_id,phone,created_at,last_login_at")
        .eq("phone", phone_e164)
        .limit(1)
        .execute()
    )
    rows = getattr(resp, "data", None)
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise RuntimeError("failed to create user")
    user = rows[0]
    user_id = str(user.get("user_id") or "").strip()
    if not user_id:
        raise RuntimeError("user_id missing")

    # Ensure wallet row exists. Trial pack is granted on first wallet creation.
    # (All registered users get it; subscription can stack later.)
    wallet_resp = (
        _safe_table("user_wallets")
        .select("user_id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    wallet_rows = getattr(wallet_resp, "data", None)
    if not isinstance(wallet_rows, list) or not wallet_rows:
        settings = get_settings()
        bt_per_cp = 12400
        trial_cp = 200
        trial_bt = trial_cp * bt_per_cp
        trial_days = 5
        trial_expires_at = _iso(now + timedelta(days=trial_days))
        # Reserve BT for the single free report so it won't be consumed by grade/chat.
        # Keep a conservative default; can be tuned later.
        report_reserve_bt = 50 * bt_per_cp  # 50 CP worth of reserve
        _safe_table("user_wallets").insert(
            {
                "user_id": user_id,
                "bt_trial": int(trial_bt),
                "bt_subscription": 0,
                "bt_report_reserve": int(report_reserve_bt),
                "report_coupons": 1,
                "trial_expires_at": trial_expires_at,
                "plan_tier": None,
                "data_retention_tier": "trial",
                "updated_at": _iso(now),
            }
        ).execute()
        log_event(
            logger,
            "trial_pack_granted",
            user_id=user_id,
            trial_cp=trial_cp,
            report_coupons=1,
            trial_expires_at=trial_expires_at,
        )

    return {
        "user_id": user_id,
        "phone": phone_e164,
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


@router.post("/sms/verify", response_model=SmsVerifyResponse)
async def verify_sms_code(req: SmsVerifyRequest):
    settings = get_settings()
    try:
        phone = normalize_cn_phone(req.phone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    code = str(req.code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="code is required")

    provider = str(getattr(settings, "sms_provider", "mock") or "mock").strip().lower()

    if provider == "aliyun":
        scheme_name = str(
            getattr(settings, "aliyun_sms_scheme_name", "默认方案") or "默认方案"
        )
        success, message = await check_sms_verify_code(
            phone,
            code,
            scheme_name=scheme_name,
        )
        if not success:
            log_event(logger, "auth_sms_verify_failed", phone=phone, result=message)
            raise HTTPException(status_code=401, detail="invalid code")
    else:
        cache = get_cache_store()
        payload = cache.get(_get_sms_code_cache_key(phone))
        expected = str((payload or {}).get("code") or "").strip()
        if not expected or expected != code:
            raise HTTPException(status_code=401, detail="invalid code")
        cache.delete(_get_sms_code_cache_key(phone))

    try:
        user = _ensure_user_and_wallet(phone_e164=phone)
    except Exception as e:
        logger.exception("Failed to ensure user/wallet: %s", e)
        raise HTTPException(status_code=500, detail="failed to create user")

    token = issue_access_token(user_id=str(user["user_id"]), phone=phone)
    expires_at = get_token_expires_at(settings)
    return SmsVerifyResponse(
        access_token=token,
        expires_at=expires_at,
        user=AuthUser(**user),
    )


class LogoutResponse(BaseModel):
    ok: bool = True


@router.post("/logout", response_model=LogoutResponse)
def logout(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    # Stateless JWT: logout is handled client-side by discarding the token.
    if authorization:
        log_event(logger, "auth_logout", has_auth=bool(authorization))
    return LogoutResponse(ok=True)


class LoginEmailRequest(BaseModel):
    email: str = Field(min_length=5)
    password: str = Field(min_length=6)


@router.post("/login/email", response_model=SmsVerifyResponse)
def login_email(req: LoginEmailRequest):
    settings = get_settings()
    email = req.email.strip().lower()

    # 1. Find user by email
    resp = (
        _safe_table("users")
        .select("user_id,phone,password_hash,created_at,last_login_at")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    rows = getattr(resp, "data", None)
    if not isinstance(rows, list) or not rows:
        # Avoid user enumeration? For MVP, explicit error is fine.
        raise HTTPException(status_code=401, detail="invalid_credentials")

    user = rows[0]
    pwd_hash = str(user.get("password_hash") or "")
    if not pwd_hash:
        raise HTTPException(status_code=401, detail="password_not_set")

    # 2. Verify password
    if not verify_password(req.password, pwd_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")

    # 3. Issue token
    user_id = str(user["user_id"])
    phone = str(user.get("phone") or "")

    # Update last login
    try:
        _safe_table("users").update({"last_login_at": _iso(_utc_now())}).eq(
            "user_id", user_id
        ).execute()
    except Exception as e:
        logger.warning(f"Failed to update last_login: {e}")

    token = issue_access_token(user_id=user_id, phone=phone)
    expires_at = get_token_expires_at(settings)

    return SmsVerifyResponse(
        access_token=token,
        expires_at=expires_at,
        user=AuthUser(
            user_id=user_id,
            phone=phone,
            created_at=user.get("created_at"),
            last_login_at=_iso(_utc_now()),
        ),
    )
