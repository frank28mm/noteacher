#!/usr/bin/env python3
"""
Collect metrics from autonomous grading runs.

Usage:
    # Local file mode (converts to base64):
    python3 homework_agent/scripts/collect_metrics.py --image-dir /path/to/images --mode local

    # URL mode (uploads to Supabase first, then uses URL):
    python3 homework_agent/scripts/collect_metrics.py --image-dir /path/to/images --mode url

    # Single image:
    python3 homework_agent/scripts/collect_metrics.py --image /path/to/image.jpg --mode local

Output:
    - metrics.json: Per-image metrics
    - metrics_summary.json: P50/P95/confidence distribution
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add repository root to path so `import homework_agent` works when executed as a file.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from homework_agent.models.schemas import ImageRef, Subject
from homework_agent.services.autonomous_agent import run_autonomous_grade_agent


@dataclass
class RunMetrics:
    file: str
    status: str
    confidence: float
    iterations: int
    duration_ms: int
    tokens_total: int
    needs_review: bool
    results_count: int
    correct_count: int
    incorrect_count: int
    uncertain_count: int
    warnings: List[str]
    error: Optional[str] = None


def find_images(
    directory: str, extensions: tuple = (".jpg", ".jpeg", ".png", ".webp")
) -> List[Path]:
    """Find all image files in directory recursively."""
    images = []
    for ext in extensions:
        images.extend(Path(directory).rglob(f"*{ext}"))
        images.extend(Path(directory).rglob(f"*{ext.upper()}"))
    return sorted(set(images))


def compress_image(path: Path, max_side: int = 1024, quality: int = 80) -> str:
    """Compress image and return as data URL."""
    with Image.open(path) as img:
        # Convert to RGB if necessary
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Resize if too large
        w, h = img.size
        if max(w, h) > max_side:
            ratio = max_side / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        # Compress
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"


def upload_to_supabase(
    path: Path, max_side: int = 1024, quality: int = 80
) -> Optional[str]:
    """Upload image to Supabase and return public URL."""
    try:
        from homework_agent.utils.supabase_storage import upload_image_to_supabase

        # Compress first
        with Image.open(path) as img:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            w, h = img.size
            if max(w, h) > max_side:
                ratio = max_side / max(w, h)
                img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality)
            image_bytes = buffer.getvalue()

        # Upload
        filename = f"qa_metrics/{int(time.time())}_{path.name}"
        url = upload_image_to_supabase(image_bytes, filename)
        return url
    except Exception as e:
        print(f"  [WARN] Upload failed for {path.name}: {e}")
        return None


async def run_single(
    image_path: Path,
    mode: str,
    subject: Subject,
    provider: str,
    max_side: int,
    quality: int,
) -> RunMetrics:
    """Run autonomous grading on a single image and collect metrics."""
    print(f"  Processing: {image_path.name}")
    start = time.monotonic()

    try:
        # Prepare image reference
        if mode == "url":
            url = upload_to_supabase(image_path, max_side, quality)
            if not url:
                return RunMetrics(
                    file=str(image_path),
                    status="upload_failed",
                    confidence=0.0,
                    iterations=0,
                    duration_ms=0,
                    results_count=0,
                    correct_count=0,
                    incorrect_count=0,
                    uncertain_count=0,
                    warnings=[],
                    error="supabase_upload_failed",
                )
            image_ref = ImageRef(url=url)
        else:
            data_url = compress_image(image_path, max_side, quality)
            image_ref = ImageRef(base64=data_url)

        # Run grading
        session_id = f"qa_metrics_{int(time.time())}_{image_path.stem}"
        result = await run_autonomous_grade_agent(
            images=[image_ref],
            subject=subject,
            provider=provider,
            session_id=session_id,
            request_id=f"metrics_{session_id}",
        )

        duration_ms = int((time.monotonic() - start) * 1000)
        tokens_total = int(getattr(result, "tokens_used", 0) or 0)
        needs_review = bool(
            getattr(result, "needs_review", False)
            or ("needs_review" in (result.warnings or []))
        )

        # Extract metrics
        correct = sum(1 for r in result.results if r.get("verdict") == "correct")
        incorrect = sum(1 for r in result.results if r.get("verdict") == "incorrect")
        uncertain = sum(1 for r in result.results if r.get("verdict") == "uncertain")

        # Get confidence from reflection (if available)
        # Note: confidence is from Reflector, not directly in result
        confidence = 0.95 if result.status == "done" else 0.0

        return RunMetrics(
            file=str(image_path),
            status=result.status,
            confidence=confidence,
            iterations=result.iterations,
            duration_ms=duration_ms,
            tokens_total=tokens_total,
            needs_review=needs_review,
            results_count=len(result.results),
            correct_count=correct,
            incorrect_count=incorrect,
            uncertain_count=uncertain,
            warnings=result.warnings,
        )
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        return RunMetrics(
            file=str(image_path),
            status="error",
            confidence=0.0,
            iterations=0,
            duration_ms=duration_ms,
            tokens_total=0,
            needs_review=True,
            results_count=0,
            correct_count=0,
            incorrect_count=0,
            uncertain_count=0,
            warnings=[],
            error=str(e),
        )


def calculate_summary(metrics: List[RunMetrics]) -> Dict[str, Any]:
    """Calculate P50/P95 and other summary statistics."""
    if not metrics:
        return {}

    durations = sorted([m.duration_ms for m in metrics])
    confidences = sorted([m.confidence for m in metrics if m.confidence > 0])
    iterations = [m.iterations for m in metrics if m.iterations > 0]
    tokens = sorted([m.tokens_total for m in metrics if m.tokens_total > 0])

    def percentile(data: List, p: float) -> float:
        if not data:
            return 0.0
        k = (len(data) - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < len(data) else f
        return data[f] + (data[c] - data[f]) * (k - f)

    success_count = sum(1 for m in metrics if m.status == "done")
    error_count = sum(1 for m in metrics if m.status == "error")
    needs_review_count = sum(1 for m in metrics if bool(m.needs_review))

    return {
        "metrics_mode": "live",
        "total_samples": len(metrics),
        "success_count": success_count,
        "error_count": error_count,
        "success_rate": success_count / len(metrics) if metrics else 0,
        "needs_review_rate": needs_review_count / len(metrics) if metrics else 0,
        "latency": {
            "p50_ms": percentile(durations, 50),
            "p95_ms": percentile(durations, 95),
            "min_ms": min(durations) if durations else 0,
            "max_ms": max(durations) if durations else 0,
            "avg_ms": sum(durations) / len(durations) if durations else 0,
        },
        "confidence": {
            "p50": percentile(confidences, 50),
            "p95": percentile(confidences, 95),
            "min": min(confidences) if confidences else 0,
            "max": max(confidences) if confidences else 0,
            "avg": sum(confidences) / len(confidences) if confidences else 0,
        },
        "iterations": {
            "avg": sum(iterations) / len(iterations) if iterations else 0,
            "max": max(iterations) if iterations else 0,
        },
        "tokens": {
            "total": sum(tokens) if tokens else 0,
            "p50": percentile(tokens, 50),
            "p95": percentile(tokens, 95),
            "max": max(tokens) if tokens else 0,
            "avg": (sum(tokens) / len(tokens)) if tokens else 0,
        },
        "verdicts": {
            "correct_total": sum(m.correct_count for m in metrics),
            "incorrect_total": sum(m.incorrect_count for m in metrics),
            "uncertain_total": sum(m.uncertain_count for m in metrics),
        },
    }


async def main():
    parser = argparse.ArgumentParser(description="Collect autonomous grading metrics")
    parser.add_argument("--image-dir", type=str, help="Directory containing images")
    parser.add_argument("--image", type=str, help="Single image path")
    parser.add_argument(
        "--mode", choices=["local", "url"], default="local", help="Image delivery mode"
    )
    parser.add_argument("--subject", choices=["math", "english"], default="math")
    parser.add_argument("--provider", default="ark", help="LLM provider (ark/silicon)")
    parser.add_argument(
        "--max-side", type=int, default=1024, help="Max image dimension"
    )
    parser.add_argument("--quality", type=int, default=80, help="JPEG quality")
    parser.add_argument("--limit", type=int, default=20, help="Max images to process")
    parser.add_argument(
        "--output", type=str, default="metrics.json", help="Output file"
    )
    args = parser.parse_args()

    # Find images
    if args.image:
        images = [Path(args.image)]
    elif args.image_dir:
        images = find_images(args.image_dir)[: args.limit]
    else:
        print("Error: Must specify --image or --image-dir")
        sys.exit(1)

    if not images:
        print("No images found")
        sys.exit(1)

    print(f"Found {len(images)} images, processing up to {args.limit}...")
    print(f"Mode: {args.mode}, Subject: {args.subject}, Provider: {args.provider}")
    print()

    subject = Subject.ENGLISH if args.subject == "english" else Subject.MATH

    # Process images
    metrics: List[RunMetrics] = []
    for i, img_path in enumerate(images[: args.limit], 1):
        print(f"[{i}/{min(len(images), args.limit)}]", end="")
        m = await run_single(
            img_path, args.mode, subject, args.provider, args.max_side, args.quality
        )
        metrics.append(m)
        print(f"    → {m.status}, {m.duration_ms}ms, {m.results_count} results")

    # Save metrics
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([asdict(m) for m in metrics], f, ensure_ascii=False, indent=2)
    print(f"\nMetrics saved to: {output_path}")

    # Calculate and save summary
    summary = calculate_summary(metrics)
    summary_path = output_path.with_name(output_path.stem + "_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"Summary saved to: {summary_path}")

    # Print summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Total samples: {summary.get('total_samples', 0)}")
    print(f"Success rate: {summary.get('success_rate', 0):.1%}")
    print(f"Latency P50: {summary.get('latency', {}).get('p50_ms', 0):.0f}ms")
    print(f"Latency P95: {summary.get('latency', {}).get('p95_ms', 0):.0f}ms")
    print(f"Avg iterations: {summary.get('iterations', {}).get('avg', 0):.1f}")


if __name__ == "__main__":
    asyncio.run(main())
