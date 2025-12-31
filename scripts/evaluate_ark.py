import os
import sys
import time
import requests
import json
import argparse

API_BASE = "http://127.0.0.1:8000/api/v1"
# Use a challenging image if possible (e.g. rotated or small)
# For now, we use the same generic test image unless specific one provided
IMAGE_PATH = "test_image.jpg" 

def run_test(enable_process: bool):
    print(f"\n[Testing Ark Image Process: {'ENABLED' if enable_process else 'DISABLED'}]")
    
    # 1. Upload
    print(f"Uploading {IMAGE_PATH}...")
    try:
        with open(IMAGE_PATH, "rb") as f:
            files = {"file": ("test_image.jpg", f, "image/jpeg")}
            r = requests.post(f"{API_BASE}/uploads", files=files)
            if r.status_code != 200:
                print(f"Upload failed: {r.text}")
                return
            upload_resp = r.json()
            upload_id = upload_resp["upload_id"]
            img_url = upload_resp["page_image_urls"][0]
            print(f"Uploaded. ID: {upload_id}")
    except Exception as e:
        print(f"Upload Exception: {e}")
        return

    # 2. Grade
    # Control Ark image process via Header (if supported) or we rely on Env var changes between runs.
    # User's env.example shows ARK_IMAGE_PROCESS_ENABLED is an env var.
    # So this script assumes the SERVER env is set correctly before running.
    # However, to automate this script, we might need a header override?
    # Checking settings.py... "ark_image_process_enabled" is in Settings.
    # It doesn't seem to have a header override in grade.py (checked code: it reads `ctx.meta_base["ark_image_process_enabled"] = bool(getattr(ctx.settings, ...))`).
    # BUT, we can use the T3/T4 context: T4 task says "support toggle via switch".
    # Wait, T0 said "New env: ARK_IMAGE_PROCESS_ENABLED".
    # If the server supports hot-reload or we assume manual restart, we can't automate fully in one script without header support.
    # Let's check if there's a header for generic settings override? Unlikely in prod logic.
    # Workaround: The user asked to "Evaluate". I can provide a script that assumes the env is set.
    
    payload = {
        "images": [{"url": img_url}],
        "subject": "math",
        "vision_provider": "doubao",
        "upload_id": upload_id
    }
    
    print(f"Requesting /grade...")
    start = time.time()
    try:
        r = requests.post(f"{API_BASE}/grade", json=payload)
        elapsed = time.time() - start
        
        if r.status_code == 200:
            resp = r.json()
            # Analyze correctness or confidence
            status = resp.get("status")
            wrong = resp.get("wrong_count")
            warnings = resp.get("warnings")
            print(f"Done. Status: {status}, Wrong: {wrong}, Warnings: {warnings}")
            print(f"Elapsed: {elapsed:.2f}s")
            # We want to see if detailed extraction is better.
            # Maybe check 'questions' length or specific item correctness if we had ground truth.
            questions = resp.get("questions") or []
            print(f"Detected Questions: {len(questions)}")
        else:
            print(f"Failed: {r.status_code} {r.text}")
    except Exception as e:
         print(f"Grade Exception: {e}")

if __name__ == "__main__":
    # Usage: python evaluate_ark.py --enabled 1
    # This script actually just runs the grade call. The ENV control is external.
    run_test(True)
