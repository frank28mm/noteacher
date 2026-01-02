#!/usr/bin/env python3
"""
E2E run for Demo UI 2.0 pipeline (async grade + report job).

Flow:
  /uploads (local image) -> /grade (X-Force-Async: 1) -> poll /jobs/{job_id}
  -> read /session/{session_id}/qbank meta -> POST /reports -> poll /reports/jobs/{job_id}
  -> GET /reports/{report_id}

Usage:
  source .venv/bin/activate
  export PYTHONPATH=$(pwd)
  python scripts/e2e_demo_ui2_pipeline.py --image-file "/path/to/IMG.jpg"
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
from dotenv import load_dotenv


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _mask(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if len(s) <= 12:
        return s[:4] + "…" + s[-2:]
    return s[:6] + "…" + s[-4:]


def _headers(*, user_id: Optional[str], auth_token: Optional[str]) -> Dict[str, str]:
    uid = (user_id or os.getenv("DEMO_USER_ID") or os.getenv("DEV_USER_ID") or "dev_user").strip() or "dev_user"
    token = (auth_token or os.getenv("DEMO_AUTH_TOKEN") or "").strip()
    headers: Dict[str, str] = {"X-User-Id": uid}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


@dataclass
class Timings:
    upload_ms: int = 0
    grade_submit_ms: int = 0
    grade_total_ms: int = 0
    report_submit_ms: int = 0
    report_total_ms: int = 0


def _post_upload(
    *,
    api_base: str,
    image_file: str,
    session_id: str,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    path = Path(image_file)
    if not path.exists():
        raise FileNotFoundError(str(path))
    with path.open("rb") as f:
        files = {"file": (path.name, f, "application/octet-stream")}
        with httpx.Client(timeout=180.0) as client:
            r = client.post(
                f"{api_base}/uploads",
                files=files,
                params={"session_id": session_id},
                headers=headers,
            )
    if r.status_code != 200:
        raise RuntimeError(f"/uploads failed {r.status_code}: {r.text[:600]}")
    data = r.json() if r.content else {}
    if not isinstance(data, dict) or not data.get("upload_id"):
        raise RuntimeError(f"/uploads returned unexpected body: {data}")
    return data


def _post_grade_async(
    *,
    api_base: str,
    upload_id: str,
    session_id: str,
    subject: str,
    vision_provider: str,
    llm_provider: str,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "images": [],
        "upload_id": upload_id,
        "subject": subject,
        "session_id": session_id,
        "vision_provider": vision_provider,
        "llm_provider": llm_provider,
    }
    h = dict(headers)
    h["X-Force-Async"] = "1"
    with httpx.Client(timeout=60.0) as client:
        r = client.post(f"{api_base}/grade", json=payload, headers=h)
    if r.status_code not in (200, 202):
        raise RuntimeError(f"/grade failed {r.status_code}: {r.text[:800]}")
    data = r.json() if r.content else {}
    if not isinstance(data, dict):
        raise RuntimeError(f"/grade returned unexpected body: {data}")
    return data


def _get_job(*, api_base: str, job_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    with httpx.Client(timeout=10.0) as client:
        r = client.get(f"{api_base}/jobs/{job_id}", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"/jobs/{job_id} failed {r.status_code}: {r.text[:400]}")
    data = r.json() if r.content else {}
    return data if isinstance(data, dict) else {}


def _get_qbank_meta(*, api_base: str, session_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    with httpx.Client(timeout=10.0) as client:
        r = client.get(f"{api_base}/session/{session_id}/qbank", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"/session/{session_id}/qbank failed {r.status_code}: {r.text[:400]}")
    data = r.json() if r.content else {}
    return data if isinstance(data, dict) else {}


def _post_report_job(
    *,
    api_base: str,
    window_days: int,
    subject: Optional[str],
    headers: Dict[str, str],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"window_days": int(window_days)}
    if subject:
        payload["subject"] = str(subject)
    with httpx.Client(timeout=15.0) as client:
        r = client.post(f"{api_base}/reports", json=payload, headers=headers)
    if r.status_code not in (200, 202):
        raise RuntimeError(f"/reports failed {r.status_code}: {r.text[:600]}")
    data = r.json() if r.content else {}
    return data if isinstance(data, dict) else {}


def _get_report_job(*, api_base: str, job_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    with httpx.Client(timeout=10.0) as client:
        r = client.get(f"{api_base}/reports/jobs/{job_id}", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"/reports/jobs/{job_id} failed {r.status_code}: {r.text[:400]}")
    data = r.json() if r.content else {}
    return data if isinstance(data, dict) else {}


def _get_report(*, api_base: str, report_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    with httpx.Client(timeout=15.0) as client:
        r = client.get(f"{api_base}/reports/{report_id}", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"/reports/{report_id} failed {r.status_code}: {r.text[:400]}")
    data = r.json() if r.content else {}
    return data if isinstance(data, dict) else {}


def _poll_until(
    *,
    label: str,
    poll_fn,
    is_done_fn,
    timeout_seconds: int,
    interval_seconds: float = 1.0,
) -> Tuple[Dict[str, Any], int]:
    started = time.monotonic()
    last_status = None
    while True:
        elapsed = time.monotonic() - started
        if elapsed > timeout_seconds:
            raise TimeoutError(f"{label} timed out after {timeout_seconds}s")
        obj = poll_fn()
        status = str(obj.get("status") or "")
        if status and status != last_status:
            print(f"[{label}] status={status} t+{int(elapsed)}s")
            last_status = status
        if is_done_fn(obj):
            return obj, int(elapsed * 1000)
        time.sleep(interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--image-file", required=True)
    parser.add_argument("--subject", default="math", choices=["math", "english"])
    parser.add_argument("--vision-provider", default="doubao", choices=["doubao", "qwen3"])
    parser.add_argument("--llm-provider", default="ark", choices=["ark", "silicon"])
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--auth-token", default=None)
    parser.add_argument("--timeout-grade", type=int, default=900)
    parser.add_argument("--timeout-report", type=int, default=180)
    parser.add_argument("--out", default=None, help="Markdown output path")
    args = parser.parse_args()

    load_dotenv(".env")

    headers = _headers(user_id=args.user_id, auth_token=args.auth_token)
    session_id = f"demo_{uuid.uuid4().hex[:8]}"
    timings = Timings()

    # /uploads
    t0 = time.monotonic()
    up = _post_upload(
        api_base=args.api_base,
        image_file=args.image_file,
        session_id=session_id,
        headers=headers,
    )
    timings.upload_ms = int((time.monotonic() - t0) * 1000)
    upload_id = str(up.get("upload_id"))

    # /grade (async)
    t1 = time.monotonic()
    grade_accepted = _post_grade_async(
        api_base=args.api_base,
        upload_id=upload_id,
        session_id=session_id,
        subject=args.subject,
        vision_provider=args.vision_provider,
        llm_provider=args.llm_provider,
        headers=headers,
    )
    timings.grade_submit_ms = int((time.monotonic() - t1) * 1000)
    job_id = str(grade_accepted.get("job_id") or "").strip()
    session_id_out = str(grade_accepted.get("session_id") or session_id).strip()
    if not job_id:
        raise RuntimeError(f"/grade async did not return job_id: {grade_accepted}")

    job, timings.grade_total_ms = _poll_until(
        label="grade",
        poll_fn=lambda: _get_job(api_base=args.api_base, job_id=job_id, headers=headers),
        is_done_fn=lambda o: str(o.get("status") or "") in {"done", "failed"},
        timeout_seconds=int(args.timeout_grade),
        interval_seconds=1.0,
    )

    grade_status = str(job.get("status") or "")
    grade_result = job.get("result") if isinstance(job, dict) else None
    if grade_status != "done" or not isinstance(grade_result, dict):
        raise RuntimeError(f"grade did not finish successfully: status={grade_status} job={job}")

    # qbank meta (for ark_response_id / image_process flags)
    qbank_meta = {}
    try:
        qbank_meta = _get_qbank_meta(api_base=args.api_base, session_id=session_id_out, headers=headers)
    except Exception as e:
        qbank_meta = {"error": str(e)}

    # /reports (async job)
    t2 = time.monotonic()
    report_created = _post_report_job(
        api_base=args.api_base,
        window_days=args.window_days,
        subject=args.subject,
        headers=headers,
    )
    timings.report_submit_ms = int((time.monotonic() - t2) * 1000)
    report_job_id = str(report_created.get("job_id") or "").strip()
    if not report_job_id:
        raise RuntimeError(f"/reports did not return job_id: {report_created}")

    report_job, timings.report_total_ms = _poll_until(
        label="report",
        poll_fn=lambda: _get_report_job(api_base=args.api_base, job_id=report_job_id, headers=headers),
        is_done_fn=lambda o: str(o.get("status") or "") in {"done", "failed"},
        timeout_seconds=int(args.timeout_report),
        interval_seconds=1.0,
    )
    report_status = str(report_job.get("status") or "")
    report_id = str(report_job.get("report_id") or "").strip()
    report_row: Dict[str, Any] = {}
    if report_status == "done" and report_id:
        report_row = _get_report(api_base=args.api_base, report_id=report_id, headers=headers)

    # Summaries
    llm_trace = (qbank_meta.get("meta") or {}) if isinstance(qbank_meta, dict) else {}
    if isinstance(llm_trace, dict):
        ark_response_id = llm_trace.get("ark_response_id")
    else:
        ark_response_id = None

    out_path = args.out
    if not out_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = f"docs/reports/demo_ui2_run_{ts}.md"
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    wrong_count = grade_result.get("wrong_count")
    total_items = grade_result.get("total_items")
    warnings = grade_result.get("warnings") or []
    summary = grade_result.get("summary") or ""

    report_title = report_row.get("title") if isinstance(report_row, dict) else None
    report_content = report_row.get("content") if isinstance(report_row, dict) else None

    md = []
    md.append(f"# Demo UI 2.0 一次性联调报告\n")
    md.append(f"- generated_at: `{_now_iso()}`")
    md.append(f"- api_base: `{args.api_base}`")
    md.append(f"- image_file: `{args.image_file}`")
    md.append(f"- subject: `{args.subject}`")
    md.append(f"- vision_provider: `{args.vision_provider}`")
    md.append(f"- llm_provider: `{args.llm_provider}`")
    md.append("")
    md.append("## 关键 ID（可用于审计/复现）")
    md.append(f"- session_id: `{session_id_out}`")
    md.append(f"- upload_id(submission_id): `{upload_id}`")
    md.append(f"- grade_job_id: `{job_id}`")
    md.append(f"- report_job_id: `{report_job_id}`")
    md.append(f"- report_id: `{report_id or '∅'}`")
    md.append(f"- ark_response_id(qbank.meta): `{_mask(str(ark_response_id or '')) or '∅'}`")
    md.append("")
    md.append("## 性能（本机观测）")
    md.append(f"- /uploads: `{timings.upload_ms}ms`")
    md.append(f"- /grade submit(202): `{timings.grade_submit_ms}ms`")
    md.append(f"- /grade end-to-end(queued→done): `{timings.grade_total_ms}ms`")
    md.append(f"- /reports submit(202): `{timings.report_submit_ms}ms`")
    md.append(f"- /reports end-to-end(queued→done): `{timings.report_total_ms}ms`")
    md.append("")
    md.append("## Grade 结果摘要")
    md.append(f"- status: `{grade_status}`")
    md.append(f"- total_items: `{total_items}`")
    md.append(f"- wrong_count: `{wrong_count}`")
    md.append(f"- summary: `{(summary or '').strip()[:120]}`")
    md.append(f"- warnings_count: `{len(warnings) if isinstance(warnings, list) else 0}`")
    md.append("")
    if isinstance(warnings, list) and warnings:
        md.append("### warnings（截断）")
        for w in warnings[:20]:
            md.append(f"- {str(w)[:200]}")
        md.append("")

    md.append("## Ark image_process / 审计字段（来自 /session/{session_id}/qbank.meta）")
    md.append("```json")
    try:
        md.append(json.dumps(qbank_meta.get("meta") if isinstance(qbank_meta, dict) else qbank_meta, ensure_ascii=False, indent=2)[:8000])
    except Exception:
        md.append("{}")
    md.append("```")
    md.append("")

    md.append("## Report 结果摘要")
    md.append(f"- status: `{report_status}`")
    md.append(f"- title: `{str(report_title or '').strip() or '∅'}`")
    if isinstance(report_content, str) and report_content.strip():
        md.append("")
        md.append("### report.content（前 2000 字）")
        md.append(report_content.strip()[:2000])
        md.append("")

    out_file.write_text("\n".join(md) + "\n", encoding="utf-8")

    print("[OK] wrote:", str(out_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

