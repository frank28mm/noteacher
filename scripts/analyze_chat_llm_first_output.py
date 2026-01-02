#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


def _extract_json_obj(line: str) -> Optional[Dict[str, Any]]:
    """
    Best-effort parse for our structured log_event JSON lines.
    Supports both:
      - pure JSON lines: {"event":"...","...":...}
      - formatted logs that embed JSON at the end / in message field
    """
    s = (line or "").strip()
    if not s:
        return None
    if s.startswith("{") and s.endswith("}"):
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    # Try to salvage embedded JSON payload.
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _iter_events(paths: Sequence[Path]) -> Iterable[Dict[str, Any]]:
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                obj = _extract_json_obj(line)
                if obj is not None:
                    yield obj


def _percentile(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    if p <= 0:
        return float(min(values))
    if p >= 100:
        return float(max(values))
    vs = sorted(values)
    # Nearest-rank method (1-indexed), stable and easy to reason about.
    k = int(math.ceil((p / 100.0) * len(vs)))
    k = max(1, min(len(vs), k))
    return float(vs[k - 1])


def _ms(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    return f"{v:.0f}ms"


def _sec(v_ms: Optional[float]) -> Optional[float]:
    if v_ms is None:
        return None
    return float(v_ms) / 1000.0


def _choose_bucket(
    *,
    p99_ms: Optional[float],
    buckets_s: Sequence[int],
    safety_margin_s: int,
) -> Optional[int]:
    if p99_ms is None:
        return None
    target = float(_sec(p99_ms) or 0.0) + float(safety_margin_s)
    for b in sorted(set(int(x) for x in buckets_s if int(x) > 0)):
        if target <= b:
            return b
    return None


def _parse_buckets(v: str) -> List[int]:
    out: List[int] = []
    for part in (v or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze structured logs for chat_llm_first_output and suggest CHAT_IDLE_DISCONNECT_SECONDS."
    )
    parser.add_argument(
        "log_paths",
        nargs="*",
        help="Log file paths (default: logs/backend.log if exists).",
    )
    parser.add_argument(
        "--event",
        type=str,
        default="chat_llm_first_output",
        help='Event name to analyze (default: "chat_llm_first_output").',
    )
    parser.add_argument(
        "--field",
        type=str,
        default="first_output_ms",
        help='Latency field in ms (default: "first_output_ms").',
    )
    parser.add_argument(
        "--buckets",
        type=str,
        default="90,120,180",
        help='Candidate thresholds in seconds (comma-separated, default: "90,120,180").',
    )
    parser.add_argument(
        "--safety-margin",
        type=int,
        default=30,
        help="Extra seconds above p99 when choosing a bucket (default: 30).",
    )
    args = parser.parse_args()

    paths = [Path(p) for p in (args.log_paths or []) if str(p).strip()]
    if not paths:
        default = Path("logs/backend.log")
        if default.exists():
            paths = [default]
        else:
            raise SystemExit("No log paths provided and logs/backend.log not found.")

    buckets = _parse_buckets(args.buckets)
    event_name = str(args.event or "").strip()
    field = str(args.field or "").strip()
    if not event_name:
        raise SystemExit("--event must be non-empty")
    if not field:
        raise SystemExit("--field must be non-empty")

    ms_values: List[float] = []
    total = 0
    matched = 0
    for obj in _iter_events(paths):
        total += 1
        if str(obj.get("event") or "") != event_name:
            continue
        matched += 1
        v = obj.get(field)
        try:
            if v is None:
                continue
            ms_values.append(float(v))
        except Exception:
            continue

    if not ms_values:
        print(f"scanned_lines={total}, matched_events={matched}, field_values=0")
        print(f'No usable "{field}" values found for event="{event_name}".')
        return 2

    p50 = _percentile(ms_values, 50)
    p90 = _percentile(ms_values, 90)
    p95 = _percentile(ms_values, 95)
    p99 = _percentile(ms_values, 99)
    vmin = min(ms_values) if ms_values else None
    vmax = max(ms_values) if ms_values else None

    print(f"scanned_lines={total}, matched_events={matched}, field_values={len(ms_values)}")
    print(
        f"{field}: min={_ms(vmin)} p50={_ms(p50)} p90={_ms(p90)} p95={_ms(p95)} p99={_ms(p99)} max={_ms(vmax)}"
    )

    chosen = _choose_bucket(
        p99_ms=p99,
        buckets_s=buckets,
        safety_margin_s=int(args.safety_margin),
    )
    if chosen is None:
        target_s = (_sec(p99) or 0.0) + float(args.safety_margin)
        print(
            f"recommendation: set CHAT_IDLE_DISCONNECT_SECONDS >= ceil(p99_seconds + safety_margin) ~= {math.ceil(target_s)}s"
        )
        if buckets:
            print(f"note: provided buckets={buckets} are all < {math.ceil(target_s)}s")
        return 0

    print(
        f"recommendation: CHAT_IDLE_DISCONNECT_SECONDS={chosen} (buckets={buckets}, safety_margin={int(args.safety_margin)}s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
