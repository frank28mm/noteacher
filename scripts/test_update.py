import os
import uuid
import logging
from homework_agent.utils.env import load_project_dotenv
from homework_agent.utils.supabase_client import get_storage_client

def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("test_update")
    load_project_dotenv()
    
    client = get_storage_client().client
    
    # Insert dummy
    job_id = str(uuid.uuid4())
    logger.info(f"Inserting {job_id}")
    client.table("report_jobs").insert({
        "id": job_id,
        "user_id": "test_update_user",
        "status": "pending"
    }).execute()
    
    # Try update
    logger.info("Attempting update...")
    try:
        resp = client.table("report_jobs").update({"status": "running"}).eq("id", job_id).execute()
        # Verify
        verify = client.table("report_jobs").select("*").eq("id", job_id).execute()
        data = verify.data
        if data and data[0]["status"] == "running":
             logger.info("Update SUCCESS (Verified)")
        else:
             logger.error(f"Update FAILED. Status: {data[0]['status'] if data else 'None'}")
    except Exception as e:
        logger.error(f"Update EXCEPTION: {e}")

if __name__ == "__main__":
    main()
