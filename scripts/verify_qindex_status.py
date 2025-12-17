#!/usr/bin/env python3
"""
Verify qindex delivery + TTL (Redis), with optional auto /grade run.

What this checks:
1) /api/v1/session/{session_id}/qbank meta (qindex_available / qindex_warnings / questions_count)
2) Redis keys:
   - qbank:{session_id}
   - qindex:{session_id}
   - grade_progress:{session_id}
   - sess:{session_id}
   and their TTLs.

Usage (manual, already have session_id):
  source .venv/bin/activate
  export PYTHONPATH=/path/to/project
  python scripts/verify_qindex_status.py --session-id demo_xxxxx

Usage (auto, run /grade to obtain session_id):
  python scripts/verify_qindex_status.py --image-url https://...jpg
  python scripts/verify_qindex_status.py --image-file /path/to/IMG.jpg

Optional:
  python scripts/verify_qindex_status.py --image-url https://...jpg --wait-seconds 120 --require-qindex
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, Optional, Tuple

import httpx
from dotenv import load_dotenv


def _json_loads_bytes(data: Any) -> Optional[Dict[str, Any]]:
    if not data:
        return None
    if isinstance(data, (bytes, bytearray)):
        s = data.decode("utf-8", errors="replace")
    else:
        s = str(data)
    s = s.strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _build_headers(*, user_id: Optional[str], auth_token: Optional[str]) -> Dict[str, str]:
    uid = (user_id or os.getenv("DEV_USER_ID") or "dev_user").strip() or "dev_user"
    token = (auth_token or os.getenv("DEMO_AUTH_TOKEN") or "").strip()
    headers: Dict[str, str] = {"X-User-Id": uid}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _upload_file_to_backend(*, api_base: str, file_path: str, session_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
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


def _redis_client():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return None
    client = redis.Redis.from_url(redis_url)
    client.ping()
    return client


def _ttl_str(ttl: int) -> str:
    if ttl == -2:
        return "missing"
    if ttl == -1:
        return "no-expire"
    if ttl >= 0:
        return f"{ttl}s"
    return str(ttl)


def _start_qindex_worker_if_requested(start: bool, *, log_path: str) -> Optional[subprocess.Popen]:
    if not start:
        return None
    try:
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        log_f = open(log_path, "ab", buffering=0)  # noqa: SIM115
    except Exception as e:
        print(f"[AUTO] cannot open worker log file: {e}", file=sys.stderr)
        return None

    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    # Make sure the worker can import homework_agent even if PYTHONPATH wasn't exported.
    # Prefer the current project root (cwd of the script execution).
    env.setdefault("PYTHONPATH", os.getcwd())

    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "homework_agent.workers.qindex_worker"],
            env=env,
            stdout=log_f,
            stderr=log_f,
        )
    except Exception as e:
        print(f"[AUTO] failed to start qindex worker: {e}", file=sys.stderr)
        try:
            log_f.close()
        except Exception:
            pass
        return None

    print(f"[AUTO] qindex worker started (pid={proc.pid}) log={log_path}")
    # Give the worker a moment to boot and connect to Redis.
    time.sleep(1.0)
    return proc


def _stop_worker(proc: Optional[subprocess.Popen]) -> None:
    if not proc:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5.0)
        return
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def _inspect_qindex_payload(payload: Dict[str, Any]) -> Tuple[int, int]:
    """
    Returns:
      (questions_count, slices_count)
    """
    index = payload.get("index")
    if isinstance(index, dict):
        q = index.get("questions")
    else:
        q = payload.get("questions")
    if not isinstance(q, dict):
        return (0, 0)
    questions_count = len(q)
    slices_count = 0
    for v in q.values():
        if not isinstance(v, dict):
            continue
        pages = v.get("pages")
        if not isinstance(pages, list):
            continue
        for p in pages:
            if not isinstance(p, dict):
                continue
            su = p.get("slice_image_urls")
            if isinstance(su, list):
                slices_count += len([x for x in su if x])
            elif isinstance(su, str) and su:
                slices_count += 1
    return (questions_count, slices_count)


def _run_grade_and_get_session_id(
    *,
    api_base: str,
    subject: str,
    vision_provider: str,
    image_url: Optional[str],
    image_file: Optional[str],
    session_id: Optional[str],
    headers: Dict[str, str],
) -> str:
    import uuid

    if not image_url and not image_file:
        raise ValueError("Must provide --image-url or --image-file when session_id is not provided")

    sid = (session_id or "").strip() or f"verify_{uuid.uuid4().hex[:8]}"
    resolved_url = image_url
    upload_id: Optional[str] = None
    if image_file:
        up = _upload_file_to_backend(api_base=api_base, file_path=image_file, session_id=sid, headers=headers)
        upload_id = str(up.get("upload_id"))
        urls = up.get("page_image_urls") or []
        if isinstance(urls, list) and urls and not resolved_url:
            resolved_url = str(urls[0])

    if not (upload_id or resolved_url):
        raise RuntimeError("Failed to resolve image input")

    payload: Dict[str, Any] = {
        "images": [],
        "upload_id": upload_id,
        "subject": subject,
        "session_id": sid,
        "vision_provider": vision_provider,
    }
    if not upload_id:
        payload["images"] = [{"url": resolved_url}]

    print(f"[AUTO] /grade session_id={sid} vision_provider={vision_provider} subject={subject}")
    with httpx.Client(timeout=900.0) as http:
        r = http.post(f"{api_base}/grade", json=payload, headers=headers)
        if r.status_code != 200:
            raise RuntimeError(f"/grade failed {r.status_code}: {r.text[:400]}")
        resp = r.json()

        # If the API offloaded to async job, poll it (best-effort).
        if resp.get("status") == "processing" and resp.get("job_id"):
            job_id = str(resp.get("job_id"))
            print(f"[AUTO] /grade offloaded to job_id={job_id}, polling /jobs/{job_id} ...")
            deadline = time.monotonic() + 300.0
            while time.monotonic() < deadline:
                jr = http.get(f"{api_base}/jobs/{job_id}", headers=headers)
                if jr.status_code != 200:
                    time.sleep(2.0)
                    continue
                job = jr.json()
                st = job.get("status")
                if st in {"done", "failed"}:
                    break
                time.sleep(2.0)
        return str(resp.get("session_id") or sid)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--subject", default="math", choices=["math", "english"])
    parser.add_argument("--vision-provider", default="doubao", choices=["doubao", "qwen3"])
    parser.add_argument("--session-id", default=None, help="If omitted, will run /grade when image is provided")
    parser.add_argument("--image-url", default=None, help="Run /grade first and use returned session_id")
    parser.add_argument("--image-file", default=None, help="Run /uploads then /grade with returned upload_id")
    parser.add_argument("--user-id", default=None, help="Dev fallback (X-User-Id). Defaults to DEV_USER_ID.")
    parser.add_argument("--auth-token", default=None, help="Bearer token (Supabase JWT). Defaults to DEMO_AUTH_TOKEN.")
    parser.add_argument("--start-worker", action="store_true", help="Start qindex worker locally for this run")
    parser.add_argument("--worker-log", default="logs/qindex_worker_verify.log", help="Worker log file path")
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--require-qindex", action="store_true")
    args = parser.parse_args()

    load_dotenv(".env")
    headers = _build_headers(user_id=args.user_id, auth_token=args.auth_token)

    worker_proc: Optional[subprocess.Popen] = None
    try:
        # Only start the worker when requested; it is normally a separate long-running process.
        worker_proc = _start_qindex_worker_if_requested(bool(args.start_worker), log_path=str(args.worker_log))

        session_id = str(args.session_id).strip() if args.session_id else ""
        if not session_id:
            try:
                session_id = _run_grade_and_get_session_id(
                    api_base=args.api_base,
                    subject=args.subject,
                    vision_provider=args.vision_provider,
                    image_url=args.image_url,
                    image_file=args.image_file,
                    session_id=None,
                    headers=headers,
                )
            except Exception as e:
                print(f"[AUTO] FAIL: {e}", file=sys.stderr)
                return 2

        # ---- 1) API meta ----
        api_meta: Dict[str, Any] = {}
        try:
            with httpx.Client(timeout=15.0) as http:
                r = http.get(f"{args.api_base}/session/{session_id}/qbank", headers=headers)
            if r.status_code == 200:
                api_meta = r.json()
            else:
                api_meta = {"error": f"{r.status_code}: {r.text[:200]}"}
        except Exception as e:
            api_meta = {"error": str(e)}

        print("[API] /session/{sid}/qbank meta:")
        for k in (
            "session_id",
            "subject",
            "questions_count",
            "questions_with_options",
            "vision_raw_len",
            "page_image_urls_count",
            "qindex_available",
            "qindex_warnings",
        ):
            if k in api_meta:
                print(f"  - {k}: {api_meta.get(k)}")
        if api_meta.get("error"):
            print(f"  - error: {api_meta.get('error')}")

        # ---- 2) Redis keys + TTL ----
        try:
            client = _redis_client()
        except Exception as e:
            print(f"[Redis] unavailable: {e}", file=sys.stderr)
            return 2
        if client is None:
            print("[Redis] REDIS_URL not set or redis package missing; cannot verify TTL.", file=sys.stderr)
            return 2

        prefix = os.getenv("CACHE_PREFIX", "")
        keys = {
            "sess": f"{prefix}sess:{session_id}",
            "qbank": f"{prefix}qbank:{session_id}",
            "qindex": f"{prefix}qindex:{session_id}",
            "progress": f"{prefix}grade_progress:{session_id}",
        }

        def _read_key(name: str) -> Tuple[int, Optional[Dict[str, Any]]]:
            key = keys[name]
            ttl = int(client.ttl(key))
            raw = client.get(key)
            obj = _json_loads_bytes(raw)
            return ttl, obj

        # Wait for qindex if requested.
        started = time.monotonic()
        qindex_ttl, qindex_obj = _read_key("qindex")
        while args.wait_seconds > 0 and (time.monotonic() - started) < float(args.wait_seconds):
            # consider "ready" when index has at least one question entry
            qc, _sc = _inspect_qindex_payload(qindex_obj or {})
            if qc > 0:
                break
            time.sleep(args.poll_interval)
            qindex_ttl, qindex_obj = _read_key("qindex")

        print("[Redis] keys + TTL:")
        results: Dict[str, Any] = {}
        for name in ("sess", "qbank", "qindex", "progress"):
            ttl, obj = (qindex_ttl, qindex_obj) if name == "qindex" else _read_key(name)
            results[name] = {"ttl": ttl, "obj": obj}
            print(f"  - {name}: ttl={_ttl_str(ttl)} key={keys[name]}")

        # Summaries
        qbank_obj = results["qbank"]["obj"] or {}
        qbank = qbank_obj.get("bank") if isinstance(qbank_obj.get("bank"), dict) else None
        if isinstance(qbank, dict):
            qs = qbank.get("questions")
            qcount = len(qs) if isinstance(qs, dict) else 0
            print(f"[qbank] questions={qcount} vision_raw_len={len(qbank.get('vision_raw_text') or '')}")

        qc, sc = _inspect_qindex_payload(qindex_obj or {})
        print(f"[qindex] questions={qc} slices={sc} ttl={_ttl_str(qindex_ttl)}")

        # Exit criteria
        if args.require_qindex:
            if qc <= 0:
                print("[RESULT] FAIL: qindex not ready (no questions).", file=sys.stderr)
                return 1
            if qindex_ttl in (-2, -1) or qindex_ttl <= 0:
                print("[RESULT] FAIL: qindex TTL invalid.", file=sys.stderr)
                return 1

        print("[RESULT] OK")
        return 0
    finally:
        _stop_worker(worker_proc)

if __name__ == "__main__":
    raise SystemExit(main())
