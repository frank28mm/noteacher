from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from homework_agent.core.slice_policy import analyze_visual_risk
from homework_agent.core.qbank_parser import build_question_bank_from_vision_raw_text
from homework_agent.models.schemas import GeometryInfo, Severity, Subject


def _max_math_steps_per_question() -> int:
    try:
        from homework_agent.utils.settings import get_settings

        settings = get_settings()
        v = getattr(settings, "max_math_steps_per_question", 5)
        return max(0, min(int(v), 20))
    except Exception:
        return 5


def _coerce_question_type(v: Any) -> str:
    s = str(v or "").strip()
    return s or "unknown"


def _coerce_difficulty(v: Any) -> str:
    s = str(v or "").strip()
    return s or "unknown"


def _normalize_question_identifiers(
    questions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Ensure each question has:
    - question_idx: 1-indexed position in the current list (deterministic for storage)
    - item_id: stable identifier for joins (prefer question_number, else idx)
    """
    counts: Dict[str, int] = {}
    for idx, q in enumerate(questions or []):
        if not isinstance(q, dict):
            continue
        q.setdefault("question_idx", idx + 1)
        if q.get("item_id"):
            q["item_id"] = str(q["item_id"])
            continue
        qn = q.get("question_number")
        base = f"q:{qn}" if qn else f"idx:{idx+1}"
        counts[base] = counts.get(base, 0) + 1
        q["item_id"] = base if counts[base] == 1 else f"{base}#{counts[base]}"
    return questions


def sanitize_wrong_items(wrong_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize LLM输出，避免 Severity/geometry_check 等字段导致 Pydantic 校验错误。"""
    allowed_sev = {s.value for s in Severity}
    cleaned: List[Dict[str, Any]] = []
    for item in wrong_items or []:
        copy_item = dict(item)
        # Normalize question_number to string for schema compatibility
        qn = _normalize_question_number(
            copy_item.get("question_number")
            or copy_item.get("question_index")
            or copy_item.get("id")
        )
        if qn is not None:
            copy_item["question_number"] = qn
        # Normalize item_id to string if present (stable identifiers preferred)
        if copy_item.get("item_id") is not None:
            copy_item["item_id"] = str(copy_item["item_id"])
        # Normalize severity in math_steps/steps
        steps = copy_item.get("math_steps") or copy_item.get("steps")
        if isinstance(steps, list):
            for step in steps:
                sev = step.get("severity")
                if isinstance(sev, str):
                    sev_norm = sev.strip().lower()
                    step["severity"] = (
                        sev_norm if sev_norm in allowed_sev else Severity.UNKNOWN.value
                    )
        # Normalize geometry_check
        geom = copy_item.get("geometry_check")
        if geom is not None and not isinstance(geom, (dict, GeometryInfo)):
            copy_item["geometry_check"] = None
        # Normalize per-item warnings
        w = copy_item.get("warnings")
        if w is None:
            copy_item["warnings"] = []
        elif isinstance(w, str):
            copy_item["warnings"] = [w]
        elif not isinstance(w, list):
            copy_item["warnings"] = [str(w)]
        cleaned.append(copy_item)
    return cleaned


def _normalize_question_number(value: Any) -> Optional[str]:
    # Import from parser module to keep it as the single source of truth.
    from homework_agent.core.qbank_parser import _normalize_question_number as _norm

    return _norm(value)


def _is_numeric_question_number(value: Optional[str]) -> bool:
    if not value:
        return False
    s = str(value).strip().replace("（", "(").replace("）", ")")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[①②③④⑤⑥⑦⑧⑨]", "", s)
    return re.fullmatch(r"\d+(?:\(\d+\))?", s) is not None


def _generate_question_aliases(qn: str) -> List[str]:
    """
    Generate aliases for non-numeric question titles.
    Example: "思维与拓展(旋转题)" -> ["思维与拓展(旋转题)", "思维与拓展", "思维", "拓展", "旋转题"]
    """
    s = str(qn or "").strip()
    if not s:
        return []
    s = s.replace("（", "(").replace("）", ")")
    aliases: List[str] = [s]
    no_paren = re.sub(r"[（(][^）)]*[)）]", "", s).strip()
    if no_paren and no_paren != s:
        aliases.append(no_paren)
    tokens = re.split(r"[与和、/\\s]+|[()（）]", s)
    for t in tokens:
        t = t.strip()
        if len(t) >= 2 and t not in aliases:
            aliases.append(t)
    return aliases


def normalize_questions(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize question entries for storage (ensure strings and safe defaults)."""
    normalized: List[Dict[str, Any]] = []
    max_steps = _max_math_steps_per_question()
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        copy_q = dict(q)
        qn = _normalize_question_number(copy_q.get("question_number"))
        if qn is not None:
            copy_q["question_number"] = qn
        # normalize verdict
        verdict = copy_q.get("verdict")
        if isinstance(verdict, str):
            v = verdict.strip().lower()
            if v in {"correct", "incorrect", "uncertain"}:
                copy_q["verdict"] = v
        # normalize warnings
        w = copy_q.get("warnings")
        if w is None:
            copy_q["warnings"] = []
        elif isinstance(w, str):
            copy_q["warnings"] = [w]
        elif not isinstance(w, list):
            copy_q["warnings"] = [str(w)]
        # normalize knowledge_tags
        tags = copy_q.get("knowledge_tags")
        if tags is None:
            copy_q["knowledge_tags"] = []
        elif isinstance(tags, str):
            copy_q["knowledge_tags"] = [tags]
        elif not isinstance(tags, list):
            copy_q["knowledge_tags"] = [str(tags)]

        # normalize question_type/difficulty (used by reports)
        copy_q["question_type"] = _coerce_question_type(copy_q.get("question_type"))
        copy_q["difficulty"] = _coerce_difficulty(copy_q.get("difficulty"))

        # Contract: do not store standard answers in the question bank (avoid leakage + reduce payload).
        if "standard_answer" in copy_q:
            copy_q.pop("standard_answer", None)

        # Storage policy for steps:
        # - correct: omit steps
        # - incorrect/uncertain: keep non-correct steps (up to K) for process diagnosis
        verdict = (copy_q.get("verdict") or "").strip().lower()
        steps = copy_q.get("math_steps") or copy_q.get("steps")
        if verdict == "correct":
            copy_q.pop("math_steps", None)
            copy_q.pop("steps", None)
        else:
            if isinstance(steps, list) and steps:
                non_correct: List[Dict[str, Any]] = []
                allowed_sev = {s.value for s in Severity}
                for s in steps:
                    if not isinstance(s, dict):
                        continue
                    v = (s.get("verdict") or "").strip().lower()
                    if v == "correct":
                        continue
                    sev = s.get("severity")
                    if isinstance(sev, str):
                        sev_norm = sev.strip().lower()
                        s["severity"] = (
                            sev_norm
                            if sev_norm in allowed_sev
                            else Severity.UNKNOWN.value
                        )
                    non_correct.append(s)
                    if max_steps and len(non_correct) >= max_steps:
                        break
                if non_correct:
                    copy_q["math_steps"] = non_correct
                else:
                    copy_q.pop("math_steps", None)
            else:
                copy_q.pop("math_steps", None)
                copy_q.pop("steps", None)

        # Keep geometry_check out of the qbank for now (future work).
        copy_q.pop("geometry_check", None)

        # Normalize options (choice questions) to a compact dict[str, str] if present.
        opts = copy_q.get("options")
        if isinstance(opts, dict):
            clean_opts: Dict[str, str] = {}
            for k, v in opts.items():
                kk = str(k).strip()
                vv = str(v).strip() if v is not None else ""
                if kk and vv:
                    clean_opts[kk[:8]] = vv[:500]
            copy_q["options"] = clean_opts or None
        else:
            copy_q["options"] = None
        normalized.append(copy_q)
    return _normalize_question_identifiers(normalized)


def build_question_bank(
    *,
    session_id: str,
    subject: Subject,
    questions: List[Dict[str, Any]],
    vision_raw_text: str,
    page_image_urls: List[str],
    visual_facts_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a queryable question bank snapshot keyed by question_number."""
    qlist = normalize_questions(questions)

    # Always parse Vision raw text to build a stable baseline:
    # - guarantees /chat can route by question_number even if the grader forgets to output a full list
    # - keeps stems grounded in OCR rather than grader hallucinations
    vision_qbank = build_question_bank_from_vision_raw_text(
        session_id=session_id,
        subject=subject,
        vision_raw_text=vision_raw_text,
        page_image_urls=page_image_urls,
    )
    vision_questions = (
        vision_qbank.get("questions") if isinstance(vision_qbank, dict) else None
    )
    vision_questions = vision_questions if isinstance(vision_questions, dict) else {}

    by_qn: Dict[str, Any] = {}
    # 1) Baseline: all questions extracted from Vision.
    for qn, vq in vision_questions.items():
        if not qn or not isinstance(vq, dict):
            continue
        base = dict(vq)
        base["question_number"] = str(qn)
        # Ensure a minimal contract for chat routing.
        base.setdefault("verdict", "uncertain")
        base.setdefault("warnings", [])
        base.setdefault("knowledge_tags", [])
        by_qn[str(qn)] = base

    # 2) Overlay: grader's structured judgments (verdict/reason/steps/tags).
    for q in qlist:
        qn = q.get("question_number")
        if not qn:
            continue
        qn_str = str(qn)
        merged = dict(by_qn.get(qn_str) or {})

        # Keep OCR-grounded fields when available; only fill from grader if missing.
        for field in ("question_content", "student_answer", "options", "answer_status"):
            if not merged.get(field) and q.get(field):
                merged[field] = q.get(field)

        # Always take grader judgments when present.
        for field in (
            "verdict",
            "reason",
            "knowledge_tags",
            "math_steps",
            "warnings",
            "cross_subject_flag",
        ):
            if q.get(field) is not None:
                merged[field] = q.get(field)

        # Merge warnings (vision risk hints are critical).
        vw = merged.get("warnings") if isinstance(merged.get("warnings"), list) else []
        qw = q.get("warnings") if isinstance(q.get("warnings"), list) else []
        if vw or qw:
            merged["warnings"] = list(dict.fromkeys([*vw, *qw]))

        merged["question_number"] = qn_str
        by_qn[qn_str] = merged

    # 3) Annotate per-question visual risk for chat re-look decisions.
    for qn, q in list(by_qn.items()):
        if not isinstance(q, dict):
            continue
        vr, reasons = analyze_visual_risk(
            subject=subject,
            question_content=q.get("question_content"),
            warnings=q.get("warnings") if isinstance(q.get("warnings"), list) else [],
        )
        q["visual_risk"] = bool(vr)
        if reasons:
            q["visual_risk_reasons"] = reasons
        # Attach aliases for non-numeric question titles (used by chat routing).
        if not _is_numeric_question_number(qn):
            q["question_aliases"] = _generate_question_aliases(str(qn))
        else:
            q["question_aliases"] = []
        by_qn[str(qn)] = q

    # 4) Attach visual_facts (if provided) to per-question payloads.
    if isinstance(visual_facts_map, dict):
        for qn, facts in visual_facts_map.items():
            qn_str = str(qn)
            if (
                qn_str in by_qn
                and isinstance(by_qn.get(qn_str), dict)
                and isinstance(facts, dict)
            ):
                by_qn[qn_str]["visual_facts"] = facts
    return {
        "session_id": session_id,
        "subject": subject.value if hasattr(subject, "value") else str(subject),
        "vision_raw_text": vision_raw_text,
        "page_image_urls": [str(u) for u in (page_image_urls or []) if u],
        "questions": by_qn,
    }


def derive_wrong_items_from_questions(
    questions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Derive WrongItem-shaped dicts from questions[*] entries.
    Provides a robust fallback when the model fails to emit valid `wrong_items`.
    """
    derived: List[Dict[str, Any]] = []
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        verdict = (q.get("verdict") or "").strip().lower()
        if verdict not in {"incorrect", "uncertain"}:
            continue

        qn = _normalize_question_number(q.get("question_number"))
        reason = q.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            reason = "判定为错误/不确定（原因未提供）"

        item: Dict[str, Any] = {
            "reason": reason,
            "question_number": qn,
            "question_content": q.get("question_content"),
            "student_answer": q.get("student_answer"),
            "warnings": q.get("warnings") or [],
            "knowledge_tags": q.get("knowledge_tags") or [],
            "cross_subject_flag": q.get("cross_subject_flag"),
        }

        # Optional extra fields if present.
        for key in (
            "math_steps",
            "geometry_check",
            "semantic_score",
            "similarity_mode",
            "keywords_used",
        ):
            if q.get(key) is not None:
                item[key] = q.get(key)

        derived.append(item)
    return derived


def assign_stable_item_ids(wrong_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ensure each wrong_item has a stable string `item_id` for UI selection and chat binding.
    Prefer `question_number` (original paper number). If duplicates exist for the same question,
    suffix with #2/#3...
    """
    counts: Dict[str, int] = {}
    for item in wrong_items or []:
        if not isinstance(item, dict):
            continue
        if item.get("item_id"):
            continue
        qn = item.get("question_number")
        if qn:
            base = f"q:{qn}"
        else:
            base = f"idx:{item.get('id')}" if item.get("id") is not None else "item"
        counts[base] = counts.get(base, 0) + 1
        item["item_id"] = base if counts[base] == 1 else f"{base}#{counts[base]}"
    return wrong_items


def dedupe_wrong_items(wrong_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop exact duplicate wrong items to reduce confusion in UI/chat context."""
    seen: set[tuple] = set()
    deduped: List[Dict[str, Any]] = []
    for item in wrong_items or []:
        if not isinstance(item, dict):
            continue
        key = (
            item.get("question_number"),
            item.get("reason"),
            item.get("student_answer") or item.get("answer"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
