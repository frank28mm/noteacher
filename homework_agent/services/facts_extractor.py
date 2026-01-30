from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from homework_agent.core.qbank_builder import normalize_questions

EXTRACT_VERSION = "facts_v1"
DIAGNOSIS_VERSION = "diag_v0"


@dataclass(frozen=True)
class ExtractedFacts:
    question_attempts: List[Dict[str, Any]]
    question_steps: List[Dict[str, Any]]


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_iso(dt: Any) -> str:
    if isinstance(dt, str) and dt.strip():
        return dt.strip()
    return _iso_utc_now()


def _coerce_list(v: Any) -> List[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        return [v]
    return [v]


def _normalize_tags_best_effort(tags: Any) -> List[str]:
    raw = [str(t).strip() for t in _coerce_list(tags) if str(t).strip()]
    # Optional: taxonomy normalize (introduced in Phase 2). Fallback to raw.
    try:
        from homework_agent.utils.taxonomy import normalize_knowledge_tags

        return normalize_knowledge_tags(raw)
    except Exception:
        return raw


def _derive_question_severity(q: Dict[str, Any]) -> Optional[str]:
    sev = q.get("severity")
    if isinstance(sev, str) and sev.strip():
        return sev.strip().lower()
    steps = q.get("math_steps")
    if isinstance(steps, list):
        for s in steps:
            if not isinstance(s, dict):
                continue
            ssev = s.get("severity")
            if isinstance(ssev, str) and ssev.strip():
                return ssev.strip().lower()
    # Best-effort fallback: infer from grader reason/judgment text when explicit severity is missing.
    # Keep conservative defaults to avoid over-confident misclassification.
    answer_state = str(q.get("answer_state") or "").strip().lower()
    if answer_state == "blank":
        return "unknown"
    reason = str(q.get("reason") or "").strip()
    judgment_basis = str(q.get("judgment_basis") or "").strip()
    text = f"{reason}\n{judgment_basis}".strip()
    if not text:
        return None
    # Unknown: unreadable / not answered / insufficient evidence
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
    # Calculation error hints
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
    # Format / writing issues
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
    # Default: concept/application issues
    return "concept"


def _diagnose_step_codes(step: Dict[str, Any]) -> List[str]:
    """
    v0 deterministic diagnosis codes (rule-based, conservative).
    The goal is to make step-level aggregation possible without LLM counting.
    """
    codes: List[str] = []
    sev = step.get("severity")
    if isinstance(sev, str) and sev.strip().lower() == "calculation":
        codes.append("calculation_error")
    return codes


def extract_facts_from_grade_result(
    *,
    user_id: str,
    submission_id: str,
    created_at: Any,
    subject: Optional[str],
    grade_result: Any,
    taxonomy_version: Optional[str] = None,
    classifier_version: Optional[str] = None,
) -> ExtractedFacts:
    """
    Convert `submissions.grade_result` (JSONB snapshot) into derived facts:
    - question_attempts (denominator-ready)
    - question_steps (process diagnosis)

    This is pure logic (no DB I/O).
    """
    uid = str(user_id or "").strip()
    sid = str(submission_id or "").strip()
    if not uid or not sid:
        return ExtractedFacts(question_attempts=[], question_steps=[])

    gr = grade_result if isinstance(grade_result, dict) else {}
    questions_raw = gr.get("questions")
    questions_raw = questions_raw if isinstance(questions_raw, list) else []
    questions = normalize_questions([q for q in questions_raw if isinstance(q, dict)])

    created_iso = _coerce_iso(created_at)
    subj = str(subject or gr.get("subject") or "").strip() or None

    attempts: List[Dict[str, Any]] = []
    steps_rows: List[Dict[str, Any]] = []
    now_iso = _iso_utc_now()
    for q in questions:
        item_id = str(q.get("item_id") or "").strip()
        if not item_id:
            continue
        tags_raw = q.get("knowledge_tags")
        tags_norm = _normalize_tags_best_effort(tags_raw)

        attempt = {
            "user_id": uid,
            "submission_id": sid,
            "item_id": item_id,
            "created_at": created_iso,
            "subject": subj,
            "question_number": q.get("question_number"),
            "question_idx": q.get("question_idx"),
            "verdict": q.get("verdict"),
            "knowledge_tags": _coerce_list(tags_raw),
            "knowledge_tags_norm": tags_norm,
            "question_type": q.get("question_type") or "unknown",
            "difficulty": q.get("difficulty") or "unknown",
            "severity": _derive_question_severity(q),
            "warnings": _coerce_list(q.get("warnings")),
            "question_raw": q,
            "extract_version": EXTRACT_VERSION,
            "taxonomy_version": taxonomy_version,
            "classifier_version": classifier_version,
            "updated_at": now_iso,
        }
        attempts.append(attempt)

        steps = q.get("math_steps")
        if isinstance(steps, list) and steps:
            for s in steps:
                if not isinstance(s, dict):
                    continue
                step_index = s.get("index")
                try:
                    step_index_int = int(step_index)
                except Exception:
                    continue
                step_row = {
                    "user_id": uid,
                    "submission_id": sid,
                    "item_id": item_id,
                    "step_index": step_index_int,
                    "created_at": created_iso,
                    "subject": subj,
                    "verdict": s.get("verdict"),
                    "severity": s.get("severity"),
                    "expected": s.get("expected"),
                    "observed": s.get("observed"),
                    "diagnosis_codes": _diagnose_step_codes(s),
                    "step_raw": s,
                    "extract_version": EXTRACT_VERSION,
                    "diagnosis_version": DIAGNOSIS_VERSION,
                    "updated_at": now_iso,
                }
                steps_rows.append(step_row)

    return ExtractedFacts(question_attempts=attempts, question_steps=steps_rows)
