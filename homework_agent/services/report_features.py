from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

FEATURES_VERSION = "features_v2"

SEVERITY_ORDER = ["calculation", "concept", "format", "unknown"]

CAUSE_DEFINITIONS_V0: Dict[str, Dict[str, str]] = {
    "calculation": {
        "display_name_cn": "计算错误",
        "standard": "计算过程出现算术/代数运算失误（如加减乘除、移项、符号、约分等），概念本身可能正确。",
    },
    "concept": {
        "display_name_cn": "概念错误",
        "standard": "对知识点/定理/定义理解或应用不当（如公式用错、条件漏用、概念混淆）。",
    },
    "format": {
        "display_name_cn": "格式/书写问题",
        "standard": "答案或步骤的表达格式不规范（如单位/符号/书写不清、未按要求作答），导致判定困难或不符合题目要求。",
    },
    "unknown": {
        "display_name_cn": "未分类",
        "standard": "当前证据不足以稳定归类到以上类型，或题目/答案信息缺失（例如未作答/图片不清）。",
    },
}


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


def _parse_iso_utc(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _is_wrongish(verdict: Any) -> bool:
    v = str(verdict or "").strip().lower()
    return v in {"incorrect", "uncertain"}


def _coerce_severity(v: Any) -> str:
    s = str(v or "").strip().lower()
    return s or "unknown"


def _attempt_cause(a: Dict[str, Any]) -> str:
    """
    Best-effort attempt-level "cause" (severity) for report aggregation.
    Priority:
    1) persisted attempt.severity
    2) attempt.question_raw.severity / math_steps[].severity
    3) infer from question_raw.reason / judgment_basis / answer_state
    """
    sev0 = str(a.get("severity") or "").strip().lower()
    if sev0:
        return sev0

    qraw = a.get("question_raw")
    if isinstance(qraw, dict):
        sev1 = str(qraw.get("severity") or "").strip().lower()
        if sev1:
            return sev1
        steps = qraw.get("math_steps")
        if isinstance(steps, list):
            for s in steps:
                if not isinstance(s, dict):
                    continue
                ssev = str(s.get("severity") or "").strip().lower()
                if ssev:
                    return ssev

        answer_state = str(qraw.get("answer_state") or "").strip().lower()
        if answer_state == "blank":
            return "unknown"
        reason = str(qraw.get("reason") or "").strip()
        judgment_basis = str(qraw.get("judgment_basis") or "").strip()
        text = f"{reason}\n{judgment_basis}".strip()
        if text:
            if any(
                k in text
                for k in (
                    "未作答",
                    "未填写",
                    "空白",
                    "看不清",
                    "识别不清",
                    "无法判定",
                    "证据不足",
                )
            ):
                return "unknown"
            if any(
                k in text
                for k in (
                    "计算",
                    "算错",
                    "运算",
                    "符号",
                    "移项",
                    "约分",
                    "通分",
                    "合并同类项",
                    "展开",
                    "乘除",
                    "加减",
                    "代入",
                )
            ):
                return "calculation"
            if any(
                k in text
                for k in (
                    "步骤",
                    "过程",
                    "格式",
                    "书写",
                    "单位",
                    "未按要求",
                    "表达不清",
                    "写法",
                    "漏写",
                )
            ):
                return "format"
            return "concept"

    return "unknown"


def _dedupe_str_list(values: Any) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in _coerce_list(values):
        s = str(item).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _pick_top_k(
    *,
    counts: Dict[str, int],
    k: int,
    prefer_order: Optional[List[str]] = None,
) -> List[str]:
    def sort_key(item: Tuple[str, int]) -> Tuple[int, int, str]:
        key, count = item
        # Higher count first
        neg_count = -int(count)
        # Stable preferred ordering (e.g. known severities)
        pref_rank = 10**9
        if prefer_order and key in prefer_order:
            pref_rank = prefer_order.index(key)
        return (neg_count, pref_rank, key)

    items = [(str(k0), int(v0)) for k0, v0 in (counts or {}).items()]
    items.sort(key=sort_key)
    return [k0 for k0, _ in items[: int(k)]]


def _compute_trends(
    *,
    attempts: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Compute time-series trend points for Reporter UI.

    Rules (C-7):
    - wrong count = verdict in {incorrect, uncertain}
    - selected tags = global Top5 by wrong count
    - selected causes = global Top3 by wrong count (attempt-level severity)
    - granularity: submission if distinct submissions <= 15 else bucket_3d

    Notes:
    - Include per-point totals so the UI can render accuracy trends without
      re-querying attempts.
    """
    if not attempts:
        return None

    # Distinct submissions + timestamps
    submission_ts: Dict[str, datetime] = {}
    for a in attempts:
        sid = str(a.get("submission_id") or "").strip()
        if not sid:
            continue
        dt = _parse_iso_utc(a.get("created_at"))
        if not dt:
            continue
        # Keep earliest timestamp per submission for ordering
        if sid not in submission_ts or dt < submission_ts[sid]:
            submission_ts[sid] = dt

    distinct_submission_ids = sorted(
        submission_ts.keys(), key=lambda s: submission_ts[s]
    )
    distinct_submission_count = len(distinct_submission_ids)
    if distinct_submission_count <= 0:
        return None

    # Global wrong counts for tag/cause selection
    tag_wrong_counts: Dict[str, int] = {}
    cause_wrong_counts: Dict[str, int] = {}
    for a in attempts:
        if not _is_wrongish(a.get("verdict")):
            continue
        for tag in _dedupe_str_list(
            a.get("knowledge_tags_norm") or a.get("knowledge_tags")
        ):
            tag_wrong_counts[tag] = tag_wrong_counts.get(tag, 0) + 1
        sev = _attempt_cause(a)
        cause_wrong_counts[sev] = cause_wrong_counts.get(sev, 0) + 1

    selected_tags = _pick_top_k(counts=tag_wrong_counts, k=5)
    selected_causes = _pick_top_k(
        counts=cause_wrong_counts, k=3, prefer_order=SEVERITY_ORDER
    )

    # Prepare per-point aggregation
    if distinct_submission_count <= 15:
        granularity = "submission"
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for a in attempts:
            sid = str(a.get("submission_id") or "").strip()
            if not sid:
                continue
            groups.setdefault(sid, []).append(a)

        points = []
        for sid in distinct_submission_ids:
            rows = groups.get(sid, [])
            wrong_by_tag = {t: 0 for t in selected_tags}
            wrong_by_cause = {c: 0 for c in selected_causes}
            total = 0
            correct = 0
            incorrect = 0
            uncertain = 0
            min_dt: Optional[datetime] = None
            max_dt: Optional[datetime] = None
            for a in rows:
                dt = _parse_iso_utc(a.get("created_at"))
                if dt:
                    min_dt = dt if min_dt is None or dt < min_dt else min_dt
                    max_dt = dt if max_dt is None or dt > max_dt else max_dt

                total += 1
                v = str(a.get("verdict") or "").strip().lower()
                if v == "correct":
                    correct += 1
                elif v == "incorrect":
                    incorrect += 1
                elif v == "uncertain":
                    uncertain += 1

                if not _is_wrongish(v):
                    continue
                tags = _dedupe_str_list(
                    a.get("knowledge_tags_norm") or a.get("knowledge_tags")
                )
                for t in selected_tags:
                    if t in tags:
                        wrong_by_tag[t] += 1
                sev = _attempt_cause(a)
                if sev in wrong_by_cause:
                    wrong_by_cause[sev] += 1
            wrong_total = int(incorrect + uncertain)
            points.append(
                {
                    "point_key": sid,
                    "since": min_dt.isoformat() if min_dt else None,
                    "until": max_dt.isoformat() if max_dt else None,
                    "sample_size": int(total),
                    "correct": int(correct),
                    "incorrect": int(incorrect),
                    "uncertain": int(uncertain),
                    "accuracy": _safe_div(int(correct), int(total)),
                    "error_rate": _safe_div(int(wrong_total), int(total)),
                    "knowledge_top5": wrong_by_tag,
                    "cause_top3": wrong_by_cause,
                }
            )
    else:
        granularity = "bucket_3d"
        # Base day is earliest submission day in UTC.
        base_dt = submission_ts[distinct_submission_ids[0]]
        base_day = base_dt.date()

        def bucket_bounds(d: date) -> Tuple[datetime, datetime]:
            since = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            until = since + timedelta(days=3) - timedelta(seconds=1)
            return since, until

        buckets: Dict[date, List[Dict[str, Any]]] = {}
        for a in attempts:
            dt = _parse_iso_utc(a.get("created_at"))
            if not dt:
                continue
            day = dt.date()
            offset = (day - base_day).days
            if offset < 0:
                idx = 0
            else:
                idx = int(offset) // 3
            b0 = base_day + timedelta(days=idx * 3)
            buckets.setdefault(b0, []).append(a)

        points = []
        for b0 in sorted(buckets.keys()):
            rows = buckets[b0]
            wrong_by_tag = {t: 0 for t in selected_tags}
            wrong_by_cause = {c: 0 for c in selected_causes}
            since_dt, until_dt = bucket_bounds(b0)
            total = 0
            correct = 0
            incorrect = 0
            uncertain = 0
            for a in rows:
                total += 1
                v = str(a.get("verdict") or "").strip().lower()
                if v == "correct":
                    correct += 1
                elif v == "incorrect":
                    incorrect += 1
                elif v == "uncertain":
                    uncertain += 1

                if not _is_wrongish(v):
                    continue
                tags = _dedupe_str_list(
                    a.get("knowledge_tags_norm") or a.get("knowledge_tags")
                )
                for t in selected_tags:
                    if t in tags:
                        wrong_by_tag[t] += 1
                sev = _attempt_cause(a)
                if sev in wrong_by_cause:
                    wrong_by_cause[sev] += 1
            end_day = (b0 + timedelta(days=2)).isoformat()
            wrong_total = int(incorrect + uncertain)
            points.append(
                {
                    "point_key": f"{b0.isoformat()}~{end_day}",
                    "since": since_dt.isoformat(),
                    "until": until_dt.isoformat(),
                    "sample_size": int(total),
                    "correct": int(correct),
                    "incorrect": int(incorrect),
                    "uncertain": int(uncertain),
                    "accuracy": _safe_div(int(correct), int(total)),
                    "error_rate": _safe_div(int(wrong_total), int(total)),
                    "knowledge_top5": wrong_by_tag,
                    "cause_top3": wrong_by_cause,
                }
            )

    return {
        "granularity": granularity,
        "points": points,
        "selected_knowledge_tags": selected_tags,
        "selected_causes": selected_causes,
    }


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
    correct = sum(
        1 for a in attempts if (a.get("verdict") or "").strip().lower() == "correct"
    )
    incorrect = sum(
        1 for a in attempts if (a.get("verdict") or "").strip().lower() == "incorrect"
    )
    uncertain = sum(
        1 for a in attempts if (a.get("verdict") or "").strip().lower() == "uncertain"
    )

    # Knowledge mastery (tag-level accuracy)
    tag_stats: Dict[str, Dict[str, int]] = {}
    attempts_with_tags = 0
    attempts_with_severity = 0
    for a in attempts:
        verdict = (a.get("verdict") or "").strip().lower()
        tags = _dedupe_str_list(a.get("knowledge_tags_norm") or a.get("knowledge_tags"))
        if tags:
            attempts_with_tags += 1
        sev0 = str(a.get("severity") or "").strip()
        if sev0:
            attempts_with_severity += 1
        for t in tags:
            ts = str(t).strip()
            if not ts:
                continue
            s = tag_stats.setdefault(
                ts, {"total": 0, "correct": 0, "incorrect": 0, "uncertain": 0}
            )
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
        s = bucket_stats.setdefault(
            key, {"total": 0, "correct": 0, "incorrect": 0, "uncertain": 0}
        )
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
    bucket_rows.sort(
        key=lambda r: (r["accuracy"] is not None, r.get("accuracy") or 0.0)
    )

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

    incorrectish = [
        a
        for a in attempts
        if (a.get("verdict") or "").strip().lower() in {"incorrect", "uncertain"}
    ]
    incorrectish.sort(key=_sort_key)
    evidence = []
    for a in incorrectish[:20]:
        evidence.append(
            {
                "submission_id": a.get("submission_id"),
                "item_id": a.get("item_id"),
                "question_number": a.get("question_number"),
                "verdict": a.get("verdict"),
                "knowledge_tags": _dedupe_keep_order(
                    [
                        str(t).strip()
                        for t in _coerce_list(a.get("knowledge_tags_norm") or [])
                        if str(t).strip()
                    ]
                )[:10],
            }
        )

    submission_ids = _dedupe_keep_order(
        [
            str(a.get("submission_id") or "").strip()
            for a in attempts
            if str(a.get("submission_id") or "").strip()
        ]
    )

    # Cause distribution ("错因统计"): aggregate only wrongish attempts.
    wrongish = [a for a in attempts if _is_wrongish(a.get("verdict"))]
    wrong_total = len(wrongish)
    cause_counts: Dict[str, int] = {}
    for a in wrongish:
        sev = _attempt_cause(a)
        if sev:
            cause_counts[sev] = cause_counts.get(sev, 0) + 1
    cause_rates: Dict[str, Optional[float]] = {}
    for k, v in cause_counts.items():
        cause_rates[k] = _safe_div(int(v), wrong_total)

    trends = _compute_trends(attempts=attempts)

    return {
        "features_version": FEATURES_VERSION,
        "generated_at": now,
        "user_id": uid,
        "submission_ids": submission_ids,
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
        "cause_distribution": {
            "sample_size": int(wrong_total),
            "severity_counts": cause_counts,
            "severity_rates": cause_rates,
        },
        "coverage": {
            "tag_coverage_rate": _safe_div(attempts_with_tags, total),
            "severity_coverage_rate": _safe_div(attempts_with_severity, total),
            "steps_coverage_rate": _safe_div(len(steps), total),
        },
        "type_difficulty": {
            "rows": bucket_rows[:200],
        },
        "process_diagnosis": {
            "steps_sample_size": len(steps),
            "severity_counts": sev_counts,
            "diagnosis_code_counts": diagnosis_counts,
        },
        "trends": trends,
        "meta": {
            "cause_definitions": CAUSE_DEFINITIONS_V0,
            "cause_definitions_version": "cause_v0",
            # Knowledge tag spec is a soft guideline (not an exhaustive taxonomy).
            # It helps the frontend explain what the tags mean and how they're aggregated.
            "knowledge_tag_spec_version": "math_knowledge_graph_v0",
            "knowledge_tag_format": "path_optional",
            "knowledge_tag_separator": "/",
        },
        "evidence_refs": evidence,
    }
