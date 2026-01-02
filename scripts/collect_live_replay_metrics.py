#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import mimetypes
import sys
import time
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES_DIR = REPO_ROOT / "homework_agent" / "tests" / "replay_data" / "samples"

# Ensure `import homework_agent` works when executed from outside repo root.
sys.path.insert(0, str(REPO_ROOT))


@dataclass
class LiveSampleMetrics:
    sample_id: str
    subject: str
    status: str
    iterations: int
    duration_ms: int
    tokens_total: int
    needs_review: bool
    verdicts: Dict[str, int]
    warnings: List[str]
    error: Optional[str] = None


def _load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if str(x or "").strip()]
    if isinstance(v, str):
        s = v.strip()
        return [s] if s else []
    return [str(v)]


def _data_url_from_file(path: Path) -> str:
    mt, _ = mimetypes.guess_type(str(path))
    mt = mt or "image/jpeg"
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("utf-8")
    return f"data:{mt};base64,{b64}"


def _image_refs_from_sample(inp: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Returns a list of dicts compatible with homework_agent.models.schemas.ImageRef:
      {"url": "..."} or {"base64": "data:image/...;base64,..."}
    """
    local_images = _as_list(inp.get("local_images"))
    image_urls = _as_list(inp.get("image_urls"))
    or_base64 = inp.get("or_base64")

    refs: List[Dict[str, str]] = []
    for p in local_images:
        path = Path(p)
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"local_images not found: {path}")
        refs.append({"base64": _data_url_from_file(path)})
    for u in image_urls:
        refs.append({"url": str(u)})
    if or_base64:
        refs.append({"base64": str(or_base64)})

    if not refs:
        raise ValueError("input must include one of local_images/image_urls/or_base64")
    return refs


def _percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    data = sorted(data)
    k = (len(data) - 1) * p / 100.0
    f = int(k)
    c = min(len(data) - 1, f + 1)
    if f == c:
        return float(data[f])
    return float(data[f]) + (float(data[c]) - float(data[f])) * (k - f)


def _summarize(metrics: List[LiveSampleMetrics]) -> Dict[str, Any]:
    total = len(metrics)
    success = sum(1 for m in metrics if m.status == "done")
    error = sum(1 for m in metrics if m.status not in {"done"})
    needs_review = sum(1 for m in metrics if bool(m.needs_review))

    durations = [float(m.duration_ms) for m in metrics if m.duration_ms > 0]
    tokens = [float(m.tokens_total) for m in metrics if m.tokens_total > 0]
    iters = [float(m.iterations) for m in metrics if m.iterations > 0]

    verdicts_total = {"correct_total": 0, "incorrect_total": 0, "uncertain_total": 0}
    for m in metrics:
        v = m.verdicts or {}
        verdicts_total["correct_total"] += int(v.get("correct", 0) or 0)
        verdicts_total["incorrect_total"] += int(v.get("incorrect", 0) or 0)
        verdicts_total["uncertain_total"] += int(v.get("uncertain", 0) or 0)

    git_commit = ""
    git_branch = ""
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore").strip()  # noqa: E501
        git_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(REPO_ROOT), stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore").strip()  # noqa: E501
    except Exception:
        pass
    return {
        "eval_id": f"eval_live_{int(time.time())}",
        "generated_at": int(time.time()),
        "git_commit": git_commit,
        "git_branch": git_branch,
        "metrics_mode": "live",
        "total_samples": total,
        "success_count": success,
        "error_count": error,
        "success_rate": (success / total) if total else 0.0,
        "needs_review_rate": (needs_review / total) if total else 0.0,
        "latency": {
            "p50_ms": _percentile(durations, 50),
            "p95_ms": _percentile(durations, 95),
            "min_ms": min(durations) if durations else 0,
            "max_ms": max(durations) if durations else 0,
            "avg_ms": (sum(durations) / len(durations)) if durations else 0,
        },
        # Confidence is intentionally omitted here because the agent's final confidence is not yet exposed
        # as a first-class field. Keep a baseline-compatible shape for dashboards.
        "confidence": {"p50": 0, "p95": 0, "min": 0, "max": 0, "avg": 0},
        "iterations": {"avg": (sum(iters) / len(iters)) if iters else 0, "max": max(iters) if iters else 0},
        "tokens": {
            "total": sum(tokens) if tokens else 0,
            "p50": _percentile(tokens, 50),
            "p95": _percentile(tokens, 95),
            "max": max(tokens) if tokens else 0,
            "avg": (sum(tokens) / len(tokens)) if tokens else 0,
        },
        "verdicts": verdicts_total,
    }


async def _run_one(
    *,
    sample_path: Path,
    provider: str,
    timeout_s: Optional[float],
) -> LiveSampleMetrics:
    data = _load_json(sample_path)
    sample_id = str(data.get("sample_id") or "").strip() or sample_path.stem
    subject = str(data.get("subject") or "").strip().lower()
    inp = data.get("input") or {}
    if not isinstance(inp, dict):
        raise ValueError("missing input object")

    # Import late so script can still lint/run without deps if not executed.
    from homework_agent.models.schemas import ImageRef, Subject
    from homework_agent.services.autonomous_agent import run_autonomous_grade_agent

    refs_raw = _image_refs_from_sample(inp)
    refs = [ImageRef(**r) for r in refs_raw]
    subj = Subject.MATH if subject == "math" else Subject.ENGLISH

    started = time.monotonic()
    try:
        result = await run_autonomous_grade_agent(
            images=refs,
            subject=subj,
            provider=provider,
            session_id=f"live_{sample_id}",
            request_id=f"live_{sample_id}",
            timeout_seconds_override=timeout_s,
            experiments={"collector": {"name": "live_replay", "sample_id": sample_id}},
        )
        duration_ms = int(getattr(result, "duration_ms", 0) or int((time.monotonic() - started) * 1000))
        tokens_total = int(getattr(result, "tokens_used", 0) or 0)
        verdicts = {"correct": 0, "incorrect": 0, "uncertain": 0}
        for r in getattr(result, "results", []) or []:
            v = str((r or {}).get("verdict") or "").strip().lower()
            if v in verdicts:
                verdicts[v] += 1
        return LiveSampleMetrics(
            sample_id=sample_id,
            subject=subject,
            status=str(getattr(result, "status", "") or "done"),
            iterations=int(getattr(result, "iterations", 0) or 0),
            duration_ms=duration_ms,
            tokens_total=tokens_total,
            needs_review=bool(getattr(result, "needs_review", False) or ("needs_review" in (result.warnings or []))),
            verdicts=verdicts,
            warnings=list(getattr(result, "warnings", None) or []),
        )
    except Exception as e:
        duration_ms = int((time.monotonic() - started) * 1000)
        return LiveSampleMetrics(
            sample_id=sample_id,
            subject=subject,
            status="error",
            iterations=0,
            duration_ms=duration_ms,
            tokens_total=0,
            needs_review=True,
            verdicts={"correct": 0, "incorrect": 0, "uncertain": 0},
            warnings=[],
            error=f"{e.__class__.__name__}: {e}",
        )


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Collect live replay metrics (provider calls; optional workflow).")
    parser.add_argument("--samples-dir", type=str, default=str(DEFAULT_SAMPLES_DIR), help="Replay samples directory")
    parser.add_argument("--output", type=str, default="qa_metrics/live_metrics.json", help="Output JSON path")
    parser.add_argument("--provider", type=str, default="ark", choices=["ark", "silicon"], help="LLM provider")
    parser.add_argument("--limit", type=int, default=0, help="Limit samples (0 = all)")
    parser.add_argument("--timeout-seconds", type=float, default=0.0, help="Override per-sample timeout (0 = keep settings)")
    parser.add_argument("--fail-on-error", action="store_true", help="Exit non-zero if any sample errors")
    args = parser.parse_args()

    samples_dir = Path(args.samples_dir)
    if not samples_dir.exists():
        print(f"[WARN] samples dir not found: {samples_dir}")
        return 2
    paths = sorted(samples_dir.glob("*.json"))
    if args.limit and args.limit > 0:
        paths = paths[: int(args.limit)]
    if not paths:
        print(f"[WARN] no samples found: {samples_dir}")
        return 2

    timeout_s = float(args.timeout_seconds) if float(args.timeout_seconds or 0) > 0 else None
    metrics: List[LiveSampleMetrics] = []
    for p in paths:
        metrics.append(await _run_one(sample_path=p, provider=str(args.provider), timeout_s=timeout_s))

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps([asdict(m) for m in metrics], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = _summarize(metrics)
    summary_path = out_path.with_name(out_path.stem + "_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[OK] metrics: {out_path}")
    print(f"[OK] summary: {summary_path}")

    if args.fail_on_error and any(m.status == "error" for m in metrics):
        return 1
    return 0


def main() -> int:
    # Avoid importing provider clients at module import time.
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
