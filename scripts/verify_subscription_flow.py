import asyncio
import uuid
import logging
import os
from datetime import datetime, timezone

from homework_agent.services.quota_service import _safe_table, load_wallet, CP_BT
# We need to test the API logic, but we can't easily spin up the full FastAPI app in a script without uvicorn.
# So we'll test the service logic directly, and then try to insert into subscription_orders to check DB state.

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_flow():
    user_id = f"test_sub_{uuid.uuid4().hex[:8]}"

    # 1. Create User
    try:
        _safe_table("users").insert(
            {
                "user_id": user_id,
                "phone": f"188{uuid.uuid4().int % 100000000:08d}",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
        logger.info(f"Created user: {user_id}")
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        return

    # 2. Check if subscription_orders table exists
    try:
        _safe_table("subscription_orders").select("id").limit(1).execute()
        logger.info("✅ Table 'subscription_orders' exists.")
    except Exception as e:
        logger.error(f"❌ Table 'subscription_orders' MISSING or inaccessible: {e}")
        logger.warning(
            "⚠️ Please run the SQL in supabase/schema.sql to create the table!"
        )
        # We can't proceed with full flow if table is missing, but we can test the grant logic.

    # 3. Test Grant Logic (Directly calling service function)
    from homework_agent.services.quota_service import grant_subscription_quota

    # Grant S2 (1000 CP + 4 coupons)
    bt_amount = 1000 * CP_BT
    coupons = 4

    logger.info("Testing grant_subscription_quota...")
    ok, err = grant_subscription_quota(
        user_id=user_id,
        bt_amount=bt_amount,
        coupon_amount=coupons,
        plan_tier="S2",
        data_retention_tier="12m",
        idempotency_key=f"test_grant_{uuid.uuid4()}",
    )

    if ok:
        logger.info("✅ Grant successful.")
        wallet = load_wallet(user_id=user_id)
        logger.info(
            f"Wallet after grant: CP={wallet.cp_left}, Coupons={wallet.report_coupons}, Tier={wallet.plan_tier}"
        )
        if wallet.plan_tier == "S2" and wallet.cp_left >= 1000:
            logger.info("✅ Verification passed: Wallet updated correctly.")
        else:
            logger.error("❌ Verification failed: Wallet state incorrect.")
    else:
        logger.error(f"❌ Grant failed: {err}")

    # Cleanup
    logger.info("Cleaning up...")
    try:
        _safe_table("user_wallets").delete().eq("user_id", user_id).execute()
        _safe_table("usage_ledger").delete().eq("user_id", user_id).execute()
        _safe_table("users").delete().eq("user_id", user_id).execute()
        # Also clean orders if we created any (we didn't yet)
    except:
        pass


if __name__ == "__main__":
    asyncio.run(test_flow())
