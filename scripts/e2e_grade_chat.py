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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--subject", default="math", choices=["math", "english"])
    parser.add_argument("--vision-provider", default="doubao", choices=["doubao", "qwen3"])
    parser.add_argument("--image-url")
    parser.add_argument("--image-file")
    parser.add_argument("--ask", default=None, help="Override chat question")
    args = parser.parse_args()

    if not args.image_url and not args.image_file:
        print("Must provide --image-url or --image-file", file=sys.stderr)
        return 2

    # Load env so Supabase upload works when using --image-file
    load_dotenv(".env")

    image_url = args.image_url
    if args.image_file:
        from homework_agent.utils.supabase_client import get_storage_client

        client = get_storage_client()
        urls = client.upload_files(args.image_file, prefix="e2e/", min_side=14)
        image_url = urls[0]

    assert image_url
    session_id = f"e2e_{uuid.uuid4().hex[:8]}"
    grade_payload = {
        "images": [{"url": image_url}],
        "subject": args.subject,
        "session_id": session_id,
        "vision_provider": args.vision_provider,
    }

    print(f"[E2E] /grade session_id={session_id}")
    with httpx.Client(timeout=900.0) as http:
        grade = http.post(f"{args.api_base}/grade", json=grade_payload)
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
        chat = http.post(f"{args.api_base}/chat", json=chat_payload)
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

