from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from homework_agent.core.qbank import _normalize_question_number
from homework_agent.core.slice_policy import analyze_visual_risk
from homework_agent.models.schemas import Subject
from homework_agent.core.question_cards import infer_answer_state, make_card_item_id


@dataclass(frozen=True)
class ReviewCandidate:
    item_id: str
    question_number: str
    page_index: int
    review_reasons: list[str]
    priority: int


def _as_list(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _needs_review_hint(*, verdict: str, needs_review: Any, warnings: List[str]) -> bool:
    if bool(needs_review):
        return True
    v = (verdict or "").strip().lower()
    if v == "uncertain":
        return True
    for w in warnings or []:
        s = str(w).strip().lower()
        if not s:
            continue
        if "needs_review" in s or "依据不足" in s or "复核" in s:
            return True
        if "budget_exhausted" in s or "token_budget_exhausted" in s:
            return True
        if "vision_timeout" in s:
            return True
    return False


def pick_review_candidates(
    *,
    subject: Subject,
    page_index: int,
    questions: Iterable[Dict[str, Any]],
    max_per_page: int,
) -> List[ReviewCandidate]:
    """
    Deterministic selection of review candidates for "review cards" (Layer 3).

    Goal:
    - Only pick a small number of high-signal items to avoid cost/latency blowups.
    - Prefer visually risky questions and uncertain judgments.
    - Exclude blank/unattempted questions (handled by answer_state).
    """
    max_per_page = max(0, int(max_per_page))
    if max_per_page <= 0:
        return []

    scored: List[ReviewCandidate] = []
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        qn = _normalize_question_number(q.get("question_number") or q.get("question_index"))
        if not qn:
            continue
        warnings = _as_list(q.get("warnings"))
        verdict = str(q.get("verdict") or "").strip().lower()
        answer_state = infer_answer_state(
            student_answer=q.get("student_answer"),
            answer_status=q.get("answer_status"),
        )
        if answer_state == "blank":
            continue

        needs_review = _needs_review_hint(
            verdict=verdict, needs_review=q.get("needs_review"), warnings=warnings
        )
        if not needs_review:
            continue

        qcontent = q.get("question_content")
        vr, vr_reasons = analyze_visual_risk(
            subject=subject,
            question_content=qcontent,
            warnings=warnings,
        )

        # Only do "review cards" for visually risky questions by default.
        if not bool(vr):
            continue

        reasons: List[str] = []
        if verdict == "uncertain":
            reasons.append("verdict_uncertain")
        elif verdict == "incorrect":
            reasons.append("verdict_incorrect")
        if any("budget" in (w or "") for w in warnings):
            reasons.append("budget_warning")
        if any("timeout" in (w or "") for w in warnings):
            reasons.append("vision_timeout_warning")
        reasons.extend([f"visual_risk:{r}" for r in (vr_reasons or [])][:5])

        # Priority: smaller is earlier.
        priority = 50
        if verdict == "uncertain":
            priority = 10
        elif verdict == "incorrect":
            priority = 20
        elif needs_review:
            priority = 30

        item_id = make_card_item_id(page_index=int(page_index), question_number=qn)
        scored.append(
            ReviewCandidate(
                item_id=item_id,
                question_number=qn,
                page_index=int(page_index),
                review_reasons=reasons or ["needs_review"],
                priority=int(priority),
            )
        )

    scored.sort(key=lambda x: (x.priority, len(x.question_number), x.question_number))
    return scored[:max_per_page]

