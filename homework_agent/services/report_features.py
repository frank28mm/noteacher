from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


FEATURES_VERSION = "features_v1"


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_list(v: Any) -> List[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        return [v]
    return [v]


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for s in items:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _safe_div(n: int, d: int) -> Optional[float]:
    if d <= 0:
        return None
    return float(n) / float(d)


def _bucket_key(*, question_type: str, difficulty: str) -> str:
    return f"{question_type}::{difficulty}"


def compute_report_features(
    *,
    user_id: str,
    attempts: List[Dict[str, Any]],
    steps: List[Dict[str, Any]],
    window: Dict[str, Any],
    taxonomy_version: Optional[str],
    classifier_version: Optional[str],
) -> Dict[str, Any]:
    """
    Deterministic features layer (no LLM counting).

    Requirements:
    - All numbers come from this computation
    - Include sample_size for any rate
    """
    uid = str(user_id or "").strip()
    now = _iso_utc_now()

    total = len(attempts)
    correct = sum(1 for a in attempts if (a.get("verdict") or "").strip().lower() == "correct")
    incorrect = sum(1 for a in attempts if (a.get("verdict") or "").strip().lower() == "incorrect")
    uncertain = sum(1 for a in attempts if (a.get("verdict") or "").strip().lower() == "uncertain")

    # Knowledge mastery (tag-level accuracy)
    tag_stats: Dict[str, Dict[str, int]] = {}
    for a in attempts:
        verdict = (a.get("verdict") or "").strip().lower()
        tags = _coerce_list(a.get("knowledge_tags_norm") or a.get("knowledge_tags"))
        for t in tags:
            ts = str(t).strip()
            if not ts:
                continue
            s = tag_stats.setdefault(ts, {"total": 0, "correct": 0, "incorrect": 0, "uncertain": 0})
            s["total"] += 1
            if verdict == "correct":
                s["correct"] += 1
            elif verdict == "incorrect":
                s["incorrect"] += 1
            elif verdict == "uncertain":
                s["uncertain"] += 1

    tag_rows = []
    for tag, s in tag_stats.items():
        acc = _safe_div(s["correct"], s["total"])
        tag_rows.append(
            {
                "tag": tag,
                "sample_size": s["total"],
                "correct": s["correct"],
                "incorrect": s["incorrect"],
                "uncertain": s["uncertain"],
                "accuracy": acc,
                "error_rate": _safe_div(s["incorrect"] + s["uncertain"], s["total"]),
            }
        )
    tag_rows.sort(key=lambda r: (r["accuracy"] is not None, r.get("accuracy") or 0.0))

    # Type x difficulty matrix
    bucket_stats: Dict[str, Dict[str, int]] = {}
    for a in attempts:
        verdict = (a.get("verdict") or "").strip().lower()
        qtype = str(a.get("question_type") or "unknown").strip() or "unknown"
        diff = str(a.get("difficulty") or "unknown").strip() or "unknown"
        key = _bucket_key(question_type=qtype, difficulty=diff)
        s = bucket_stats.setdefault(key, {"total": 0, "correct": 0, "incorrect": 0, "uncertain": 0})
        s["total"] += 1
        if verdict == "correct":
            s["correct"] += 1
        elif verdict == "incorrect":
            s["incorrect"] += 1
        elif verdict == "uncertain":
            s["uncertain"] += 1

    bucket_rows = []
    for key, s in bucket_stats.items():
        qtype, diff = key.split("::", 1)
        bucket_rows.append(
            {
                "question_type": qtype,
                "difficulty": diff,
                "sample_size": s["total"],
                "correct": s["correct"],
                "incorrect": s["incorrect"],
                "uncertain": s["uncertain"],
                "accuracy": _safe_div(s["correct"], s["total"]),
            }
        )
    bucket_rows.sort(key=lambda r: (r["accuracy"] is not None, r.get("accuracy") or 0.0))

    # Process diagnosis from steps
    sev_counts: Dict[str, int] = {}
    diagnosis_counts: Dict[str, int] = {}
    for s in steps:
        sev = str(s.get("severity") or "unknown").strip().lower() or "unknown"
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
        for code in _coerce_list(s.get("diagnosis_codes")):
            cs = str(code).strip()
            if not cs:
                continue
            diagnosis_counts[cs] = diagnosis_counts.get(cs, 0) + 1

    # Evidence sampling: pick a few incorrect attempts (stable ordering by created_at desc if present)
    def _sort_key(a: Dict[str, Any]) -> Tuple[int, str]:
        v = (a.get("verdict") or "").strip().lower()
        # incorrect first, then uncertain
        pri = 0 if v == "incorrect" else 1 if v == "uncertain" else 2
        ts = str(a.get("created_at") or "")
        return (pri, ts)

    incorrectish = [a for a in attempts if (a.get("verdict") or "").strip().lower() in {"incorrect", "uncertain"}]
    incorrectish.sort(key=_sort_key)
    evidence = []
    for a in incorrectish[:20]:
        evidence.append(
            {
                "submission_id": a.get("submission_id"),
                "item_id": a.get("item_id"),
                "question_number": a.get("question_number"),
                "verdict": a.get("verdict"),
                "knowledge_tags": _dedupe_keep_order([str(t).strip() for t in _coerce_list(a.get("knowledge_tags_norm") or []) if str(t).strip()])[:10],
            }
        )

    return {
        "features_version": FEATURES_VERSION,
        "generated_at": now,
        "user_id": uid,
        "window": window,
        "taxonomy_version": taxonomy_version,
        "classifier_version": classifier_version,
        "overall": {
            "sample_size": total,
            "correct": correct,
            "incorrect": incorrect,
            "uncertain": uncertain,
            "accuracy": _safe_div(correct, total),
            "error_rate": _safe_div(incorrect + uncertain, total),
        },
        "knowledge_mastery": {
            "rows": tag_rows[:200],
        },
        "type_difficulty": {
            "rows": bucket_rows[:200],
        },
        "process_diagnosis": {
            "steps_sample_size": len(steps),
            "severity_counts": sev_counts,
            "diagnosis_code_counts": diagnosis_counts,
        },
        "evidence_refs": evidence,
    }

