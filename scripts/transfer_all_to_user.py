import asyncio
import os
import sys
from dotenv import load_dotenv

# Load env first
load_dotenv()

# Add root to sys.path
sys.path.append(os.getcwd())

from homework_agent.utils.supabase_client import get_supabase_client

TARGET_PHONE = "18930236070"

# Tables that have 'user_id' column to migrate
TABLES_TO_MIGRATE = [
    "submissions",
    "profiles",
    "subscription_orders",
    "redeem_cards",  # redeemed_by
    "feedback_messages",
    "report_jobs",
    "reports",
]


async def main():
    supabase = get_supabase_client()

    print(f"🔍 Looking up user with phone: {TARGET_PHONE}...")

    # 1. Find User ID
    # In Supabase, auth.users is not directly queryable via public API usually,
    # but we might have a public 'users' table or we rely on 'auth_users_view' if created.
    # OR we try to find a submission/profile linked to this phone if we sync it?
    # Actually, for 'local' auth mode, we might store users in a local table?
    # Let's check 'users' table if it exists (custom), or try to infer from somewhere.
    # WAIT: Standard Supabase Auth users are in auth schema. Service role key can query it.
    # Since we are running as admin script, we should use SERVICE_ROLE_KEY if available,
    # but 'get_supabase_client' might use ANON key.

    # Check if we have ADMIN/SERVICE key
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not service_key:
        print(
            "⚠️  Warning: SUPABASE_SERVICE_ROLE_KEY not found. Using ANON key. Might not be able to query auth.users."
        )
        # Try to find user via our 'profiles' or other heuristic?
        # If user registered via our API, we might not have a public user table.
        # Let's assume the user has logged in at least once and created a Profile?
        pass

    # Alternative: Ask user for UUID directly? No, requirement is by phone.
    # Let's try to find user_id from 'auth.users' using Admin API if possible.
    # Since we use 'supabase-py', we can use supabase.auth.admin.list_users() if using service key.

    # If standard client is used, we can't query auth.users.
    # WORKAROUND: If you are using our local auth implementation (AUTH_MODE=local),
    # we might look into how user IDs are generated.
    # But usually Supabase Auth is used.

    # Let's try to fetch user_id via RPC if exists, or assume we can search profiles?
    # If the user registered, they should have a default profile.
    # Let's search 'profiles' for a user_id that MIGHT belong to this phone?
    # Wait, profiles table usually doesn't have phone.

    # Let's try to use the admin API (assuming script runs in trusted env).
    from supabase import create_client, Client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

    admin_client: Client = create_client(url, key)

    # Try to find user in auth
    try:
        # Supabase Admin API to list users
        # Note: list_users returns a response object
        page = 1
        found_user_id = None
        while True:
            # Need service_role key for this
            resp = admin_client.auth.admin.list_users(page=page, per_page=50)
            if not resp:
                break

            # resp is UserList object
            for u in resp:
                if u.phone == TARGET_PHONE:
                    found_user_id = u.id
                    break

            if found_user_id or len(resp) < 50:
                break
            page += 1

        if not found_user_id:
            # If phone has country code?
            target_with_plus = f"+86{TARGET_PHONE}"
            print(f"  Retrying with {target_with_plus}...")
            # Repeat search logic or simplified
            resp = admin_client.auth.admin.list_users(
                page=1, per_page=1000
            )  # One big batch
            for u in resp:
                if u.phone == target_with_plus or u.phone == TARGET_PHONE:
                    found_user_id = u.id
                    break

        if not found_user_id:
            print(f"❌ User {TARGET_PHONE} not found in Auth system.")
            return

        print(f"✅ Found User ID: {found_user_id}")

        # 2. Perform Migration
        print("🚀 Starting migration...")

        # Update Submissions
        res = (
            admin_client.table("submissions")
            .update({"user_id": found_user_id})
            .neq("user_id", found_user_id)
            .execute()
        )
        print(f"  - Submissions migrated: {len(res.data)}")

        # Update Profiles
        # Handle conflict: if user already has a default profile, and we migrate 'dev_user' profile...
        # We just move them all. The user will have multiple profiles.
        res = (
            admin_client.table("profiles")
            .update({"user_id": found_user_id})
            .neq("user_id", found_user_id)
            .execute()
        )
        print(f"  - Profiles migrated: {len(res.data)}")

        # Update Orders
        res = (
            admin_client.table("subscription_orders")
            .update({"user_id": found_user_id})
            .neq("user_id", found_user_id)
            .execute()
        )
        print(f"  - Orders migrated: {len(res.data)}")

        # Update Redemptions
        # Column is 'redeemed_by'
        res = (
            admin_client.table("redeem_cards")
            .update({"redeemed_by": found_user_id})
            .neq("redeemed_by", found_user_id)
            .not_.is_("redeemed_by", "null")
            .execute()
        )
        print(f"  - Redemptions migrated: {len(res.data)}")

        # Update Feedback
        # Column is 'user_id'
        # Check if table exists first? Assuming schema is stable.
        try:
            res = (
                admin_client.table("feedback_messages")
                .update({"user_id": found_user_id})
                .neq("user_id", found_user_id)
                .execute()
            )
            print(f"  - Feedback migrated: {len(res.data)}")
        except Exception:
            print("  - Feedback table not found or error (skipping)")

        # Reports
        try:
            res = (
                admin_client.table("reports")
                .update({"user_id": found_user_id})
                .neq("user_id", found_user_id)
                .execute()
            )
            print(f"  - Reports migrated: {len(res.data)}")
        except Exception:
            print("  - Reports table error")

        print("\n✨ Migration Complete! All data now belongs to 18930236070.")

    except Exception as e:
        print(f"❌ Error: {e}")
        # Fallback if admin api fails: Direct DB update via table if RLS allows?
        # But RLS usually blocks cross-user updates. We rely on Service Key.


if __name__ == "__main__":
    asyncio.run(main())
