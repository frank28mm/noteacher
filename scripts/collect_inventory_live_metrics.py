#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import json
import mimetypes
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Register HEIF/HEIC opener for PIL (iPhone photos often use HEIC even with .jpg extension)
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass  # pillow-heif not available; HEIC files will fail gracefully


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "homework_agent" / "tests" / "replay_data" / "samples_inventory.csv"


def _git_info() -> Dict[str, str]:
    def _run(args: List[str]) -> str:
        try:
            out = subprocess.check_output(args, cwd=str(REPO_ROOT), stderr=subprocess.DEVNULL)
            return out.decode("utf-8", errors="ignore").strip()
        except Exception:
            return ""

    return {
        "git_commit": _run(["git", "rev-parse", "HEAD"]),
        "git_branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
    }


def _read_inventory(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if not r:
                continue
            rows.append({str(k or "").strip(): str(v or "").strip() for k, v in r.items()})
    return rows


def _split_tags(s: str) -> List[str]:
    raw = str(s or "").strip()
    if not raw:
        return []
    for sep in (";", "|", ","):
        if sep in raw:
            return [t.strip() for t in raw.split(sep) if t.strip()]
    return [raw]


def _data_url(mime: str, b: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(b).decode('utf-8')}"


def _load_pdf_pages_as_jpeg_bytes(path: Path, *, max_pages: int = 8, dpi: int = 200) -> List[bytes]:
    try:
        import fitz  # type: ignore
    except Exception as e:
        raise RuntimeError(f"PyMuPDF (fitz) not available for PDF conversion: {e}")

    doc = fitz.open(str(path))
    pages = min(len(doc), int(max_pages))
    if pages <= 0:
        doc.close()
        raise RuntimeError("PDF has no pages")
    outs: List[bytes] = []
    try:
        for i in range(pages):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=int(dpi))
            outs.append(pix.tobytes("jpeg"))
    finally:
        doc.close()
    return outs


def _load_image_as_jpeg_bytes(path: Path, *, quality: int = 95) -> bytes:
    from io import BytesIO

    from PIL import Image

    with Image.open(str(path)) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=int(quality))
        return buf.getvalue()


def _file_to_image_refs(path: Path) -> List[Dict[str, str]]:
    """
    Returns list of ImageRef-like dicts: [{"base64": "data:image/jpeg;base64,..."}]
    Supports: jpg/jpeg/png/webp/heic/heif/avif, pdf (first <=8 pages).
    """
    p = path
    if not p.exists():
        raise FileNotFoundError(str(p))

    ext = p.suffix.lower()
    mime_guess, _ = mimetypes.guess_type(str(p))
    if ext == ".pdf" or mime_guess == "application/pdf":
        pages = _load_pdf_pages_as_jpeg_bytes(p)
        return [{"base64": _data_url("image/jpeg", b)} for b in pages]

    # For HEIC/HEIF/AVIF, pillow-heif is already in deps and registers with PIL.
    jpg = _load_image_as_jpeg_bytes(p)
    return [{"base64": _data_url("image/jpeg", jpg)}]


@dataclass
class InventoryRunMetrics:
    sample_id: str
    subject: str
    status: str
    iterations: int
    duration_ms: int
    tokens_total: int
    needs_review: bool
    verdicts: Dict[str, int]
    warning_codes: List[str]
    tags: List[str]
    input_path: str
    error: Optional[str] = None


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


def _summarize(metrics: List[InventoryRunMetrics], *, eval_meta: Dict[str, Any]) -> Dict[str, Any]:
    total = len(metrics)
    success = sum(1 for m in metrics if m.status == "done")
    error = sum(1 for m in metrics if m.status != "done")
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

    subjects: Dict[str, int] = {}
    tag_counts: Dict[str, int] = {}
    for m in metrics:
        subjects[m.subject] = subjects.get(m.subject, 0) + 1
        for t in m.tags or []:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    out: Dict[str, Any] = {
        "metrics_mode": "live_inventory",
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
        "dataset": {"subjects": subjects, "tags": tag_counts},
    }
    out.update(eval_meta)
    return out


