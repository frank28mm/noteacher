from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple

from homework_agent.utils.observability import log_event
from homework_agent.utils.settings import get_settings
from homework_agent.utils.supabase_client import get_worker_storage_client

logger = logging.getLogger(__name__)

BT_GRANT_EXPIRY_DAYS = 30


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_table(name: str):
    storage = get_worker_storage_client()
    return storage.client.table(name)


CP_BT: int = 12400
BT_OUTPUT_MULTIPLIER: int = 10


@dataclass(frozen=True)
class Wallet:
    user_id: str
    bt_trial: int
    bt_subscription: int
    bt_subscription_active: int
    bt_subscription_expired: int
    bt_report_reserve: int
    report_coupons: int
    trial_expires_at: Optional[str]
    plan_tier: Optional[str]
    data_retention_tier: Optional[str]

    @property
    def bt_spendable(self) -> int:
        active = (
            max(0, int(self.bt_subscription_active))
            if self.bt_subscription_active
            else int(self.bt_subscription)
        )
        return max(0, int(self.bt_trial) + active)

    @property
    def cp_left(self) -> int:
        return max(0, self.bt_spendable // CP_BT)


def bt_from_usage(*, prompt_tokens: int, completion_tokens: int) -> int:
    """
    WS-E frozen rule:
    BT = prompt_tokens + 10 * completion_tokens
    """
    p = max(0, int(prompt_tokens))
    c = max(0, int(completion_tokens))
    return int(p + BT_OUTPUT_MULTIPLIER * c)


def load_wallet(*, user_id: str) -> Optional[Wallet]:
    uid = str(user_id or "").strip()
    if not uid:
        return None
    try:
        resp = (
            _safe_table("user_wallets")
            .select(
                "user_id,bt_trial,bt_subscription,bt_subscription_active,bt_subscription_expired,bt_report_reserve,report_coupons,trial_expires_at,plan_tier,data_retention_tier"
            )
            .eq("user_id", uid)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None)
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return None
        row = rows[0]
        trial_expires_at = row.get("trial_expires_at")
        bt_trial = int(row.get("bt_trial") or 0)
        if trial_expires_at:
            try:
                expires = datetime.fromisoformat(
                    str(trial_expires_at).replace("Z", "+00:00")
                )
                if _utc_now() > expires:
                    bt_trial = 0
            except Exception:
                pass
        return Wallet(
            user_id=uid,
            bt_trial=bt_trial,
            bt_subscription=int(row.get("bt_subscription") or 0),
            bt_subscription_active=int(row.get("bt_subscription_active") or 0),
            bt_subscription_expired=int(row.get("bt_subscription_expired") or 0),
            bt_report_reserve=int(row.get("bt_report_reserve") or 0),
            report_coupons=int(row.get("report_coupons") or 0),
            trial_expires_at=str(trial_expires_at) if trial_expires_at else None,
            plan_tier=str(row.get("plan_tier") or "") or None,
            data_retention_tier=str(row.get("data_retention_tier") or "") or None,
        )
    except Exception:
        return None


def _apply_spend(
    *,
    user_id: str,
    bt_delta: int,
    from_pool: str,
    report_coupons_delta: int = 0,
    idempotency_key: Optional[str],
    request_id: Optional[str],
    endpoint: str,
    stage: str,
    model: Optional[str],
    usage: Optional[Dict[str, Any]],
) -> Tuple[bool, Optional[str]]:
    """
    Best-effort wallet update + ledger insert.
    Returns (ok, error_message?).

    Idempotency:
    - If idempotency_key is provided, we upsert ledger on (user_id,idempotency_key).
    - Wallet update is best-effort; in rare races it may double-spend. We'll harden this once we
      move to a DB with transactions (RDS).
    """
    uid = str(user_id or "").strip()
    if not uid:
        return False, "user_id is required"
    idem = str(idempotency_key or "").strip() or None

    # Idempotency guard: if we have already recorded this spend, do not charge again.
    # This prevents double-charging on client retries (e.g., X-Idempotency-Key or job reruns).
    if idem:
        try:
            existing = (
                _safe_table("usage_ledger")
                .select("id,user_id,idempotency_key")
                .eq("user_id", uid)
                .eq("idempotency_key", idem)
                .limit(1)
                .execute()
            )
            rows = getattr(existing, "data", None)
            if isinstance(rows, list) and rows:
                log_event(
                    logger,
                    "quota_idempotency_hit",
                    user_id=uid,
                    endpoint=endpoint,
                    stage=stage,
                    idempotency_key=idem,
                )
                return True, None
        except Exception:
            # Best-effort: if the ledger lookup fails, continue with charging (we'll still upsert).
            pass

    # 1) Load current wallet
    wallet = load_wallet(user_id=uid)
    if not wallet:
        return False, "wallet not found"

    bt_delta_i = int(bt_delta)
    rc_delta_i = int(report_coupons_delta)

    bt_trial_delta = 0
    bt_subscription_delta = 0
    bt_report_reserve_delta = 0

    # Spend semantics:
    # - grade/chat: consume bt_trial first, then bt_subscription (both are spendable)
    # - report: consumes report_coupons first, then bt_report_reserve (separate pool)
    if from_pool == "report_reserve":
        if rc_delta_i != 0:
            pass
        bt_report_reserve_delta = bt_delta_i
    else:
        # spendable pools
        remaining = bt_delta_i
        if remaining < 0:
            # negative means spend: allocate to trial then subscription
            spend = -remaining
            take_trial = min(spend, max(0, wallet.bt_trial))
            take_sub = max(0, spend - take_trial)
            bt_trial_delta = -take_trial
            bt_subscription_delta = -take_sub
        else:
            # positive grant
            bt_subscription_delta = remaining

    # 2) Update wallet
    try:
        update: Dict[str, Any] = {"updated_at": _utc_now().isoformat()}
        if bt_trial_delta:
            update["bt_trial"] = max(0, int(wallet.bt_trial) + int(bt_trial_delta))
        if bt_subscription_delta:
            update["bt_subscription"] = max(
                0, int(wallet.bt_subscription) + int(bt_subscription_delta)
            )
        if bt_report_reserve_delta:
            update["bt_report_reserve"] = max(
                0, int(wallet.bt_report_reserve) + int(bt_report_reserve_delta)
            )
        if rc_delta_i:
            update["report_coupons"] = max(
                0, int(wallet.report_coupons) + int(rc_delta_i)
            )
        _safe_table("user_wallets").update(update).eq("user_id", uid).execute()
    except Exception as e:
        return False, f"wallet update failed: {e}"

    # 3) Insert ledger (best-effort)
    try:
        payload: Dict[str, Any] = {
            "user_id": uid,
            "request_id": str(request_id or "") or None,
            "idempotency_key": idem,
            "endpoint": str(endpoint or ""),
            "stage": str(stage or ""),
            "model": str(model or "") or None,
            "prompt_tokens": int((usage or {}).get("prompt_tokens") or 0)
            if usage
            else None,
            "completion_tokens": int((usage or {}).get("completion_tokens") or 0)
            if usage
            else None,
            "total_tokens": int((usage or {}).get("total_tokens") or 0)
            if usage
            else None,
            "bt_delta": int(bt_delta_i),
            "bt_trial_delta": int(bt_trial_delta),
            "bt_subscription_delta": int(bt_subscription_delta),
            "bt_report_reserve_delta": int(bt_report_reserve_delta),
            "report_coupons_delta": int(rc_delta_i),
            "meta": {"usage": usage or {}},
        }
        if idem:
            _safe_table("usage_ledger").upsert(
                payload, on_conflict="user_id,idempotency_key"
            ).execute()
        else:
            _safe_table("usage_ledger").insert(payload).execute()
    except Exception:
        pass

    try:
        log_event(
            logger,
            "quota_ledger_written",
            user_id=uid,
            endpoint=endpoint,
            stage=stage,
            bt_delta=bt_delta_i,
            report_coupons_delta=rc_delta_i,
            idempotency_key=idem,
        )
    except Exception:
        pass

    return True, None


def can_afford_bt(*, user_id: str, bt_required: int) -> bool:
    wallet = load_wallet(user_id=user_id)
    if not wallet:
        return False
    return wallet.bt_spendable >= max(0, int(bt_required))


def can_use_report_coupon(*, user_id: str) -> bool:
    wallet = load_wallet(user_id=user_id)
    if not wallet:
        return False
    return int(wallet.report_coupons) > 0 and int(wallet.bt_report_reserve) > 0


def charge_bt_spendable(
    *,
    user_id: str,
    bt_cost: int,
    idempotency_key: Optional[str],
    request_id: Optional[str],
    endpoint: str,
    stage: str,
    model: Optional[str],
    usage: Optional[Dict[str, Any]],
) -> Tuple[bool, Optional[str]]:
    return _apply_spend(
        user_id=user_id,
        bt_delta=-abs(int(bt_cost)),
        from_pool="spendable",
        report_coupons_delta=0,
        idempotency_key=idempotency_key,
        request_id=request_id,
        endpoint=endpoint,
        stage=stage,
        model=model,
        usage=usage,
    )


def grant_subscription_quota(
    *,
    user_id: str,
    bt_amount: int,
    coupon_amount: int,
    plan_tier: str,
    data_retention_tier: str,
    idempotency_key: str,
    grant_type: str = "subscription",
    created_from: str = "redeem_card",
    reference_id: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    uid = str(user_id or "").strip()
    if not uid:
        return False, "user_id required"

    wallet = load_wallet(user_id=uid)
    now = _utc_now()
    now_iso = now.isoformat()
    expires_at = (now + timedelta(days=BT_GRANT_EXPIRY_DAYS)).isoformat()
    bt_amount_i = int(bt_amount)
    coupon_amount_i = int(coupon_amount)

    try:
        if wallet:
            _safe_table("user_wallets").update(
                {
                    "bt_subscription": int(wallet.bt_subscription) + bt_amount_i,
                    "bt_subscription_active": int(
                        getattr(wallet, "bt_subscription_active", 0) or 0
                    )
                    + bt_amount_i,
                    "report_coupons": int(wallet.report_coupons) + coupon_amount_i,
                    "plan_tier": plan_tier,
                    "data_retention_tier": data_retention_tier,
                    "updated_at": now_iso,
                }
            ).eq("user_id", uid).execute()
        else:
            _safe_table("user_wallets").insert(
                {
                    "user_id": uid,
                    "bt_trial": 0,
                    "bt_subscription": bt_amount_i,
                    "bt_subscription_active": bt_amount_i,
                    "bt_subscription_expired": 0,
                    "report_coupons": coupon_amount_i,
                    "plan_tier": plan_tier,
                    "data_retention_tier": data_retention_tier,
                    "updated_at": now_iso,
                }
            ).execute()

        if bt_amount_i > 0:
            _safe_table("bt_grants").insert(
                {
                    "user_id": uid,
                    "bt_amount": bt_amount_i,
                    "grant_type": grant_type,
                    "expires_at": expires_at,
                    "created_from": created_from,
                    "reference_id": reference_id,
                    "meta": {
                        "idempotency_key": idempotency_key,
                        "plan_tier": plan_tier,
                    },
                }
            ).execute()

        ledger_payload: Dict[str, Any] = {
            "user_id": uid,
            "idempotency_key": idempotency_key,
            "endpoint": "subscription",
            "stage": "grant",
            "bt_delta": bt_amount_i,
            "bt_subscription_delta": bt_amount_i,
            "report_coupons_delta": coupon_amount_i,
            "meta": {
                "plan_tier": plan_tier,
                "grant_type": grant_type,
                "expires_at": expires_at,
            },
        }
        try:
            _safe_table("usage_ledger").insert(ledger_payload).execute()
        except Exception:
            pass

        return True, None
    except Exception as e:
        logger.exception("grant_subscription_quota failed")
        return False, str(e)
