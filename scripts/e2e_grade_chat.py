#!/usr/bin/env python3
"""
Minimal E2E regression:
  1) /grade with one image (URL or local file upload to Supabase)
  2) /chat with "讲讲第XX题" using returned session_id

Usage:
  source .venv/bin/activate
  export PYTHONPATH=/path/to/project
  python scripts/e2e_grade_chat.py --image-url https://...jpg

Or:
  python scripts/e2e_grade_chat.py --image-file /path/to/IMG.jpg
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from typing import Any, Optional

import httpx
from dotenv import load_dotenv


def _pick_question_number(grade_resp: dict[str, Any]) -> Optional[str]:
    wrong_items = grade_resp.get("wrong_items") or []
    for it in wrong_items:
        qn = it.get("question_number")
        if qn:
            return str(qn)
    vr = grade_resp.get("vision_raw_text") or ""
    m = re.search(r"第\\s*(\\d{1,3}(?:\\([^\\)]+\\))?(?:[①②③④⑤⑥⑦⑧⑨])?)\\s*题", str(vr))
    if m:
        return m.group(1)
    return None


def _build_headers(*, user_id: Optional[str], auth_token: Optional[str]) -> dict[str, str]:
    uid = (user_id or os.getenv("DEV_USER_ID") or "dev_user").strip() or "dev_user"
    token = (auth_token or os.getenv("DEMO_AUTH_TOKEN") or "").strip()
    headers: dict[str, str] = {"X-User-Id": uid}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _upload_file_to_backend(*, api_base: str, file_path: str, session_id: str, headers: dict[str, str]) -> dict[str, Any]:
    if not file_path or not os.path.exists(file_path):
        raise ValueError(f"file not found: {file_path}")
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        files = {"file": (filename, f, "application/octet-stream")}
        with httpx.Client(timeout=120.0) as http:
            r = http.post(f"{api_base}/uploads", files=files, params={"session_id": session_id}, headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"/uploads failed {r.status_code}: {r.text[:400]}")
    data = r.json()
    if not isinstance(data, dict) or not data.get("upload_id"):
        raise RuntimeError(f"/uploads returned unexpected body: {data}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--subject", default="math", choices=["math", "english"])
    parser.add_argument("--vision-provider", default="doubao", choices=["doubao", "qwen3"])
    parser.add_argument("--image-url")
    parser.add_argument("--image-file")
    parser.add_argument("--user-id", default=None, help="Dev fallback (X-User-Id). Defaults to DEV_USER_ID.")
    parser.add_argument("--auth-token", default=None, help="Bearer token (Supabase JWT). Defaults to DEMO_AUTH_TOKEN.")
    parser.add_argument("--ask", default=None, help="Override chat question")
    args = parser.parse_args()

    if not args.image_url and not args.image_file:
        print("Must provide --image-url or --image-file", file=sys.stderr)
        return 2

    # Load env so Supabase upload works when using --image-file
    load_dotenv(".env")

    headers = _build_headers(user_id=args.user_id, auth_token=args.auth_token)

    session_id = f"e2e_{uuid.uuid4().hex[:8]}"
    upload_id: Optional[str] = None
    image_url = args.image_url
    if args.image_file:
        up = _upload_file_to_backend(api_base=args.api_base, file_path=args.image_file, session_id=session_id, headers=headers)
        upload_id = str(up.get("upload_id"))
        urls = up.get("page_image_urls") or []
        if isinstance(urls, list) and urls and not image_url:
            image_url = str(urls[0])

    grade_payload: dict[str, Any] = {
        "images": [],
        "upload_id": upload_id,
        "subject": args.subject,
        "session_id": session_id,
        "vision_provider": args.vision_provider,
    }
    if not upload_id:
        if not image_url:
            print("Must provide --image-url or --image-file", file=sys.stderr)
            return 2
        grade_payload["images"] = [{"url": image_url}]

    print(f"[E2E] /grade session_id={session_id}")
    with httpx.Client(timeout=900.0) as http:
        grade = http.post(f"{args.api_base}/grade", json=grade_payload, headers=headers)
        print("[E2E] grade status:", grade.status_code)
        if grade.status_code != 200:
            print(grade.text[:800], file=sys.stderr)
            return 1
        grade_resp = grade.json()

    status = grade_resp.get("status")
    if status != "done":
        print("[E2E] grade failed:", grade_resp.get("summary"), file=sys.stderr)
        print("[E2E] warnings:", grade_resp.get("warnings"), file=sys.stderr)
        return 1

    if not (grade_resp.get("vision_raw_text") or ""):
        print("[E2E] vision_raw_text missing", file=sys.stderr)
        return 1

    qn = _pick_question_number(grade_resp) or "1"
    question = args.ask or f"讲讲第{qn}题"
    chat_payload = {
        "history": [],
        "question": question,
        "subject": args.subject,
        "session_id": grade_resp.get("session_id") or session_id,
        "context_item_ids": [],
    }

    print(f"[E2E] /chat question={question}")
    with httpx.Client(timeout=180.0) as http:
        chat = http.post(f"{args.api_base}/chat", json=chat_payload, headers=headers)
        print("[E2E] chat status:", chat.status_code)
        if chat.status_code != 200:
            print(chat.text[:800], file=sys.stderr)
            return 1
        text = chat.text

    # Parse SSE: last assistant content from chat events
    last_assistant = ""
    current_event = ""
    for line in text.split("\n"):
        line = line.strip("\r")
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and current_event == "chat":
            data = line.split(":", 1)[1].strip()
            if not data:
                continue
            try:
                obj = json.loads(data)
            except Exception:
                continue
            msgs = obj.get("messages") or []
            for m in reversed(msgs):
                if m.get("role") == "assistant":
                    last_assistant = m.get("content") or ""
                    break

    if not last_assistant.strip():
        print("[E2E] chat assistant content missing", file=sys.stderr)
        return 1

    print("[E2E] OK. assistant_preview:", last_assistant[:160].replace("\n", " "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
