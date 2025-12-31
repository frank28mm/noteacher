import os
import sys
import time
import requests
import json

API_BASE = "http://127.0.0.1:8000/api/v1"
IMAGE_PATH = "test_image.jpg"

def run_grade(variant):
    print(f"\n[Testing Variant: {variant}]")
    
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
            print(f"Uploaded. ID: {upload_id}, URL: {img_url}")
    except Exception as e:
        print(f"Upload Exception: {e}")
        return

    # 2. Grade
    # Support overriding variant via header as per user description
    headers = {"X-Grade-Image-Input-Variant": variant}
    payload = {
        "images": [{"url": img_url}],
        "subject": "math",
        "vision_provider": "doubao",
        "upload_id": upload_id # associating upload_id
    }
    
    print(f"Requesting /grade with variant={variant}...")
    start = time.time()
    try:
        r = requests.post(f"{API_BASE}/grade", json=payload, headers=headers)
        elapsed = time.time() - start
        
        if r.status_code == 200:
            resp = r.json()
            status = resp.get("status")
            summary = str(resp.get("summary"))[:50]
            timings = resp.get("timings_ms", {}) # Assuming response might return timings, or we check logs
            print(f"Done. Status: {status}")
            print(f"Summary: {summary}...")
            print(f"Client Elapsed: {elapsed:.2f}s")
        else:
            print(f"Failed: {r.status_code} {r.text}")
    except Exception as e:
         print(f"Grade Exception: {e}")

if __name__ == "__main__":
    variants = ["url", "proxy", "data_url_first_page"]
    if len(sys.argv) > 1:
        variants = sys.argv[1:]
    
    for v in variants:
        run_grade(v)
        time.sleep(2)
