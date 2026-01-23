import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from homework_agent.utils.user_context import require_user_id
from homework_agent.utils.supabase_client import get_worker_storage_client
from homework_agent.services.quota_service import grant_subscription_quota, load_wallet

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def _safe_table(name: str):
    storage = get_worker_storage_client()
    return storage.client.table(name)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RedeemRequest(BaseModel):
    code: str = Field(..., min_length=8)


class RedeemResponse(BaseModel):
    ok: bool
    granted_bt: int
    granted_coupons: int


@router.post("/redeem", response_model=RedeemResponse)
def redeem_code(
    req: RedeemRequest,
    *,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    code = req.code.strip()

    resp = _safe_table("redeem_cards").select("*").eq("code", code).single().execute()
    card = getattr(resp, "data", None)
    if not card:
        raise HTTPException(status_code=400, detail="invalid_code")

    if card["status"] != "active":
        raise HTTPException(status_code=400, detail="code_already_used_or_expired")

    if card.get("expires_at"):
        try:
            exp = datetime.fromisoformat(card["expires_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp:
                raise HTTPException(status_code=400, detail="code_expired")
        except ValueError:
            pass

    bt_amount = int(card.get("bt_amount") or 0)
    coupon_amount = int(card.get("report_coupons") or 0)
    card_plan_tier = card.get("plan_tier") or ""

    current_wallet = load_wallet(user_id=user_id)

    final_plan_tier = (
        card_plan_tier
        or (current_wallet.plan_tier if current_wallet else None)
        or "free"
    )
    final_data_retention = (
        current_wallet.data_retention_tier if current_wallet else "3m"
    )

    ok, err = grant_subscription_quota(
        user_id=user_id,
        bt_amount=bt_amount,
        coupon_amount=coupon_amount,
        plan_tier=final_plan_tier,
        data_retention_tier=final_data_retention,
        idempotency_key=f"redeem_{card['id']}",
        grant_type="subscription",
        created_from="redeem_card",
        reference_id=str(card["id"]),
    )

    if not ok:
        logger.error(f"Redeem grant failed for {code}: {err}")
        raise HTTPException(status_code=500, detail="grant_failed_contact_support")

    upd_resp = (
        _safe_table("redeem_cards")
        .update(
            {
                "status": "redeemed",
                "redeemed_by": user_id,
                "redeemed_at": _utc_now_iso(),
            }
        )
        .eq("id", card["id"])
        .eq("status", "active")
        .execute()
    )
    if not getattr(upd_resp, "data", None):
        raise HTTPException(status_code=409, detail="race_condition_redeem_failed")

    return RedeemResponse(ok=True, granted_bt=bt_amount, granted_coupons=coupon_amount)


@router.get("/redemptions")
def list_my_redemptions(
    limit: int = 20,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    user_id = require_user_id(authorization=authorization, x_user_id=x_user_id)
    resp = (
        _safe_table("redeem_cards")
        .select("*")
        .eq("redeemed_by", user_id)
        .order("redeemed_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"items": getattr(resp, "data", [])}
