import asyncio
import os
import sys
from dotenv import load_dotenv
from supabase import create_client, Client

# Load env first
load_dotenv()

# Add root to sys.path
sys.path.append(os.getcwd())

EMAIL = "frank28mm@live.com"


async def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        print("❌ Error: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not found in env.")
        return

    supabase: Client = create_client(url, key)

    print(f"🗑️  Deleting user: {EMAIL} ...")

    user_id = None

    # 1. Find ID
    try:
        users = supabase.auth.admin.list_users(page=1, per_page=1000)
        for u in users:
            if u.email == EMAIL:
                user_id = u.id
                break
    except Exception as e:
        print(f"❌ Error listing users: {e}")
        return

    if not user_id:
        print("⚠️  User not found.")
        return

    print(f"ℹ️  Found User ID: {user_id}")

    # 2. Delete User (Cascades usually handle profiles, but maybe not)
    try:
        supabase.auth.admin.delete_user(user_id)
        print("✅ User deleted from Auth.")
    except Exception as e:
        print(f"❌ Failed to delete auth user: {e}")

    # 3. Cleanup Profile (Manual cleanup if cascade didn't work)
    try:
        res = supabase.table("child_profiles").delete().eq("user_id", user_id).execute()
        if res.data:
            print(f"✅ Deleted {len(res.data)} child_profile records.")
        else:
            print("ℹ️  No child_profile records found (or already deleted).")
    except Exception as e:
        # Ignore if table not found or other error
        print(f"⚠️  Profile cleanup note: {e}")

    print("\n🎉 Account deleted successfully.")


if __name__ == "__main__":
    asyncio.run(main())
