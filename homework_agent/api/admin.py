from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request, Query
from pydantic import BaseModel, Field

from homework_agent.utils.observability import log_event
from homework_agent.utils.settings import get_settings
from homework_agent.utils.supabase_client import get_worker_storage_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_table(name: str):
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
    q = _safe_table("users").select("user_id,phone,created_at,last_login_at").limit(
        max(1, min(limit, 200))
    )
    if phone:
        q = q.eq("phone", phone)
    resp = q.execute()
    rows = getattr(resp, "data", None)
    users: List[AdminUserDetail] = []
    if isinstance(rows, list):
        wallet_map: Dict[str, Dict[str, Any]] = {}
        if include_wallet and rows:
            ids = [str(r.get("user_id")) for r in rows if r.get("user_id")]
            if ids:
                w_resp = (
                    _safe_table("user_wallets")
                    .select(
                        "user_id,bt_trial,bt_subscription,bt_report_reserve,report_coupons,trial_expires_at,plan_tier,data_retention_tier,updated_at"
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
            "user_id,bt_trial,bt_subscription,bt_report_reserve,report_coupons,trial_expires_at,plan_tier,data_retention_tier,updated_at"
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
            "user_id,bt_trial,bt_subscription,bt_report_reserve,report_coupons,trial_expires_at,plan_tier,data_retention_tier,updated_at"
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
    update["bt_subscription"] = max(
        0, int(before["bt_subscription"]) + int(payload.bt_subscription_delta)
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
    before: Optional[str] = Query(default=None, description="ISO timestamp; created_at < before"),
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
    before: Optional[str] = Query(default=None, description="ISO timestamp; created_at < before"),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)
    before_iso = _parse_iso_utc_ts(before)
    if before and not before_iso:
        raise HTTPException(status_code=400, detail="invalid before timestamp")

    q = (
        _safe_table("submissions")
        .select("submission_id,user_id,profile_id,created_at,subject,session_id,warnings")
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
    before: Optional[str] = Query(default=None, description="ISO timestamp; created_at < before"),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    x_admin_actor: Optional[str] = Header(default=None, alias="X-Admin-Actor"),
):
    _require_admin(token=x_admin_token)
    before_iso = _parse_iso_utc_ts(before)
    if before and not before_iso:
        raise HTTPException(status_code=400, detail="invalid before timestamp")

    q = (
        _safe_table("reports")
        .select("id,user_id,profile_id,report_job_id,title,period_from,period_to,created_at")
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
