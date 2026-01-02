#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return data


def _get(d: Dict[str, Any], key: str) -> Optional[float]:
    cur: Any = d
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur.get(part)
    try:
        if cur is None:
            return None
        return float(cur)
    except Exception:
        return None


def _derive_uncertain_rate(summary: Dict[str, Any]) -> Optional[float]:
    v = summary.get("verdicts")
    if not isinstance(v, dict):
        return None
    try:
        correct = float(v.get("correct_total") or 0)
        incorrect = float(v.get("incorrect_total") or 0)
        uncertain = float(v.get("uncertain_total") or 0)
        total = correct + incorrect + uncertain
        if total <= 0:
            return None
        return uncertain / total
    except Exception:
        return None


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    current: Optional[float]
    baseline: Optional[float]
    detail: str


def _pct(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    return f"{x:.1%}"


def _ms(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    return f"{x:.0f}ms"


def _num(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    if math.isfinite(x) and abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.3f}"


def run_checks(
    *,
    current: Dict[str, Any],
    baseline: Dict[str, Any],
    rate_tolerance: float,
    latency_multiplier: float,
    iterations_multiplier: float,
) -> List[CheckResult]:
    results: List[CheckResult] = []

    # Offline dataset integrity checks (CI-safe).
    cur_mode = str(current.get("metrics_mode") or "").strip().lower()
    base_mode = str(baseline.get("metrics_mode") or "").strip().lower()
    if cur_mode == "offline" and base_mode == "offline":
        cur_total = _get(current, "total_samples")
        base_total = _get(baseline, "total_samples")
        if cur_total is not None and base_total is not None:
            passed = cur_total >= base_total
            results.append(
                CheckResult(
                    name="total_samples_no_shrink",
                    passed=passed,
                    current=cur_total,
                    baseline=base_total,
                    detail=f"current={_num(cur_total)}, baseline={_num(base_total)} (must_not_shrink)",
                )
            )
        cur_err = _get(current, "error_count")
        base_err = _get(baseline, "error_count")
        if cur_err is not None:
            # Keep it strict for offline: schema errors should be 0.
            passed = cur_err <= 0
            results.append(
                CheckResult(
                    name="error_count",
                    passed=passed,
                    current=cur_err,
                    baseline=base_err,
                    detail=f"current={_num(cur_err)} (must_be_0)",
                )
            )

    cur_success = _get(current, "success_rate")
    base_success = _get(baseline, "success_rate")
    if cur_success is not None and base_success is not None:
        passed = cur_success >= (base_success - rate_tolerance)
        results.append(
            CheckResult(
                name="success_rate",
                passed=passed,
                current=cur_success,
                baseline=base_success,
                detail=f"current={_pct(cur_success)}, baseline={_pct(base_success)}, allow_drop={_pct(rate_tolerance)}",
            )
        )

    cur_needs_review = _get(current, "needs_review_rate")
    base_needs_review = _get(baseline, "needs_review_rate")
    if cur_needs_review is not None and base_needs_review is not None:
        passed = cur_needs_review <= (base_needs_review + rate_tolerance)
        results.append(
            CheckResult(
                name="needs_review_rate",
                passed=passed,
                current=cur_needs_review,
                baseline=base_needs_review,
                detail=f"current={_pct(cur_needs_review)}, baseline={_pct(base_needs_review)}, allow_rise={_pct(rate_tolerance)}",
            )
        )

    cur_uncertain = _derive_uncertain_rate(current)
    base_uncertain = _derive_uncertain_rate(baseline)
    if cur_uncertain is not None and base_uncertain is not None:
        passed = cur_uncertain <= (base_uncertain + rate_tolerance)
        results.append(
            CheckResult(
                name="uncertain_rate",
                passed=passed,
                current=cur_uncertain,
                baseline=base_uncertain,
                detail=f"current={_pct(cur_uncertain)}, baseline={_pct(base_uncertain)}, allow_rise={_pct(rate_tolerance)}",
            )
        )

    cur_p95 = _get(current, "latency.p95_ms")
    base_p95 = _get(baseline, "latency.p95_ms")
    if cur_p95 is not None and base_p95 is not None and base_p95 > 0:
        limit = base_p95 * latency_multiplier
        passed = cur_p95 <= limit
        results.append(
            CheckResult(
                name="latency.p95_ms",
                passed=passed,
                current=cur_p95,
                baseline=base_p95,
                detail=f"current={_ms(cur_p95)}, baseline={_ms(base_p95)}, limit={_ms(limit)} (x{latency_multiplier:.2f})",
            )
        )

    cur_iter = _get(current, "iterations.avg")
    base_iter = _get(baseline, "iterations.avg")
    if cur_iter is not None and base_iter is not None and base_iter > 0:
        limit = base_iter * iterations_multiplier
        passed = cur_iter <= limit
        results.append(
            CheckResult(
                name="iterations.avg",
                passed=passed,
                current=cur_iter,
                baseline=base_iter,
                detail=f"current={_num(cur_iter)}, baseline={_num(base_iter)}, limit={_num(limit)} (x{iterations_multiplier:.2f})",
            )
        )

    cur_tokens_p95 = _get(current, "tokens.p95")
    base_tokens_p95 = _get(baseline, "tokens.p95")
    if cur_tokens_p95 is not None and base_tokens_p95 is not None and base_tokens_p95 > 0:
        limit = base_tokens_p95 * iterations_multiplier
        passed = cur_tokens_p95 <= limit
        results.append(
            CheckResult(
                name="tokens.p95",
                passed=passed,
                current=cur_tokens_p95,
                baseline=base_tokens_p95,
                detail=f"current={_num(cur_tokens_p95)}, baseline={_num(base_tokens_p95)}, limit={_num(limit)} (x{iterations_multiplier:.2f})",
            )
        )

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Check regression against a baseline metrics summary.")
    parser.add_argument("--current", type=str, required=True, help="Path to current metrics_summary.json")
    parser.add_argument("--baseline", type=str, required=True, help="Path to baseline metrics_summary.json")
    parser.add_argument("--rate-tolerance", type=float, default=0.05, help="Allowed absolute change for rates (default: 0.05)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Alias for --rate-tolerance (kept for backward-compatible docs).",
    )
    parser.add_argument("--latency-multiplier", type=float, default=1.2, help="Allowed latency multiplier (default: 1.2)")
    parser.add_argument(
        "--iterations-multiplier",
        type=float,
        default=1.2,
        help="Allowed iterations multiplier (default: 1.2)",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Overwrite baseline with current summary and exit 0 (useful for refreshing baseline).",
    )
    parser.add_argument(
        "--allow-missing-baseline",
        action="store_true",
        help="If baseline file is missing, print a warning and exit 0.",
    )
    args = parser.parse_args()

    current_path = Path(args.current)
    baseline_path = Path(args.baseline)
    if not current_path.exists():
        print(f"[FAIL] current summary not found: {current_path}")
        return 2

    if not baseline_path.exists():
        if args.allow_missing_baseline:
            print(f"[WARN] baseline not found, skipping regression check: {baseline_path}")
            return 0
        print(f"[FAIL] baseline not found: {baseline_path}")
        print("       Tip: run with --update-baseline to create it from current.")
        return 2

    current = _load_json(current_path)
    baseline = _load_json(baseline_path)

    if args.update_baseline:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[OK] baseline updated: {baseline_path}")
        return 0

    checks = run_checks(
        current=current,
        baseline=baseline,
        rate_tolerance=float(args.threshold if args.threshold is not None else args.rate_tolerance),
        latency_multiplier=float(args.latency_multiplier),
        iterations_multiplier=float(args.iterations_multiplier),
    )

    if not checks:
        print("[WARN] No comparable metrics found between current and baseline.")
        print(f"       current: {current_path}")
        print(f"       baseline: {baseline_path}")
        return 0

    failed = [c for c in checks if not c.passed]
    for c in checks:
        status = "OK" if c.passed else "FAIL"
        print(f"[{status}] {c.name}: {c.detail}")

    if failed:
        print(f"\n[FAIL] Regression detected: {len(failed)} check(s) failed.")
        return 1
    print("\n[OK] No regression detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
