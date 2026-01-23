"""
BT 额度过期检测 Worker

运行方式：
1. K8s CronJob（推荐）：每日 02:00 运行
2. 或手动运行：python -m homework_agent.workers.expiry_worker
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

from homework_agent.utils.supabase_client import get_worker_storage_client
from homework_agent.utils.observability import log_event

logger = logging.getLogger(__name__)


def _safe_table(name: str):
    storage = get_worker_storage_client()
    return storage.client.table(name)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def find_expired_grants(*, limit: int = 1000) -> List[Dict[str, Any]]:
    now = _utc_now().isoformat()

    resp = (
        _safe_table("bt_grants")
        .select("*")
        .lt("expires_at", now)
        .eq("is_expired", False)
        .order("expires_at", desc=False)
        .limit(limit)
        .execute()
    )

    return getattr(resp, "data", [])


def process_expired_grant(grant: Dict[str, Any]) -> bool:
    user_id = grant.get("user_id")
    grant_id = grant.get("id")
    bt_amount = int(grant.get("bt_amount", 0))

    if not user_id or not grant_id:
        return False

    try:
        now = _utc_now().isoformat()

        wallet_resp = (
            _safe_table("user_wallets")
            .select("*")
            .eq("user_id", user_id)
            .single()
            .execute()
        )

        wallet = getattr(wallet_resp, "data", None)
        if not wallet:
            logger.warning(f"Wallet not found for user {user_id}")
            return False

        current_active = int(wallet.get("bt_subscription_active", 0))
        current_expired = int(wallet.get("bt_subscription_expired", 0))

        new_active = max(0, current_active - bt_amount)
        new_expired = current_expired + bt_amount

        (
            _safe_table("user_wallets")
            .update(
                {
                    "bt_subscription_active": new_active,
                    "bt_subscription_expired": new_expired,
                    "last_expiry_check_at": now,
                    "updated_at": now,
                }
            )
            .eq("user_id", user_id)
            .execute()
        )

        (
            _safe_table("bt_grants")
            .update(
                {
                    "is_expired": True,
                    "processed_at": now,
                }
            )
            .eq("id", grant_id)
            .execute()
        )

        ledger_payload = {
            "user_id": user_id,
            "endpoint": "expiry_worker",
            "stage": "expire",
            "bt_delta": -bt_amount,
            "bt_subscription_delta": -bt_amount,
            "meta": {
                "grant_id": grant_id,
                "grant_type": grant.get("grant_type"),
                "created_from": grant.get("created_from"),
                "reference_id": grant.get("reference_id"),
                "expires_at": grant.get("expires_at"),
                "reason": "bt_quota_expired_after_30_days",
            },
        }

        try:
            _safe_table("usage_ledger").insert(ledger_payload).execute()
        except Exception as e:
            logger.warning(f"Failed to write ledger for {user_id}: {e}")

        log_event(
            logger,
            "bt_grant_expired",
            user_id=user_id,
            grant_id=grant_id,
            bt_amount=bt_amount,
            new_active=new_active,
            new_expired=new_expired,
        )

        return True

    except Exception as e:
        logger.exception(f"Failed to process expired grant {grant_id}: {e}")
        return False


def run_expiry_check(
    *, batch_size: int = 1000, max_batches: int = 100
) -> Dict[str, int]:
    stats = {
        "total_processed": 0,
        "total_expired": 0,
        "total_failed": 0,
        "batches_processed": 0,
    }

    log_event(logger, "expiry_check_started")

    while stats["batches_processed"] < max_batches:
        expired_grants = find_expired_grants(limit=batch_size)

        if not expired_grants:
            break

        stats["batches_processed"] += 1

        for grant in expired_grants:
            stats["total_processed"] += 1

            if process_expired_grant(grant):
                stats["total_expired"] += int(grant.get("bt_amount", 0))
            else:
                stats["total_failed"] += 1

        if len(expired_grants) < batch_size:
            break

    log_event(logger, "expiry_check_completed", **stats)

    return stats


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    stats = run_expiry_check()

    print(f"\n=== BT 额度过期检测完成 ===")
    print(f"处理记录数: {stats['total_processed']}")
    print(f"过期额度: {stats['total_expired']} BT")
    print(f"失败数: {stats['total_failed']}")
    print(f"批次: {stats['batches_processed']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
