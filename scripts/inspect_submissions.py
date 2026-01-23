import asyncio
import os
import sys
from dotenv import load_dotenv
from supabase import create_client, Client

# Load env first
load_dotenv()

# Add root to sys.path
sys.path.append(os.getcwd())

IDS = ["cc4ea4", "504dfa"]


async def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("❌ Error: Supabase credentials missing.")
        return

    supabase: Client = create_client(url, key)

    print(f"🔍 Inspecting Submissions: {IDS}")

    for short_id in IDS:
        print(f"\n--- Checking ID: {short_id} ---")

        # Try to find in submissions (upload_id) or jobs
        # 1. Search submissions by upload_id
        res = (
            supabase.table("submissions")
            .select("*")
            .ilike("submission_id", f"%{short_id}%")
            .execute()
        )
        data = res.data

        if not data:
            print("  (Not found in submissions, checking jobs...)")
            # 2. Search jobs
            res = (
                supabase.table("grade_jobs")
                .select("*")
                .ilike("job_id", f"%{short_id}%")
                .execute()
            )
            if res.data:
                job = res.data[0]
                print(f"  ✅ Found Job: {job['job_id']}")
                upload_id = job.get("upload_id")
                if upload_id:
                    res = (
                        supabase.table("submissions")
                        .select("*")
                        .eq("submission_id", upload_id)
                        .execute()
                    )
                    data = res.data

        if not data:
            print("  ❌ Not found.")
            continue

        sub = data[0]
        print(f"  ✅ Submission: {sub['submission_id']}")
        print(f"  Subject: {sub.get('subject')}")

        # Analyze wrong items
        wrong_items = sub.get("wrong_items") or []
        print(f"  Wrong Items: {len(wrong_items)}")

        for idx, item in enumerate(wrong_items):
            print(f"    [Item {idx + 1}]")
            print(f"      Question: {item.get('question_content', '')[:50]}...")
            print(f"      Reason: {item.get('reason')}")
            print(f"      Tags: {item.get('knowledge_tags')}")
            print(f"      Basis: {item.get('judgment_basis')}")


if __name__ == "__main__":
    asyncio.run(main())
