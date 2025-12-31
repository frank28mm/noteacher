import asyncio
import logging
import os
import sys
import time
import uuid
from homework_agent.utils.supabase_client import get_storage_client

def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("test_narrative")
    
    user_id = "dev_user"
    client = get_storage_client().client
    
    # 1. Create Report Job
    job_id = str(uuid.uuid4())
    logger.info(f"Inserting report job {job_id} for user {user_id}")
    
    res = client.table("report_jobs").insert({
        "id": job_id,
        "user_id": user_id,
        "status": "pending",
        "params": {"window_days": 30}
    }).execute()
    
    logger.info("Job inserted. Please run report_worker now (or ensure it is running).")
    logger.info("Waiting for job to complete...")
    
    # 2. Poll for completion
    timeout = 120
    start = time.time()
    while time.time() - start < timeout:
        res = client.table("report_jobs").select("*").eq("id", job_id).execute()
        rows = res.data
        if not rows:
            logger.warning("Job not found!")
            break
        
        job = rows[0]
        status = job.get("status")
        logger.info(f"Job Status: {status}")
        
        if status == "done":
            report_id = job.get("report_id")
            logger.info(f"Job Done! Report ID: {report_id}")
            
            # 3. Verify Report
            rep_res = client.table("reports").select("*").eq("report_id", report_id).execute()
            if rep_res.data:
                rep = rep_res.data[0]
                has_narrative = bool(rep.get("narrative_md"))
                has_json = bool(rep.get("narrative_json"))
                logger.info(f"Verification: Narrative MD present? {has_narrative}")
                logger.info(f"Verification: Narrative JSON present? {has_json}")
                if has_narrative:
                    print("\n--- Narrative Preview ---\n")
                    print(str(rep.get("narrative_md"))[:500] + "...")
                    print("\n-------------------------\n")
            else:
                logger.error("Report not found in table!")
            return
        elif status == "failed":
            logger.error(f"Job Failed: {job.get('error')}")
            return
            
        time.sleep(2)

    logger.error("Timeout waiting for job.")

if __name__ == "__main__":
    main()
