import asyncio
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any

from homework_agent.utils.supabase_client import get_worker_storage_client
from homework_agent.services.quota_service import (
    load_wallet,
    charge_bt_spendable,
    _safe_table,
    CP_BT,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEST_USER_ID = f"test_user_{uuid.uuid4().hex[:8]}"


async def setup_test_wallet(user_id: str):
    """Create a test wallet with initial balance."""
    logger.info(f"Setting up test wallet for user: {user_id}")

    # Ensure user exists in users table (foreign key constraint)
    try:
        _safe_table("users").insert(
            {
                "user_id": user_id,
                "phone": f"199{uuid.uuid4().int % 100000000:08d}",  # random phone
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
        logger.info(f"Created test user: {user_id}")
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        return False

    initial_bt = 10 * CP_BT  # 10 CP

    try:
        # Create wallet with 10 CP trial
        _safe_table("user_wallets").insert(
            {
                "user_id": user_id,
                "bt_trial": initial_bt,
                "bt_subscription": 0,
                "report_coupons": 0,
                "plan_tier": "S1",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
        logger.info(f"Created wallet with {initial_bt} BT ({initial_bt // CP_BT} CP)")
        return True
    except Exception as e:
        logger.error(f"Failed to setup wallet: {e}")
        return False


async def verify_deduction(user_id: str):
    """Perform a deduction and verify the result."""

    # 1. Check initial balance
    wallet_before = load_wallet(user_id=user_id)
    if not wallet_before:
        logger.error("Wallet not found after setup")
        return False

    initial_cp = wallet_before.cp_left
    logger.info(f"Initial Balance: {wallet_before.bt_spendable} BT ({initial_cp} CP)")

    # 2. Charge 1 CP (CP_BT)
    charge_amount = CP_BT
    request_id = f"req_{uuid.uuid4().hex}"

    logger.info(f"Charging {charge_amount} BT...")
    ok, err = charge_bt_spendable(
        user_id=user_id,
        bt_cost=charge_amount,
        idempotency_key=request_id,
        request_id=request_id,
        endpoint="test_script",
        stage="test",
        model="test-model",
        usage={"total_tokens": 100},
    )

    if not ok:
        logger.error(f"Charge failed: {err}")
        return False

    logger.info("Charge successful.")

    # 3. Check new balance
    wallet_after = load_wallet(user_id=user_id)
    new_cp = wallet_after.cp_left
    logger.info(f"New Balance: {wallet_after.bt_spendable} BT ({new_cp} CP)")

    # Verification
    expected_bt = wallet_before.bt_spendable - charge_amount
    if wallet_after.bt_spendable != expected_bt:
        logger.error(
            f"Balance mismatch! Expected {expected_bt}, got {wallet_after.bt_spendable}"
        )
        return False

    if new_cp != initial_cp - 1:
        logger.error(f"CP mismatch! Expected {initial_cp - 1}, got {new_cp}")
        return False

    logger.info("✅ Wallet balance verified.")

    # 4. Check Ledger
    logger.info("Verifying ledger entry...")
    resp = (
        _safe_table("usage_ledger")
        .select("*")
        .eq("idempotency_key", request_id)
        .execute()
    )
    rows = getattr(resp, "data", [])

    if not rows or len(rows) != 1:
        logger.error("Ledger entry not found or duplicated")
        return False

    entry = rows[0]

    # Check the actual value
    actual_delta = entry["bt_delta"]
    logger.info(f"Ledger bt_delta: {actual_delta}")

    if actual_delta != -charge_amount:
        logger.error(
            f"Ledger delta mismatch! Expected {-charge_amount}, got {actual_delta}"
        )
        return False

    logger.info("✅ Ledger entry verified.")
    return True


async def cleanup(user_id: str):
    """Cleanup test data."""
    logger.info("Cleaning up...")
    try:
        _safe_table("user_wallets").delete().eq("user_id", user_id).execute()
        _safe_table("usage_ledger").delete().eq("user_id", user_id).execute()
        _safe_table("users").delete().eq("user_id", user_id).execute()
        logger.info("Cleanup done.")
    except Exception as e:
        logger.warning(f"Cleanup failed: {e}")


async def main():
    try:
        if await setup_test_wallet(TEST_USER_ID):
            if await verify_deduction(TEST_USER_ID):
                logger.info("\n🎉 All verification passed!")
            else:
                logger.error("\n❌ Verification failed!")
        else:
            logger.error("\n❌ Setup failed!")
    finally:
        await cleanup(TEST_USER_ID)


if __name__ == "__main__":
    asyncio.run(main())
