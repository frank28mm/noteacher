import logging
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request, Query
from pydantic import BaseModel, Field

from homework_agent.utils.observability import log_event
from homework_agent.utils.settings import get_settings
from homework_agent.utils.supabase_client import (
    get_worker_storage_client,
    get_service_role_storage_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_table(name: str):
    try:
        # Force service role for admin operations to bypass RLS
        storage = get_service_role_storage_client()
    except Exception as e:
        logger.warning(f"Service role key not available for admin: {e}")
        storage = get_worker_storage_client()
    return storage.client.table(name)


def _require_admin(*, token: Optional[str]) -> None:
    settings = get_settings()
    expected = str(getattr(settings, "admin_token", "") or "").strip()
    if not expected:
        raise HTTPException(status_code=403, detail="admin token not configured")
    if str(token or "").strip() != expected:
        raise HTTPException(status_code=403, detail="forbidden")


def _audit_log(
    *,
    request: Request,
    actor: Optional[str],
    action: str,
    target_type: Optional[str],
    target_id: Optional[str],
    payload: Optional[Dict[str, Any]],
) -> None:
    req_id = getattr(getattr(request, "state", None), "request_id", None)
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    try:
        _safe_table("admin_audit_logs").insert(
            {
                "actor": actor,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "payload": payload or {},
                "request_id": req_id,
                "ip": ip,
                "user_agent": user_agent,
                "created_at": _utc_now(),
            }
        ).execute()
    except Exception:
        pass


def _parse_iso_utc_ts(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _map_wallet(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "user_id": row.get("user_id"),
        "bt_trial": int(row.get("bt_trial") or 0),
        "bt_subscription": int(row.get("bt_subscription") or 0),
        "bt_subscription_active": int(row.get("bt_subscription_active") or 0),
        "bt_subscription_expired": int(row.get("bt_subscription_expired") or 0),
        "bt_report_reserve": int(row.get("bt_report_reserve") or 0),
        "report_coupons": int(row.get("report_coupons") or 0),
        "trial_expires_at": row.get("trial_expires_at"),
        "plan_tier": row.get("plan_tier"),
        "data_retention_tier": row.get("data_retention_tier"),
        "updated_at": row.get("updated_at"),
    }


class AdminUser(BaseModel):
    user_id: str
    phone: str
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None


class WalletInfo(BaseModel):
    user_id: str
    bt_trial: int
    bt_subscription: int
    bt_subscription_active: int = 0
    bt_subscription_expired: int = 0
    bt_report_reserve: int
    report_coupons: int
    trial_expires_at: Optional[str] = None
    plan_tier: Optional[str] = None
    data_retention_tier: Optional[str] = None
    updated_at: Optional[str] = None


class AdminUserDetail(BaseModel):
    user: AdminUser
    wallet: Optional[WalletInfo] = None


class UserListResponse(BaseModel):
    users: List[AdminUserDetail] = Field(default_factory=list)


class WalletAdjustRequest(BaseModel):
    bt_trial_delta: int = 0
    bt_subscription_delta: int = 0
    bt_report_reserve_delta: int = 0
    report_coupons_delta: int = 0
    plan_tier: Optional[str] = None
    data_retention_tier: Optional[str] = None
    trial_expires_at: Optional[str] = None
    reason: Optional[str] = Field(default=None, max_length=500)


@router.get("/users", response_model=UserListResponse)
def list_users(
    request: Request,
    phone: Optional[str] = None,
    limit: int = 20,
    include_wallet: bool = False,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)
    q = (
        _safe_table("users")
        .select("user_id,phone,created_at,last_login_at")
        .limit(max(1, min(limit, 200)))
    )
    if phone:
        # Support search by Phone OR User ID
        # Clean the input
        val = phone.strip()
        # Supabase OR syntax: column.eq.val,column2.eq.val
        q = q.or_(f"phone.eq.{val},user_id.eq.{val}")

    logger.info(f"Listing users with phone='{phone}'")
    resp = q.execute()
    rows = getattr(resp, "data", None)
    logger.info(f"Found {len(rows) if rows else 0} users")
    users: List[AdminUserDetail] = []
    if isinstance(rows, list):
        wallet_map: Dict[str, Dict[str, Any]] = {}
        if include_wallet and rows:
            ids = [str(r.get("user_id")) for r in rows if r.get("user_id")]
            if ids:
                w_resp = (
                    _safe_table("user_wallets")
                    .select(
                        "user_id,bt_trial,bt_subscription,bt_subscription_active,bt_subscription_expired,bt_report_reserve,report_coupons,trial_expires_at,plan_tier,data_retention_tier,updated_at"
                    )
                    .in_("user_id", ids)
                    .execute()
                )
                w_rows = getattr(w_resp, "data", None)
                if isinstance(w_rows, list):
                    wallet_map = {str(w.get("user_id")): _map_wallet(w) for w in w_rows}
        for row in rows:
            if not isinstance(row, dict):
                continue
            user = AdminUser(
                user_id=str(row.get("user_id")),
                phone=str(row.get("phone")),
                created_at=row.get("created_at"),
                last_login_at=row.get("last_login_at"),
            )
            wallet = None
            if include_wallet:
                w = wallet_map.get(user.user_id)
                if w:
                    wallet = WalletInfo(**w)
            users.append(AdminUserDetail(user=user, wallet=wallet))
    _audit_log(
        request=request,
        actor=x_admin_actor,
        action="users_list",
        target_type="users",
        target_id=None,
        payload={"phone": phone, "limit": limit, "include_wallet": include_wallet},
    )
    return UserListResponse(users=users)


@router.get("/users/{user_id}", response_model=AdminUserDetail)
def get_user_detail(
    request: Request,
    user_id: str,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)
    resp = (
        _safe_table("users")
        .select("user_id,phone,created_at,last_login_at")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = getattr(resp, "data", None)
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=404, detail="user_not_found")
    row = rows[0]
    user = AdminUser(
        user_id=str(row.get("user_id")),
        phone=str(row.get("phone")),
        created_at=row.get("created_at"),
        last_login_at=row.get("last_login_at"),
    )
    w_resp = (
        _safe_table("user_wallets")
        .select(
            "user_id,bt_trial,bt_subscription,bt_subscription_active,bt_subscription_expired,bt_report_reserve,report_coupons,trial_expires_at,plan_tier,data_retention_tier,updated_at"
        )
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    w_rows = getattr(w_resp, "data", None)
    wallet = None
    if isinstance(w_rows, list) and w_rows:
        wallet = WalletInfo(**_map_wallet(w_rows[0]))
    _audit_log(
        request=request,
        actor=x_admin_actor,
        action="user_get",
        target_type="users",
        target_id=user_id,
        payload={},
    )
    return AdminUserDetail(user=user, wallet=wallet)


@router.post("/users/{user_id}/wallet_adjust", response_model=AdminUserDetail)
def adjust_wallet(
    request: Request,
    user_id: str,
    payload: WalletAdjustRequest,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)
    w_resp = (
        _safe_table("user_wallets")
        .select(
            "user_id,bt_trial,bt_subscription,bt_subscription_active,bt_subscription_expired,bt_report_reserve,report_coupons,trial_expires_at,plan_tier,data_retention_tier,updated_at"
        )
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    w_rows = getattr(w_resp, "data", None)
    if not isinstance(w_rows, list) or not w_rows:
        raise HTTPException(status_code=404, detail="wallet_not_found")
    before = _map_wallet(w_rows[0])

    update: Dict[str, Any] = {"updated_at": _utc_now()}
    update["bt_trial"] = max(0, int(before["bt_trial"]) + int(payload.bt_trial_delta))
    new_bt_sub = max(
        0, int(before["bt_subscription"]) + int(payload.bt_subscription_delta)
    )
    update["bt_subscription"] = new_bt_sub
    update["bt_subscription_active"] = max(
        0, int(before["bt_subscription_active"]) + int(payload.bt_subscription_delta)
    )
    update["bt_report_reserve"] = max(
        0, int(before["bt_report_reserve"]) + int(payload.bt_report_reserve_delta)
    )
    update["report_coupons"] = max(
        0, int(before["report_coupons"]) + int(payload.report_coupons_delta)
    )
    if payload.plan_tier is not None:
        update["plan_tier"] = payload.plan_tier
    if payload.data_retention_tier is not None:
        update["data_retention_tier"] = payload.data_retention_tier
    if payload.trial_expires_at is not None:
        update["trial_expires_at"] = payload.trial_expires_at

    _safe_table("user_wallets").update(update).eq("user_id", user_id).execute()

    after = {**before, **update}
    _audit_log(
        request=request,
        actor=x_admin_actor,
        action="wallet_adjust",
        target_type="user_wallets",
        target_id=user_id,
        payload={
            "reason": payload.reason,
            "delta": payload.model_dump(),
            "before": before,
            "after": after,
        },
    )
    log_event(
        logger,
        "admin_wallet_adjust",
        user_id=user_id,
        actor=x_admin_actor,
        bt_trial_delta=payload.bt_trial_delta,
        bt_subscription_delta=payload.bt_subscription_delta,
        bt_report_reserve_delta=payload.bt_report_reserve_delta,
        report_coupons_delta=payload.report_coupons_delta,
    )
    user_resp = (
        _safe_table("users")
        .select("user_id,phone,created_at,last_login_at")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    u_rows = getattr(user_resp, "data", None)
    if not isinstance(u_rows, list) or not u_rows:
        raise HTTPException(status_code=404, detail="user_not_found")
    u = u_rows[0]
    user = AdminUser(
        user_id=str(u.get("user_id")),
        phone=str(u.get("phone")),
        created_at=u.get("created_at"),
        last_login_at=u.get("last_login_at"),
    )
    wallet = WalletInfo(**_map_wallet(after))
    return AdminUserDetail(user=user, wallet=wallet)


class GrantQuotaRequest(BaseModel):
    bt_amount: int = Field(..., ge=0, description="BT 额度")
    coupon_amount: int = Field(default=0, ge=0, description="报告券数量")
    expiry_days: int = Field(default=30, ge=1, le=365, description="额度有效天数")
    reason: Optional[str] = Field(default=None, max_length=500)


@router.post("/users/{user_id}/grant", response_model=AdminUserDetail)
def admin_grant_quota(
    user_id: str,
    request: Request,
    payload: GrantQuotaRequest,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)

    from homework_agent.services.quota_service import load_wallet, BT_GRANT_EXPIRY_DAYS

    wallet = load_wallet(user_id=user_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="wallet_not_found")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    expires_at = (now + timedelta(days=payload.expiry_days)).isoformat()
    bt_amount = payload.bt_amount
    coupon_amount = payload.coupon_amount

    before = {
        "bt_subscription": wallet.bt_subscription,
        "bt_subscription_active": wallet.bt_subscription_active,
        "report_coupons": wallet.report_coupons,
    }

    new_bt_sub = wallet.bt_subscription + bt_amount
    new_bt_active = wallet.bt_subscription_active + bt_amount
    new_coupons = wallet.report_coupons + coupon_amount

    _safe_table("user_wallets").update(
        {
            "bt_subscription": new_bt_sub,
            "bt_subscription_active": new_bt_active,
            "report_coupons": new_coupons,
            "updated_at": now_iso,
        }
    ).eq("user_id", user_id).execute()

    if bt_amount > 0:
        grant_id = str(uuid.uuid4())
        _safe_table("bt_grants").insert(
            {
                "id": grant_id,
                "user_id": user_id,
                "bt_amount": bt_amount,
                "grant_type": "admin_grant",
                "expires_at": expires_at,
                "created_from": "admin_grant",
                "reference_id": None,
                "meta": {
                    "actor": x_admin_actor,
                    "reason": payload.reason,
                    "expiry_days": payload.expiry_days,
                },
            }
        ).execute()

    after = {
        "bt_subscription": new_bt_sub,
        "bt_subscription_active": new_bt_active,
        "report_coupons": new_coupons,
    }

    _audit_log(
        request=request,
        actor=x_admin_actor,
        action="admin_grant_quota",
        target_type="user_wallets",
        target_id=user_id,
        payload={
            "reason": payload.reason,
            "bt_amount": bt_amount,
            "coupon_amount": coupon_amount,
            "expiry_days": payload.expiry_days,
            "expires_at": expires_at,
            "before": before,
            "after": after,
        },
    )

    log_event(
        logger,
        "admin_grant_quota",
        user_id=user_id,
        actor=x_admin_actor,
        bt_amount=bt_amount,
        coupon_amount=coupon_amount,
        expiry_days=payload.expiry_days,
    )

    u_resp = (
        _safe_table("users")
        .select("user_id,phone,created_at,last_login_at")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    u_rows = getattr(u_resp, "data", None)
    if not isinstance(u_rows, list) or not u_rows:
        raise HTTPException(status_code=404, detail="user_not_found")
    u = u_rows[0]
    user_obj = AdminUser(
        user_id=str(u.get("user_id")),
        phone=str(u.get("phone")),
        created_at=u.get("created_at"),
        last_login_at=u.get("last_login_at"),
    )

    w_resp = (
        _safe_table("user_wallets")
        .select(
            "user_id,bt_trial,bt_subscription,bt_subscription_active,bt_subscription_expired,bt_report_reserve,report_coupons,trial_expires_at,plan_tier,data_retention_tier,updated_at"
        )
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    w_rows = getattr(w_resp, "data", None)
    wallet_info = WalletInfo(**_map_wallet(w_rows[0])) if w_rows else None

    return AdminUserDetail(user=user_obj, wallet=wallet_info)


@router.get("/audit_logs")
def list_audit_logs(
    request: Request,
    limit: int = 50,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)
    resp = (
        _safe_table("admin_audit_logs")
        .select("*")
        .order("created_at", desc=True)
        .limit(max(1, min(limit, 200)))
        .execute()
    )
    rows = getattr(resp, "data", None)
    _audit_log(
        request=request,
        actor=x_admin_actor,
        action="audit_logs_list",
        target_type="admin_audit_logs",
        target_id=None,
        payload={"limit": limit},
    )
    if not isinstance(rows, list):
        return {"items": []}
    return {"items": rows}


@router.get("/usage_ledger")
def list_usage_ledger(
    request: Request,
    *,
    user_id: str = Query(..., min_length=1),
    limit: int = Query(default=50, ge=1, le=200),
    before: Optional[str] = Query(
        default=None, description="ISO timestamp; created_at < before"
    ),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)
    before_iso = _parse_iso_utc_ts(before)
    if before and not before_iso:
        raise HTTPException(status_code=400, detail="invalid before timestamp")

    q = (
        _safe_table("usage_ledger")
        .select("*")
        .eq("user_id", str(user_id))
        .order("created_at", desc=True)
        .limit(int(limit))
    )
    if before_iso:
        q = q.lt("created_at", before_iso)
    resp = q.execute()
    rows = getattr(resp, "data", None)
    _audit_log(
        request=request,
        actor=x_admin_actor,
        action="usage_ledger_list",
        target_type="usage_ledger",
        target_id=str(user_id),
        payload={"limit": int(limit), "before": before_iso},
    )
    return {"items": rows if isinstance(rows, list) else []}


@router.get("/submissions")
def list_submissions_admin(
    request: Request,
    *,
    user_id: str = Query(..., min_length=1),
    profile_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    before: Optional[str] = Query(
        default=None, description="ISO timestamp; created_at < before"
    ),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)
    before_iso = _parse_iso_utc_ts(before)
    if before and not before_iso:
        raise HTTPException(status_code=400, detail="invalid before timestamp")

    q = (
        _safe_table("submissions")
        .select(
            "submission_id,user_id,profile_id,created_at,subject,session_id,warnings"
        )
        .eq("user_id", str(user_id))
        .order("created_at", desc=True)
        .limit(int(limit))
    )
    pid = str(profile_id or "").strip()
    if pid:
        q = q.eq("profile_id", pid)
    if before_iso:
        q = q.lt("created_at", before_iso)
    resp = q.execute()
    rows = getattr(resp, "data", None)
    _audit_log(
        request=request,
        actor=x_admin_actor,
        action="submissions_list",
        target_type="submissions",
        target_id=str(user_id),
        payload={"profile_id": pid or None, "limit": int(limit), "before": before_iso},
    )
    return {"items": rows if isinstance(rows, list) else []}


@router.get("/reports")
def list_reports_admin(
    request: Request,
    *,
    user_id: str = Query(..., min_length=1),
    profile_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    before: Optional[str] = Query(
        default=None, description="ISO timestamp; created_at < before"
    ),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)
    before_iso = _parse_iso_utc_ts(before)
    if before and not before_iso:
        raise HTTPException(status_code=400, detail="invalid before timestamp")

    q = (
        _safe_table("reports")
        .select(
            "id,user_id,profile_id,report_job_id,title,period_from,period_to,created_at"
        )
        .eq("user_id", str(user_id))
        .order("created_at", desc=True)
        .limit(int(limit))
    )
    pid = str(profile_id or "").strip()
    if pid:
        q = q.eq("profile_id", pid)
    if before_iso:
        q = q.lt("created_at", before_iso)
    resp = q.execute()
    rows = getattr(resp, "data", None)
    _audit_log(
        request=request,
        actor=x_admin_actor,
        action="reports_list",
        target_type="reports",
        target_id=str(user_id),
        payload={"profile_id": pid or None, "limit": int(limit), "before": before_iso},
    )
    return {"items": rows if isinstance(rows, list) else []}


class GenerateRedeemCardsRequest(BaseModel):
    card_type: str = Field(
        ..., description="trial_pack / subscription_pack / report_coupon"
    )
    bt_amount: int = 0
    coupon_amount: int = 0
    premium_days: int = 0
    count: int = Field(default=1, ge=1, le=1000)
    batch_id: str = Field(..., min_length=1)
    expires_days: int = Field(default=30, ge=1)
    meta: Optional[Dict[str, Any]] = None


@router.post("/redeem_cards/generate")
def generate_redeem_cards(
    request: Request,
    payload: GenerateRedeemCardsRequest,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)

    codes = []
    # Always set expires_at based on expires_days (default 30)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=payload.expires_days)
    ).isoformat()

    now_str = _utc_now()
    rows_to_insert = []

    # Use uppercase letters and digits for the code
    chars = string.ascii_uppercase + string.digits

    for _ in range(payload.count):
        # Format: 14 chars, A-Z0-9
        code = "".join(random.choices(chars, k=14))

        # Extract plan_tier from meta if present
        plan_tier = None
        if payload.meta and "target_tier" in payload.meta:
            plan_tier = payload.meta["target_tier"]

        rows_to_insert.append(
            {
                "code": code,
                "card_type": payload.card_type,
                "bt_amount": payload.bt_amount,
                "report_coupons": payload.coupon_amount,
                "premium_days": payload.premium_days,
                "plan_tier": plan_tier,
                "batch_id": payload.batch_id,
                "status": "active",
                "expires_at": expires_at,
                "created_at": now_str,
            }
        )
        codes.append(code)

    if rows_to_insert:
        _safe_table("redeem_cards").insert(rows_to_insert).execute()

    _audit_log(
        request=request,
        actor=x_admin_actor,
        action="redeem_cards_generate",
        target_type="redeem_cards",
        target_id=payload.batch_id,
        payload=payload.model_dump(),
    )

    return {"codes": codes, "count": len(codes), "batch_id": payload.batch_id}


@router.get("/redemptions")
def list_redemptions_admin(
    request: Request,
    *,
    user_id: Optional[str] = Query(default=None),
    code: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)
    q = (
        _safe_table("redeem_cards")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
    )

    if user_id:
        q = q.eq("redeemed_by", str(user_id))
    if code:
        q = q.eq("code", str(code))
    if status:
        q = q.eq("status", str(status))

    resp = q.execute()
    rows = getattr(resp, "data", [])

    _audit_log(
        request=request,
        actor=x_admin_actor,
        action="redemptions_list",
        target_type="redeem_cards",
        target_id=None,
        payload={"user_id": user_id, "code": code, "limit": limit},
    )
    return {"items": rows}


@router.get("/redeem_cards/batches")
def list_card_batches(
    request: Request,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    _require_admin(token=x_admin_token)
    # Use RPC for aggregation
    resp = (
        _safe_table("redeem_cards").select("*").limit(0).execute()
    )  # Dummy to get client
    # Actually supabase-py client.rpc(...)
    storage = get_worker_storage_client()
    rpc_resp = storage.client.rpc("admin_get_batch_stats", {}).execute()

    return {"items": getattr(rpc_resp, "data", [])}


@router.post("/redeem_cards/batches/{batch_id}/disable")
def disable_card_batch(
    request: Request,
    batch_id: str,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)

    # Disable only active cards in this batch
    resp = (
        _safe_table("redeem_cards")
        .update({"status": "disabled", "updated_at": _utc_now()})
        .eq("batch_id", batch_id)
        .eq("status", "active")
        .execute()
    )

    updated = getattr(resp, "data", [])
    count = len(updated) if isinstance(updated, list) else 0

    _audit_log(
        request=request,
        actor=x_admin_actor,
        action="batch_disable",
        target_type="redeem_cards",
        target_id=batch_id,
        payload={"disabled_count": count},
    )

    return {"ok": True, "disabled_count": count}


class BulkUpdateCardsRequest(BaseModel):
    codes: List[str]
    status: str = Field(..., pattern="^(active|disabled)$")


@router.post("/redeem_cards/bulk_update")
def bulk_update_cards(
    request: Request,
    payload: BulkUpdateCardsRequest,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)

    if not payload.codes:
        return {"updated_count": 0}

    resp = (
        _safe_table("redeem_cards")
        .update({"status": payload.status, "updated_at": _utc_now()})
        .in_("code", payload.codes)
        .execute()
    )

    updated = getattr(resp, "data", [])
    count = len(updated) if isinstance(updated, list) else 0

    _audit_log(
        request=request,
        actor=x_admin_actor,
        action="cards_bulk_update",
        target_type="redeem_cards",
        target_id=None,
        payload={
            "status": payload.status,
            "count": count,
            "codes": payload.codes[:10],
        },  # truncate logs
    )

    return {"ok": True, "updated_count": count}


@router.get("/stats/dashboard")
def get_dashboard_stats(
    request: Request,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    _require_admin(token=x_admin_token)

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    month_start = now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()

    # --- 1. KPIs ---
    # Total Users
    u_resp = _safe_table("users").select("user_id", count="exact", head=True).execute()
    total_users = u_resp.count or 0

    # Paid Users (plan_tier != 'free' or has subscription balance)
    w_resp = (
        _safe_table("user_wallets")
        .select("plan_tier")
        .neq("plan_tier", "free")
        .execute()
    )
    paid_users = len(getattr(w_resp, "data", []) or [])
    paid_ratio = round((paid_users / total_users * 100) if total_users > 0 else 0, 1)

    # DAU (Active Today)
    dau_resp = (
        _safe_table("users")
        .select("user_id", count="exact", head=True)
        .gt("last_login_at", today_start)
        .execute()
    )
    dau = dau_resp.count or 0

    mrr = 0.0

    # --- 2. Cost & Usage ---
    # Token Usage Today
    usage_resp = (
        _safe_table("usage_ledger")
        .select("total_tokens")
        .gt("created_at", today_start)
        .limit(1000)
        .execute()
    )
    tokens_today = sum(
        int(r.get("total_tokens") or 0) for r in (getattr(usage_resp, "data", []) or [])
    )

    # Submissions Today
    sub_resp = (
        _safe_table("submissions")
        .select("id", count="exact", head=True)
        .gt("created_at", today_start)
        .execute()
    )
    subs_today = sub_resp.count or 0

    # Avg Cost per Submission
    avg_cost_tokens = int(tokens_today / subs_today) if subs_today > 0 else 0

    # --- 3. Conversion ---
    # Card Redemption Rate
    card_total_resp = (
        _safe_table("redeem_cards").select("id", count="exact", head=True).execute()
    )
    card_total = card_total_resp.count or 0

    card_redeemed_resp = (
        _safe_table("redeem_cards")
        .select("id", count="exact", head=True)
        .eq("status", "redeemed")
        .execute()
    )
    card_redeemed = card_redeemed_resp.count or 0

    card_rate = round((card_redeemed / card_total * 100) if card_total > 0 else 0, 1)

    # --- 4. Health ---
    # Error Rate Mock
    err_count = 0  # Placeholder
    error_rate = round((err_count / subs_today * 100) if subs_today > 0 else 0, 2)

    # Latency (P50) - Mock
    latency_p50 = "1.2s"

    return {
        "kpi": {
            "total_users": total_users,
            "paid_ratio": f"{paid_ratio}%",
            "dau": dau,
            "mrr": f"¥{mrr:,.2f}",
        },
        "cost": {
            "tokens_today": f"{tokens_today:,}",
            "subs_today": subs_today,
            "avg_cost": f"{avg_cost_tokens} T/sub",
        },
        "conversion": {
            "card_redemption_rate": f"{card_rate}% ({card_redeemed}/{card_total})",
            "trial_conversion": f"{paid_ratio}%",  # Reusing paid ratio as proxy
        },
        "health": {
            "error_rate": f"{error_rate}%",
            "latency_p50": latency_p50,
        },
    }
