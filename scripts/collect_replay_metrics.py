#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
REPLAY_SAMPLES_DIR = REPO_ROOT / "homework_agent" / "tests" / "replay_data" / "samples"


@dataclass
class SampleMetrics:
    sample_id: str
    subject: str
    status: str
    tags: List[str]
    has_local_images: bool
    has_image_urls: bool
    has_or_base64: bool
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


def _validate_sample_schema(data: Dict[str, Any], *, path: Path) -> None:
    sid = data.get("sample_id")
    if not isinstance(sid, str) or not sid.strip():
        raise ValueError("missing sample_id")
    subject = str(data.get("subject") or "").strip().lower()
    if subject not in {"math", "english"}:
        raise ValueError(f"invalid subject: {subject}")
    inp = data.get("input")
    if not isinstance(inp, dict):
        raise ValueError("missing input object")
    local_images = inp.get("local_images")
    image_urls = inp.get("image_urls")
    or_base64 = inp.get("or_base64")
    if not (local_images or image_urls or or_base64):
        raise ValueError("input must include one of local_images/image_urls/or_base64")
    expected_output = data.get("expected_output")
    if expected_output is not None and not isinstance(expected_output, dict):
        raise ValueError("expected_output must be object if provided")


def collect_metrics(samples_dir: Path) -> List[SampleMetrics]:
    if not samples_dir.exists():
        return []
    metrics: List[SampleMetrics] = []
    for p in sorted(samples_dir.glob("*.json")):
        try:
            data = _load_json(p)
            _validate_sample_schema(data, path=p)
            inp = data.get("input") or {}
            tags = _as_list(data.get("tags") or [])
            metrics.append(
                SampleMetrics(
                    sample_id=str(data.get("sample_id")),
                    subject=str(data.get("subject")),
                    status="ok",
                    tags=tags,
                    has_local_images=bool(inp.get("local_images")),
                    has_image_urls=bool(inp.get("image_urls")),
                    has_or_base64=bool(inp.get("or_base64")),
                )
            )
        except Exception as e:
            # Best-effort: keep a record so the report still writes.
            sid = None
            try:
                sid = str(_load_json(p).get("sample_id") or "").strip() or p.stem
            except Exception:
                sid = p.stem
            metrics.append(
                SampleMetrics(
                    sample_id=sid,
                    subject="unknown",
                    status="error",
                    tags=[],
                    has_local_images=False,
                    has_image_urls=False,
                    has_or_base64=False,
                    error=str(e),
                )
            )
    return metrics


def summarize(metrics: List[SampleMetrics]) -> Dict[str, Any]:
    total = len(metrics)
    success = sum(1 for m in metrics if m.status == "ok")
    error = sum(1 for m in metrics if m.status != "ok")
    subjects: Dict[str, int] = {}
    tag_counts: Dict[str, int] = {}
    for m in metrics:
        subjects[m.subject] = subjects.get(m.subject, 0) + 1
        for t in m.tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    # Keep a baseline-compatible shape for scripts/check_baseline.py
    git_commit = ""
    git_branch = ""
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore").strip()  # noqa: E501
        git_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(REPO_ROOT), stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore").strip()  # noqa: E501
    except Exception:
        pass

    eval_id = f"eval_offline_{int(time.time())}"
    return {
        "eval_id": eval_id,
        "generated_at": int(time.time()),
        "git_commit": git_commit,
        "git_branch": git_branch,
        "metrics_mode": "offline",
        "total_samples": total,
        "success_count": success,
        "error_count": error,
        "success_rate": (success / total) if total else 0.0,
        "latency": {"p50_ms": 0, "p95_ms": 0, "min_ms": 0, "max_ms": 0, "avg_ms": 0},
        "confidence": {"p50": 0, "p95": 0, "min": 0, "max": 0, "avg": 0},
        "iterations": {"avg": 0, "max": 0},
        "verdicts": {"correct_total": 0, "incorrect_total": 0, "uncertain_total": 0},
        "dataset": {"subjects": subjects, "tags": tag_counts},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect offline replay dataset metrics (no provider calls).")
    parser.add_argument("--samples-dir", type=str, default=str(REPLAY_SAMPLES_DIR), help="Replay samples directory")
    parser.add_argument("--output", type=str, default="qa_metrics/metrics.json", help="Output JSON path")
    args = parser.parse_args()

    samples_dir = Path(args.samples_dir)
    metrics = collect_metrics(samples_dir)
    if not metrics:
        print(f"[WARN] No replay samples found at: {samples_dir}")
        return 2

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps([asdict(m) for m in metrics], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = summarize(metrics)
    summary_path = output_path.with_name(output_path.stem + "_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[OK] metrics: {output_path}")
    print(f"[OK] summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
