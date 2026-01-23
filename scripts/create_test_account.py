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
PASSWORD = "12345678Y"  # Plain text for registration
HUGE_QUOTA = 999999999


async def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        print("❌ Error: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not found in env.")
        print(
            "   Please check your .env file. Service Role Key is required for admin actions."
        )
        return

    supabase: Client = create_client(url, key)

    print(f"🚀 Creating/Updating test account: {EMAIL}")

    # HARDCODED ID from previous run (to bypass creation error)
    user_id = "e4b6dc22-679f-4f8e-b1c0-fee9cebd62e9"
    print(f"ℹ️  Using existing User ID: {user_id}")

    # 2. Check/Create Profile

    # Usually profile is created via trigger, but we can force it or update it
    print("🔧 Updating Profile quotas (Table: child_profiles)...")

    # Check if profile exists
    res = supabase.table("child_profiles").select("*").eq("user_id", user_id).execute()
    profile_exists = len(res.data) > 0

    updates = {
        "user_id": user_id,  # Ensure link
        "display_name": "TestAdmin",
        "cp_left": HUGE_QUOTA,
        "report_coupons_left": HUGE_QUOTA,
        "is_default": True,  # Important for first profile
    }

    try:
        if profile_exists:
            supabase.table("child_profiles").update(updates).eq(
                "user_id", user_id
            ).execute()
            print("✅ Child Profile updated with INFINITE QUOTA.")
        else:
            supabase.table("child_profiles").insert(updates).execute()
            print("✅ Child Profile created with INFINITE QUOTA.")

    except Exception as e:
        print(f"❌ Failed to update profile: {e}")
        # Fallback: maybe column names differ?

    print("\n🎉 Done! You can now login with:")
    print(f"   Email: {EMAIL}")
    print(f"   Pass : {PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
