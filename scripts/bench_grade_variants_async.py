#!/usr/bin/env python3
"""
Benchmark /grade async latency by image input variants + preprocess modes.

It runs:
  /uploads once (local file) -> for each case:
    /grade (X-Force-Async: 1, upload_id, images=[])
    poll /jobs/{job_id} and measure queue_wait_ms (processing->running) and total_ms
    fetch /session/{session_id}/qbank to collect timings_ms + ark_response_id/tool flags

Note:
- Changing AUTONOMOUS_PREPROCESS_MODE requires restarting the grade_worker (and backend if not running in worker mode).

Usage:
  source .venv/bin/activate
  export PYTHONPATH=$(pwd)
  python scripts/bench_grade_variants_async.py \\
    --image-file "/path/to/IMG.jpg" \\
    --variants url proxy data_url_first_page \\
    --repeat 10 \\
    --out-prefix grade_perf_variants_qindex_only_n10

This script is intentionally sequential (one async job at a time) to reduce queue contention.
It writes results incrementally so you can safely stop and resume.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv


def _now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _headers(*, user_id: Optional[str], auth_token: Optional[str]) -> Dict[str, str]:
    uid = (user_id or os.getenv("DEMO_USER_ID") or os.getenv("DEV_USER_ID") or "dev_user").strip() or "dev_user"
    token = (auth_token or os.getenv("DEMO_AUTH_TOKEN") or "").strip()
    headers: Dict[str, str] = {"X-User-Id": uid}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _post_upload(*, api_base: str, image_file: str, session_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
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
    variant: str,
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
    if variant:
        h["X-Grade-Image-Input-Variant"] = variant
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


@dataclass
class CaseResult:
    preprocess_mode: str
    variant: str
    run_index: int
    job_id: str
    session_id: str
    upload_id: str
    grade_status: str
    queue_wait_ms: int
    total_ms: int
    timings_ms: Dict[str, Any]
    qbank_meta: Dict[str, Any]


def _poll_job(
    *,
    api_base: str,
    job_id: str,
    headers: Dict[str, str],
    timeout_seconds: int,
    interval_seconds: float,
) -> Tuple[Dict[str, Any], int, int]:
    started = time.monotonic()
    t_running: Optional[float] = None
    last_status = None
    while True:
        elapsed = time.monotonic() - started
        if elapsed > timeout_seconds:
            raise TimeoutError(f"grade job timed out after {timeout_seconds}s: {job_id}")
        job = _get_job(api_base=api_base, job_id=job_id, headers=headers)
        status = str(job.get("status") or "unknown")
        if status != last_status:
            print(f"[job {job_id}] status={status} t+{int(elapsed)}s")
            last_status = status
        if status == "running" and t_running is None:
            t_running = time.monotonic()
        if status in {"done", "failed"}:
            total_ms = int(elapsed * 1000)
            queue_wait_ms = 0
            if t_running is not None:
                queue_wait_ms = int((t_running - started) * 1000)
            return job, queue_wait_ms, total_ms
        time.sleep(interval_seconds)


def _percentile(values: List[int], p: float) -> Optional[int]:
    if not values:
        return None
    xs = sorted(int(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    # Nearest-rank (stable and simple)
    k = int(round((p / 100.0) * (len(xs) - 1)))
    k = min(max(k, 0), len(xs) - 1)
    return xs[k]


def _out_paths(prefix: str) -> tuple[Path, Path]:
    out_json = Path("docs/reports") / f"{prefix}.json"
    out_md = Path("docs/reports") / f"{prefix}.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    return out_json, out_md


def _load_existing(prefix: str) -> Optional[Dict[str, Any]]:
    out_json, _ = _out_paths(prefix)
    if not out_json.exists():
        return None
    try:
        raw = json.loads(out_json.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def _write_outputs(
    *,
    out_json: Path,
    out_md: Path,
    raw: Dict[str, Any],
    variants: List[str],
    results: List[CaseResult],
    summary: Dict[str, Any],
) -> None:
    out_json.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines: List[str] = []
    lines.append("# /grade 输入策略对比（async）\n")
    lines.append(f"- generated_at: `{raw.get('generated_at')}`")
    lines.append(f"- preprocess_mode(label): `{raw.get('preprocess_mode')}`")
    lines.append(f"- upload_id: `{raw.get('upload_id')}`")
    lines.append(f"- upload_ms: `{raw.get('upload_ms')}`")
    lines.append(f"- repeat: `{raw.get('repeat')}`")
    lines.append(f"- completed_cases: `{len(results)}`")
    lines.append("")
    lines.append("## 汇总（p50/p95）")
    lines.append(
        "| variant | n | total_ms_p50 | total_ms_p95 | queue_wait_p50 | queue_wait_p95 | grade_total_p50 | grade_total_p95 |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for v in variants:
        s = summary.get(str(v), {}) if isinstance(summary, dict) else {}

        def _s(k: str) -> str:
            vv = s.get(k)
            return str(int(vv)) if isinstance(vv, int) else ""

        lines.append(
            "| {v} | {n} | {t50} | {t95} | {q50} | {q95} | {g50} | {g95} |".format(
                v=str(v),
                n=str(int(s.get("n") or 0)),
                t50=_s("total_ms_p50"),
                t95=_s("total_ms_p95"),
                q50=_s("queue_wait_ms_p50"),
                q95=_s("queue_wait_ms_p95"),
                g50=_s("grade_total_duration_ms_p50"),
                g95=_s("grade_total_duration_ms_p95"),
            )
        )
    lines.append("")
    lines.append("## 明细（每次运行）")
    lines.append(
        "| variant | status | queue_wait_ms | total_ms | preprocess_total_ms | llm_aggregate_call_ms | grade_total_duration_ms | ark_image_process_requested | ark_image_process_enabled |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        t = r.timings_ms or {}

        def _i(k: str) -> str:
            v = t.get(k)
            return str(int(v)) if isinstance(v, int) else ""

        meta = r.qbank_meta or {}
        lines.append(
            "| {variant} | {status} | {qwait} | {total} | {prep} | {agg} | {gt} | {req} | {en} |".format(
                variant=r.variant,
                status=r.grade_status,
                qwait=r.queue_wait_ms,
                total=r.total_ms,
                prep=_i("preprocess_total_ms"),
                agg=_i("llm_aggregate_call_ms"),
                gt=_i("grade_total_duration_ms"),
                req=str(bool(meta.get("ark_image_process_requested", False))).lower()
                if isinstance(meta, dict)
                else "",
                en=str(bool(meta.get("ark_image_process_enabled", False))).lower()
                if isinstance(meta, dict)
                else "",
            )
        )
    lines.append("")
    lines.append(f"- raw_json: `{out_json}`")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--image-file", required=True)
    parser.add_argument("--subject", default="math", choices=["math", "english"])
    parser.add_argument("--vision-provider", default="doubao", choices=["doubao", "qwen3"])
    parser.add_argument("--llm-provider", default="ark", choices=["ark", "silicon"])
    parser.add_argument("--variants", nargs="+", default=["url", "proxy", "data_url_first_page"])
    parser.add_argument("--preprocess-mode", default=None, help="Recorded label only (set env + restart worker separately)")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--auth-token", default=None)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--repeat", type=int, default=1, help="Repeat each variant N times")
    parser.add_argument("--out-prefix", default=None, help="Output path prefix under docs/reports/")
    parser.add_argument("--resume", action="store_true", help="Resume from existing out-prefix json if present")
    args = parser.parse_args()

    load_dotenv(".env")

    headers = _headers(user_id=args.user_id, auth_token=args.auth_token)
    session_id_upload = f"bench_upload_{uuid.uuid4().hex[:8]}"

    preprocess_mode = (
        (args.preprocess_mode or os.getenv("AUTONOMOUS_PREPROCESS_MODE") or "unknown").strip().lower()
    )

    ts = _now_ts()
    prefix = args.out_prefix or f"grade_perf_variants_{preprocess_mode}_{ts}"
    out_json, out_md = _out_paths(prefix)

    existing = _load_existing(prefix) if bool(args.resume) else None
    results: List[CaseResult] = []
    upload_id = ""
    upload_ms = 0

    if existing:
        prev_cases = existing.get("cases")
        if isinstance(prev_cases, list):
            for c in prev_cases:
                if isinstance(c, dict):
                    try:
                        results.append(CaseResult(**c))
                    except Exception:
                        continue
        upload_id = str(existing.get("upload_id") or "").strip()
        try:
            upload_ms = int(existing.get("upload_ms") or 0)
        except Exception:
            upload_ms = 0

    if not upload_id:
        t0 = time.monotonic()
        up = _post_upload(
            api_base=args.api_base,
            image_file=args.image_file,
            session_id=session_id_upload,
            headers=headers,
        )
        upload_ms = int((time.monotonic() - t0) * 1000)
        upload_id = str(up.get("upload_id"))

    repeat = int(args.repeat or 1)
    if repeat < 1:
        repeat = 1

    completed = {(r.variant, int(r.run_index)) for r in results}

    for variant in args.variants:
        for run_index in range(repeat):
            if (str(variant), int(run_index)) in completed:
                continue
            sid = f"bench_{preprocess_mode}_{variant}_{uuid.uuid4().hex[:6]}"
            accepted = _post_grade_async(
                api_base=args.api_base,
                upload_id=upload_id,
                session_id=sid,
                subject=args.subject,
                vision_provider=args.vision_provider,
                llm_provider=args.llm_provider,
                variant=str(variant),
                headers=headers,
            )
            job_id = str(accepted.get("job_id") or "").strip()
            if not job_id:
                raise RuntimeError(f"missing job_id for variant={variant}: {accepted}")

            job, queue_wait_ms, total_ms = _poll_job(
                api_base=args.api_base,
                job_id=job_id,
                headers=headers,
                timeout_seconds=int(args.timeout),
                interval_seconds=float(args.interval),
            )
            grade_status = str(job.get("status") or "unknown")

            qbank_meta: Dict[str, Any] = {}
            timings_ms: Dict[str, Any] = {}
            try:
                qb = _get_qbank_meta(api_base=args.api_base, session_id=sid, headers=headers)
                qbank_meta = qb.get("meta") if isinstance(qb.get("meta"), dict) else {}
                timings_ms = (
                    qbank_meta.get("timings_ms")
                    if isinstance(qbank_meta.get("timings_ms"), dict)
                    else {}
                )
            except Exception as e:
                qbank_meta = {"error": str(e)}
                timings_ms = {}

            results.append(
                CaseResult(
                    preprocess_mode=preprocess_mode,
                    variant=str(variant),
                    run_index=int(run_index),
                    job_id=job_id,
                    session_id=sid,
                    upload_id=upload_id,
                    grade_status=grade_status,
                    queue_wait_ms=int(queue_wait_ms),
                    total_ms=int(total_ms),
                    timings_ms=timings_ms,
                    qbank_meta=qbank_meta,
                )
            )
            completed.add((str(variant), int(run_index)))
            # Incremental write (safe to interrupt/resume).
            per_variant: Dict[str, Dict[str, Any]] = {}
            for r in results:
                pv = per_variant.setdefault(
                    r.variant,
                    {"total_ms": [], "queue_wait_ms": [], "grade_total_duration_ms": []},
                )
                pv["total_ms"].append(int(r.total_ms))
                pv["queue_wait_ms"].append(int(r.queue_wait_ms))
                gt = (r.timings_ms or {}).get("grade_total_duration_ms")
                if isinstance(gt, int):
                    pv["grade_total_duration_ms"].append(int(gt))

            summary: Dict[str, Any] = {}
            for v, pv in per_variant.items():
                summary[v] = {
                    "n": len(pv["total_ms"]),
                    "total_ms_p50": _percentile(pv["total_ms"], 50),
                    "total_ms_p95": _percentile(pv["total_ms"], 95),
                    "queue_wait_ms_p50": _percentile(pv["queue_wait_ms"], 50),
                    "queue_wait_ms_p95": _percentile(pv["queue_wait_ms"], 95),
                    "grade_total_duration_ms_p50": _percentile(
                        pv["grade_total_duration_ms"], 50
                    ),
                    "grade_total_duration_ms_p95": _percentile(
                        pv["grade_total_duration_ms"], 95
                    ),
                }

            raw = {
                "generated_at": ts,
                "api_base": args.api_base,
                "image_file": args.image_file,
                "upload_id": upload_id,
                "upload_ms": upload_ms,
                "preprocess_mode": preprocess_mode,
                "repeat": repeat,
                "summary": summary,
                "cases": [asdict(r) for r in results],
            }
            _write_outputs(
                out_json=out_json,
                out_md=out_md,
                raw=raw,
                variants=[str(v) for v in args.variants],
                results=results,
                summary=summary,
            )

    per_variant: Dict[str, Dict[str, Any]] = {}
    for r in results:
        pv = per_variant.setdefault(
            r.variant, {"total_ms": [], "queue_wait_ms": [], "grade_total_duration_ms": []}
        )
        pv["total_ms"].append(int(r.total_ms))
        pv["queue_wait_ms"].append(int(r.queue_wait_ms))
        gt = (r.timings_ms or {}).get("grade_total_duration_ms")
        if isinstance(gt, int):
            pv["grade_total_duration_ms"].append(int(gt))

    summary: Dict[str, Any] = {}
    for v, pv in per_variant.items():
        summary[v] = {
            "n": len(pv["total_ms"]),
            "total_ms_p50": _percentile(pv["total_ms"], 50),
            "total_ms_p95": _percentile(pv["total_ms"], 95),
            "queue_wait_ms_p50": _percentile(pv["queue_wait_ms"], 50),
            "queue_wait_ms_p95": _percentile(pv["queue_wait_ms"], 95),
            "grade_total_duration_ms_p50": _percentile(pv["grade_total_duration_ms"], 50),
            "grade_total_duration_ms_p95": _percentile(pv["grade_total_duration_ms"], 95),
        }

    raw = {
        "generated_at": ts,
        "api_base": args.api_base,
        "image_file": args.image_file,
        "upload_id": upload_id,
        "upload_ms": upload_ms,
        "preprocess_mode": preprocess_mode,
        "repeat": repeat,
        "summary": summary,
        "cases": [asdict(r) for r in results],
    }

    _write_outputs(
        out_json=out_json,
        out_md=out_md,
        raw=raw,
        variants=[str(v) for v in args.variants],
        results=results,
        summary=summary,
    )

    print("[OK] wrote:", str(out_md))
    print("[OK] wrote:", str(out_json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