async def _run_one(
    *,
    sample_id: str,
    subject: str,
    image_refs: List[Dict[str, str]],
    provider: str,
    tags: List[str],
    input_path: str,
    timeout_s: Optional[float],
    experiments: Dict[str, Any],
) -> InventoryRunMetrics:
    from homework_agent.models.schemas import ImageRef, Subject  # noqa: WPS433
    from homework_agent.services.autonomous_agent import run_autonomous_grade_agent  # noqa: WPS433

    subj = Subject.MATH if subject == "math" else Subject.ENGLISH
    refs = [ImageRef(**r) for r in image_refs]
    started = time.monotonic()
    try:
        result = await run_autonomous_grade_agent(
            images=refs,
            subject=subj,
            provider=provider,
            session_id=f"inv_{sample_id}",
            request_id=f"inv_{sample_id}",
            timeout_seconds_override=timeout_s,
            experiments=experiments,
        )
        duration_ms = int(getattr(result, "duration_ms", 0) or int((time.monotonic() - started) * 1000))
        tokens_total = int(getattr(result, "tokens_used", 0) or 0)
        verdicts = {"correct": 0, "incorrect": 0, "uncertain": 0}
        for r in getattr(result, "results", []) or []:
            v = str((r or {}).get("verdict") or "").strip().lower()
            if v in verdicts:
                verdicts[v] += 1
        # collect warning codes from tool signals when present
        warning_codes: List[str] = []
        for r in getattr(result, "results", []) or []:
            if isinstance(r, dict):
                for w in (r.get("warnings") or []):
                    ws = str(w or "").strip()
                    if ws:
                        warning_codes.append(ws)
        return InventoryRunMetrics(
            sample_id=sample_id,
            subject=subject,
            status=str(getattr(result, "status", "") or "done"),
            iterations=int(getattr(result, "iterations", 0) or 0),
            duration_ms=duration_ms,
            tokens_total=tokens_total,
            needs_review=bool(getattr(result, "needs_review", False) or ("needs_review" in (result.warnings or []))),
            verdicts=verdicts,
            warning_codes=warning_codes,
            tags=tags,
            input_path=input_path,
        )
    except Exception as e:
        duration_ms = int((time.monotonic() - started) * 1000)
        return InventoryRunMetrics(
            sample_id=sample_id,
            subject=subject,
            status="error",
            iterations=0,
            duration_ms=duration_ms,
            tokens_total=0,
            needs_review=True,
            verdicts={"correct": 0, "incorrect": 0, "uncertain": 0},
            warning_codes=[],
            tags=tags,
            input_path=input_path,
            error=f"{e.__class__.__name__}: {e}",
        )


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Collect live metrics from samples_inventory.csv (local absolute paths).")
    parser.add_argument("--inventory", type=str, default=str(DEFAULT_INVENTORY), help="Path to samples_inventory.csv")
    parser.add_argument("--output", type=str, default="qa_metrics/inventory_live_metrics.json", help="Output metrics JSON path")
    parser.add_argument("--provider", type=str, default="ark", choices=["ark", "silicon"], help="LLM provider")
    parser.add_argument("--limit", type=int, default=0, help="Limit samples (0 = all)")
    parser.add_argument("--timeout-seconds", type=float, default=0.0, help="Override per-sample timeout (0 = keep settings)")
    parser.add_argument("--fail-on-error", action="store_true", help="Exit non-zero if any sample errors")
    args = parser.parse_args()

    inv_path = Path(args.inventory).expanduser().resolve()
    if not inv_path.exists():
        print(f"[FAIL] inventory not found: {inv_path}")
        return 2

    rows = _read_inventory(inv_path)
    if not rows:
        print(f"[FAIL] inventory empty: {inv_path}")
        return 2

    selected = rows[: int(args.limit)] if args.limit and args.limit > 0 else rows
    timeout_s = float(args.timeout_seconds) if float(args.timeout_seconds or 0) > 0 else None

    eval_id = f"eval_inventory_{int(time.time())}"
    git = _git_info()
    eval_meta = {
        "eval_id": eval_id,
        "generated_at": int(time.time()),
        **git,
    }

    metrics: List[InventoryRunMetrics] = []
    for row in selected:
        sample_id = str(row.get("sample_id") or "").strip()
        subject = str(row.get("subject") or "").strip().lower()
        input_type = str(row.get("input_type") or "").strip().lower()
        input_path = str(row.get("input") or "").strip()
        tags = _split_tags(row.get("tags") or "")
        if not sample_id or subject not in {"math", "english"} or input_type != "path" or not input_path:
            metrics.append(
                InventoryRunMetrics(
                    sample_id=sample_id or "<missing>",
                    subject=subject or "<missing>",
                    status="error",
                    iterations=0,
                    duration_ms=0,
                    tokens_total=0,
                    needs_review=True,
                    verdicts={"correct": 0, "incorrect": 0, "uncertain": 0},
                    warning_codes=[],
                    tags=tags,
                    input_path=input_path,
                    error="invalid_inventory_row",
                )
            )
            continue
        p = Path(input_path).expanduser()
        try:
            image_refs = _file_to_image_refs(p)
        except Exception as e:
            metrics.append(
                InventoryRunMetrics(
                    sample_id=sample_id,
                    subject=subject,
                    status="error",
                    iterations=0,
                    duration_ms=0,
                    tokens_total=0,
                    needs_review=True,
                    verdicts={"correct": 0, "incorrect": 0, "uncertain": 0},
                    warning_codes=[],
                    tags=tags,
                    input_path=str(p),
                    error=f"{e.__class__.__name__}: {e}",
                )
            )
            continue

        experiments = {"collector": {"name": "inventory_live_replay", "sample_id": sample_id, **eval_meta}}
        metrics.append(
            await _run_one(
                sample_id=sample_id,
                subject=subject,
                image_refs=image_refs,
                provider=str(args.provider),
                tags=tags,
                input_path=str(p),
                timeout_s=timeout_s,
                experiments=experiments,
            )
        )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps([asdict(m) for m in metrics], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = _summarize(metrics, eval_meta=eval_meta)
    summary_path = out_path.with_name(out_path.stem + "_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[OK] eval_id: {eval_id}")
    print(f"[OK] metrics: {out_path}")
    print(f"[OK] summary: {summary_path}")

    if args.fail_on_error and any(m.status != "done" for m in metrics):
        return 1
    return 0


def main() -> int:
    # Ensure `import homework_agent` works when executed from outside repo root.
    import sys

    sys.path.insert(0, str(REPO_ROOT))
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())

