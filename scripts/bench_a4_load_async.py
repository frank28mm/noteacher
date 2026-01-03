#!/usr/bin/env python3
"""
A-4 "production-equivalent" benchmark harness (backend-focused).

Goals (aligned with current execution plan):
- Simulate burst submissions with 3–4 pages per submission.
- Separate queue_wait_ms vs worker_elapsed_ms, and track per-page readiness timestamps.
- Record evidence as JSON + Markdown under docs/reports/.

Notes:
- This script drives the public API (uploads -> grade -> jobs polling).
- It does NOT manage workers/redis; start them yourself (e.g., grade_worker=2).
- It uses URL-only image input (upload_id resolves canonical page_image_urls).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv


def _now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _headers(*, user_id: Optional[str], auth_token: Optional[str]) -> Dict[str, str]:
    uid = (
        (user_id or os.getenv("DEMO_USER_ID") or os.getenv("DEV_USER_ID") or "dev_user")
        .strip()
        or "dev_user"
    )
    token = (auth_token or os.getenv("DEMO_AUTH_TOKEN") or "").strip()
    headers: Dict[str, str] = {"X-User-Id": uid}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _out_paths(prefix: str) -> tuple[Path, Path]:
    out_json = Path("docs/reports") / f"{prefix}.json"
    out_md = Path("docs/reports") / f"{prefix}.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    return out_json, out_md


def _as_files(image_files: List[str]) -> List[Tuple[str, Tuple[str, Any, str]]]:
    files: List[Tuple[str, Tuple[str, Any, str]]] = []
    for p in image_files:
        path = Path(p)
        if not path.exists():
            raise FileNotFoundError(str(path))
        # Best-effort content-type (backend doesn't rely on it).
        content_type = "application/octet-stream"
        suffix = path.suffix.lower().lstrip(".")
        if suffix in {"jpg", "jpeg"}:
            content_type = "image/jpeg"
        elif suffix in {"png"}:
            content_type = "image/png"
        elif suffix in {"heic"}:
            content_type = "image/heic"
        f = path.open("rb")
        files.append(("file", (path.name, f, content_type)))
    return files


async def _post_upload(
    *,
    client: httpx.AsyncClient,
    api_base: str,
    image_files: List[str],
    session_id: str,
    headers: Dict[str, str],
) -> Tuple[Dict[str, Any], int]:
    t0 = time.monotonic()
    files = _as_files(image_files)
    try:
        r = await client.post(
            f"{api_base}/uploads",
            files=files,
            params={"session_id": session_id},
            headers=headers,
        )
    finally:
        # Always close file descriptors.
        for _, (name, fh, _) in files:
            try:
                fh.close()
            except Exception:
                _ = name
    upload_ms = int((time.monotonic() - t0) * 1000)
    if r.status_code != 200:
        raise RuntimeError(f"/uploads failed {r.status_code}: {r.text[:600]}")
    data = r.json() if r.content else {}
    if not isinstance(data, dict) or not data.get("upload_id"):
        raise RuntimeError(f"/uploads returned unexpected body: {data}")
    return data, upload_ms


async def _post_grade_async(
    *,
    client: httpx.AsyncClient,
    api_base: str,
    upload_id: str,
    session_id: str,
    subject: str,
    vision_provider: str,
    llm_provider: str,
    headers: Dict[str, str],
) -> Tuple[Dict[str, Any], int]:
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
    t0 = time.monotonic()
    r = await client.post(f"{api_base}/grade", json=payload, headers=h)
    submit_ms = int((time.monotonic() - t0) * 1000)
    if r.status_code not in (200, 202):
        raise RuntimeError(f"/grade failed {r.status_code}: {r.text[:800]}")
    data = r.json() if r.content else {}
    if not isinstance(data, dict):
        raise RuntimeError(f"/grade returned unexpected body: {data}")
    return data, submit_ms


async def _get_job(
    *, client: httpx.AsyncClient, api_base: str, job_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    r = await client.get(f"{api_base}/jobs/{job_id}", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"/jobs/{job_id} failed {r.status_code}: {r.text[:400]}")
    data = r.json() if r.content else {}
    return data if isinstance(data, dict) else {}


async def _get_qbank_meta(
    *,
    client: httpx.AsyncClient,
    api_base: str,
    session_id: str,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    r = await client.get(f"{api_base}/session/{session_id}/qbank", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(
            f"/session/{session_id}/qbank failed {r.status_code}: {r.text[:400]}"
        )
    data = r.json() if r.content else {}
    return data if isinstance(data, dict) else {}


@dataclass
class SubmissionRun:
    run_index: int
    upload_id: str
    session_id: str
    job_id: str
    pages: int
    upload_ms: int
    grade_submit_ms: int
    queue_wait_ms: int
    ttv_first_page_ms: Optional[int]
    ttd_done_ms: Optional[int]
    job_status: str
    job_elapsed_ms: Optional[int]
    per_page_ready_ms: Dict[int, int]
    qbank_meta: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


async def _poll_job_until_done(
    *,
    client: httpx.AsyncClient,
    api_base: str,
    job_id: str,
    headers: Dict[str, str],
    timeout_seconds: int,
    poll_interval_seconds: float,
    total_pages: int,
) -> Tuple[Dict[str, Any], int, Optional[int], Dict[int, int], bool]:
    started = time.monotonic()
    queue_wait_ms: Optional[int] = None
    ttv_first_page_ms: Optional[int] = None
    per_page_ready_ms: Dict[int, int] = {}
    last_done_pages: Optional[int] = None
    last_status = None
    last_job: Dict[str, Any] = {}

    while True:
        elapsed_s = time.monotonic() - started
        if elapsed_s > timeout_seconds:
            if queue_wait_ms is None:
                queue_wait_ms = 0
            return last_job, int(queue_wait_ms), ttv_first_page_ms, per_page_ready_ms, True

        job = await _get_job(
            client=client, api_base=api_base, job_id=job_id, headers=headers
        )
        last_job = job if isinstance(job, dict) else {}
        status = str(job.get("status") or "unknown")
        if status != last_status:
            last_status = status
        if status == "running" and queue_wait_ms is None:
            queue_wait_ms = int(elapsed_s * 1000)

        done_pages = job.get("done_pages")
        if isinstance(done_pages, int):
            if last_done_pages is None:
                last_done_pages = done_pages
            if done_pages > last_done_pages:
                # Record time when page N becomes ready (done_pages counts pages completed).
                # We map done_pages=1 => page_index=0, etc.
                for pidx in range(last_done_pages, done_pages):
                    per_page_ready_ms[int(pidx)] = int(elapsed_s * 1000)
                last_done_pages = done_pages
            if done_pages >= 1 and ttv_first_page_ms is None:
                ttv_first_page_ms = int(elapsed_s * 1000)

        if status in {"done", "failed"}:
            if queue_wait_ms is None:
                queue_wait_ms = 0
            return job, int(queue_wait_ms), ttv_first_page_ms, per_page_ready_ms, False

        # Light polling; real UI uses dynamic backoff, but for benchmarking keep fixed.
        await asyncio.sleep(poll_interval_seconds)


def _percentile(values: List[int], p: float) -> Optional[int]:
    if not values:
        return None
    xs = sorted(int(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    k = int(round((p / 100.0) * (len(xs) - 1)))
    k = min(max(k, 0), len(xs) - 1)
    return xs[k]


def _summarize(runs: List[SubmissionRun]) -> Dict[str, Any]:
    done = [r for r in runs if r.job_status == "done" and r.ttd_done_ms is not None]
    timeout = [r for r in runs if r.job_status == "timeout"]
    failed = [r for r in runs if r.job_status not in {"done", "timeout"}]

    def _ints(xs: List[Optional[int]]) -> List[int]:
        return [int(x) for x in xs if isinstance(x, int)]

    ttd = _ints([r.ttd_done_ms for r in done])
    ttv = _ints([r.ttv_first_page_ms for r in done])
    queue = _ints([r.queue_wait_ms for r in done])
    worker = _ints([r.job_elapsed_ms for r in done])

    return {
        "n_total": len(runs),
        "n_done": len(done),
        "n_timeout": len(timeout),
        "n_failed": len(failed),
        "timeout_job_ids": [r.job_id for r in timeout if r.job_id][:50],
        "failed_job_ids": [r.job_id for r in failed if r.job_id][:50],
        "queue_wait_ms": {
            "p50": _percentile(queue, 50),
            "p95": _percentile(queue, 95),
            "max": max(queue) if queue else None,
        },
        "ttv_first_page_ms": {
            "p50": _percentile(ttv, 50),
            "p95": _percentile(ttv, 95),
            "max": max(ttv) if ttv else None,
        },
        "ttd_done_ms": {
            "p50": _percentile(ttd, 50),
            "p95": _percentile(ttd, 95),
            "max": max(ttd) if ttd else None,
        },
        "worker_elapsed_ms": {
            "p50": _percentile(worker, 50),
            "p95": _percentile(worker, 95),
            "max": max(worker) if worker else None,
        },
    }


def _write_md(*, out_md: Path, raw: Dict[str, Any], runs: List[SubmissionRun], summary: Dict[str, Any]) -> None:
    lines: List[str] = []
    lines.append("# A-4 生产等价压测（Load / Async）\n")
    lines.append(f"- generated_at: `{raw.get('generated_at')}`")
    lines.append(f"- api_base: `{raw.get('api_base')}`")
    lines.append(f"- user_id: `{raw.get('user_id')}`")
    lines.append(f"- worker_count(label): `{raw.get('worker_count')}`")
    lines.append(f"- burst_submissions: `{raw.get('burst_submissions')}`")
    lines.append(f"- pages_per_submission: `{raw.get('pages_per_submission')}`")
    lines.append(f"- subject: `{raw.get('subject')}`")
    lines.append(f"- vision_provider: `{raw.get('vision_provider')}`")
    lines.append(f"- llm_provider: `{raw.get('llm_provider')}`")
    lines.append(f"- preload_submissions: `{raw.get('preload_submissions')}`")
    lines.append(f"- preload_hold_seconds: `{raw.get('preload_hold_seconds')}`")
    lines.append(f"- upload_concurrency: `{raw.get('upload_concurrency')}`")
    lines.append(f"- grade_concurrency: `{raw.get('grade_concurrency')}`")
    lines.append(f"- poll_interval_seconds: `{raw.get('poll_interval_seconds')}`")
    lines.append(f"- timeout_seconds: `{raw.get('timeout_seconds')}`")
    lines.append("")

    lines.append("## 汇总")
    lines.append(f"- n_total: `{summary.get('n_total')}`")
    lines.append(f"- n_done: `{summary.get('n_done')}`")
    lines.append(f"- n_timeout: `{summary.get('n_timeout')}`")
    lines.append(f"- n_failed: `{summary.get('n_failed')}`")
    lines.append("")
    lines.append("| metric | p50_ms | p95_ms | max_ms |")
    lines.append("|---|---:|---:|---:|")
    for k in ["queue_wait_ms", "ttv_first_page_ms", "worker_elapsed_ms", "ttd_done_ms"]:
        v = summary.get(k, {}) if isinstance(summary.get(k), dict) else {}
        lines.append(
            "| {k} | {p50} | {p95} | {mx} |".format(
                k=k,
                p50=str(v.get("p50") or ""),
                p95=str(v.get("p95") or ""),
                mx=str(v.get("max") or ""),
            )
        )
    lines.append("")

    lines.append("## 明细（每次 submission）")
    lines.append(
        "| idx | pages | status | upload_ms | submit_ms | queue_wait_ms | ttv_first_page_ms | worker_elapsed_ms | ttd_done_ms |"
    )
    lines.append("|---:|---:|---|---:|---:|---:|---:|---:|---:|")
    for r in runs:
        lines.append(
            "| {idx} | {pages} | {status} | {up} | {sub} | {q} | {ttv} | {wk} | {ttd} |".format(
                idx=r.run_index,
                pages=r.pages,
                status=r.job_status,
                up=r.upload_ms,
                sub=r.grade_submit_ms,
                q=r.queue_wait_ms,
                ttv=r.ttv_first_page_ms or "",
                wk=r.job_elapsed_ms or "",
                ttd=r.ttd_done_ms or "",
            )
        )
    lines.append("")

    lines.append("## 逐页可用（可解释证据）")
    lines.append(
        "每条记录会输出 `per_page_ready_ms`（page_index→ms），用于确认“第 1 页可用是否足够早”。"
    )
    lines.append("")

    out_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="A-4 load benchmark (uploads + async grade jobs).")
    parser.add_argument("--api-base", type=str, default="http://localhost:8000/api/v1")
    parser.add_argument("--user-id", type=str, default=None)
    parser.add_argument("--auth-token", type=str, default=None)
    parser.add_argument("--subject", type=str, default="math")
    parser.add_argument("--vision-provider", type=str, default=os.getenv("LIVE_VISION_PROVIDER", "doubao"))
    parser.add_argument("--llm-provider", type=str, default=os.getenv("LIVE_LLM_PROVIDER", "ark"))
    parser.add_argument("--worker-count", type=int, default=2, help="Label only (start workers yourself).")
    parser.add_argument("--burst-submissions", type=int, default=20)
    parser.add_argument("--pages-per-submission", type=int, default=3)
    parser.add_argument("--image-file", action="append", default=[], help="Page image file path (repeatable).")
    parser.add_argument(
        "--preload-submissions",
        type=int,
        default=0,
        help="Optional: enqueue some jobs before measurement to simulate a small backlog (do not wait for completion).",
    )
    parser.add_argument(
        "--preload-hold-seconds",
        type=float,
        default=10.0,
        help="After preload enqueues, wait a bit so they start running before the measured burst.",
    )
    parser.add_argument(
        "--upload-concurrency",
        type=int,
        default=6,
        help="Limit concurrent /uploads to avoid saturating storage/network.",
    )
    parser.add_argument(
        "--grade-concurrency",
        type=int,
        default=20,
        help="Limit concurrent /grade submissions (queue burst).",
    )
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=int, default=60 * 30)
    parser.add_argument("--out-prefix", type=str, default=None)
    args = parser.parse_args()

    if not args.image_file:
        raise SystemExit("Provide at least one --image-file (repeatable) to form pages.")
    pages_per = int(args.pages_per_submission)
    if pages_per <= 0:
        raise SystemExit("--pages-per-submission must be >= 1")

    api_base = str(args.api_base).rstrip("/")
    user_id = (args.user_id or os.getenv("DEMO_USER_ID") or f"bench_{uuid.uuid4().hex[:8]}").strip()
    headers = _headers(user_id=user_id, auth_token=args.auth_token)

    out_prefix = (
        args.out_prefix
        or f"a4_load_w{int(args.worker_count)}_burst{int(args.burst_submissions)}_p{pages_per}_{_now_ts()}"
    )
    out_json, out_md = _out_paths(out_prefix)

    # Build per-submission page lists (reuse provided files if not enough).
    pool = [str(p) for p in args.image_file]
    page_lists: List[List[str]] = []
    for i in range(int(args.burst_submissions)):
        pages: List[str] = []
        for j in range(pages_per):
            pages.append(pool[(i * pages_per + j) % len(pool)])
        page_lists.append(pages)

    timeout = httpx.Timeout(connect=10.0, read=180.0, write=180.0, pool=10.0)
    limits = httpx.Limits(max_keepalive_connections=50, max_connections=80)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        runs: List[SubmissionRun] = []
        upload_sem = asyncio.Semaphore(max(1, int(args.upload_concurrency)))
        grade_sem = asyncio.Semaphore(max(1, int(args.grade_concurrency)))
        preload_job_ids: List[str] = []

        async def _one(i: int, pages: List[str]) -> SubmissionRun:
            session_id = f"a4_{out_prefix}_{i}_{uuid.uuid4().hex[:6]}"
            try:
                async with upload_sem:
                    upload_data, upload_ms = await _post_upload(
                        client=client,
                        api_base=api_base,
                        image_files=pages,
                        session_id=session_id,
                        headers=headers,
                    )
                upload_id = str(upload_data.get("upload_id"))
                async with grade_sem:
                    grade_data, submit_ms = await _post_grade_async(
                        client=client,
                        api_base=api_base,
                        upload_id=upload_id,
                        session_id=session_id,
                        subject=str(args.subject),
                        vision_provider=str(args.vision_provider),
                        llm_provider=str(args.llm_provider),
                        headers=headers,
                    )
                job_id = str(grade_data.get("job_id") or "")
                if not job_id:
                    raise RuntimeError(f"/grade did not return job_id: {grade_data}")

                job, queue_wait_ms, ttv_ms, per_page, timed_out = (
                    await _poll_job_until_done(
                    client=client,
                    api_base=api_base,
                    job_id=job_id,
                    headers=headers,
                    timeout_seconds=int(args.timeout_seconds),
                    poll_interval_seconds=float(args.poll_interval_seconds),
                    total_pages=len(pages),
                )
                )
                status = str(job.get("status") or "unknown")
                if timed_out and status not in {"done", "failed"}:
                    status = "timeout"
                ttd_ms = (
                    int(job.get("elapsed_ms") or 0)
                    if status in {"done", "failed"}
                    else None
                )

                # Prefer worker elapsed_ms from job if present; else approximate by wall clock.
                job_elapsed_ms = None
                if isinstance(job.get("elapsed_ms"), int):
                    job_elapsed_ms = int(job.get("elapsed_ms"))

                # Best-effort: qbank meta for timings and audit ids.
                qbank_meta: Optional[Dict[str, Any]] = None
                try:
                    qbank_meta = await _get_qbank_meta(
                        client=client,
                        api_base=api_base,
                        session_id=session_id,
                        headers=headers,
                    )
                except Exception:
                    qbank_meta = None

                # ttd_done_ms: wall clock (from polling start) is better for UX; store separately.
                # We approximate with: queue_wait_ms + job_elapsed_ms when job_elapsed_ms exists.
                ttd_done_ms = None
                if status == "done":
                    if job_elapsed_ms is not None:
                        ttd_done_ms = int(queue_wait_ms) + int(job_elapsed_ms)
                    else:
                        # Fallback: use last recorded page time if any.
                        if per_page:
                            ttd_done_ms = max(per_page.values())

                return SubmissionRun(
                    run_index=i,
                    upload_id=upload_id,
                    session_id=session_id,
                    job_id=job_id,
                    pages=len(pages),
                    upload_ms=upload_ms,
                    grade_submit_ms=submit_ms,
                    queue_wait_ms=int(queue_wait_ms),
                    ttv_first_page_ms=ttv_ms,
                    ttd_done_ms=ttd_done_ms,
                    job_status=status,
                    job_elapsed_ms=job_elapsed_ms,
                    per_page_ready_ms=per_page,
                    qbank_meta=qbank_meta,
                    error=None,
                )
            except Exception as e:
                return SubmissionRun(
                    run_index=i,
                    upload_id="",
                    session_id=session_id,
                    job_id="",
                    pages=len(pages),
                    upload_ms=0,
                    grade_submit_ms=0,
                    queue_wait_ms=0,
                    ttv_first_page_ms=None,
                    ttd_done_ms=None,
                    job_status="failed",
                    job_elapsed_ms=None,
                    per_page_ready_ms={},
                    qbank_meta=None,
                    error=str(e),
                )

        async def _enqueue_preload(i: int, pages: List[str]) -> None:
            session_id = f"a4_preload_{out_prefix}_{i}_{uuid.uuid4().hex[:6]}"
            async with upload_sem:
                upload_data, _upload_ms = await _post_upload(
                    client=client,
                    api_base=api_base,
                    image_files=pages,
                    session_id=session_id,
                    headers=headers,
                )
            upload_id = str(upload_data.get("upload_id"))
            async with grade_sem:
                grade_data, _submit_ms = await _post_grade_async(
                    client=client,
                    api_base=api_base,
                    upload_id=upload_id,
                    session_id=session_id,
                    subject=str(args.subject),
                    vision_provider=str(args.vision_provider),
                    llm_provider=str(args.llm_provider),
                    headers=headers,
                )
            job_id = str(grade_data.get("job_id") or "")
            if job_id:
                preload_job_ids.append(job_id)

        # Optional preload to simulate backlog.
        preload_n = max(0, int(args.preload_submissions))
        if preload_n:
            preload_page_lists = page_lists[:preload_n]
            preload_tasks = [
                asyncio.create_task(_enqueue_preload(i, preload_page_lists[i]))
                for i in range(len(preload_page_lists))
            ]
            await asyncio.gather(*preload_tasks)
            hold = max(0.0, float(args.preload_hold_seconds))
            if hold:
                await asyncio.sleep(hold)

        # Burst: start measured submissions concurrently.
        tasks = [asyncio.create_task(_one(i, page_lists[i])) for i in range(len(page_lists))]
        for t in asyncio.as_completed(tasks):
            r = await t
            runs.append(r)
            # Persist incrementally for crash safety.
            raw: Dict[str, Any] = {
                "generated_at": out_prefix,
                "api_base": api_base,
                "user_id": user_id,
                "worker_count": int(args.worker_count),
                "burst_submissions": int(args.burst_submissions),
                "pages_per_submission": int(args.pages_per_submission),
                "subject": str(args.subject),
                "vision_provider": str(args.vision_provider),
                "llm_provider": str(args.llm_provider),
                "upload_concurrency": int(args.upload_concurrency),
                "grade_concurrency": int(args.grade_concurrency),
                "preload_submissions": int(args.preload_submissions),
                "preload_hold_seconds": float(args.preload_hold_seconds),
                "preload_job_ids": preload_job_ids[:200],
                "poll_interval_seconds": float(args.poll_interval_seconds),
                "timeout_seconds": int(args.timeout_seconds),
                "runs": [asdict(x) for x in sorted(runs, key=lambda x: x.run_index)],
            }
            summary = _summarize(runs)
            raw["summary"] = summary
            out_json.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            _write_md(out_md=out_md, raw=raw, runs=sorted(runs, key=lambda x: x.run_index), summary=summary)

    print(f"[OK] wrote: {out_json}")
    print(f"[OK] wrote: {out_md}")
    return 0


def main() -> int:
    load_dotenv()
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
