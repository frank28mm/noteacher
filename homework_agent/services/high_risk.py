from __future__ import annotations

import logging
from typing import List, Union

from homework_agent.services.llm import MathGradingResult, EnglishGradingResult

logger = logging.getLogger(__name__)

# T3 High Risk Triggers
HIGH_RISK_WARNING_substrings = {
    "visual_risk",
    "ocr_failed",
    "blur",
    "skew",
    "figure_too_small",
    "needs_review",
    "budget_exhausted",
}


def enforce_conservative_grading(
    result: Union[MathGradingResult, EnglishGradingResult], warnings: List[str]
) -> List[str]:
    """
    T3: Quality Differentiated Gate (Conservative Correctness).
    If high-risk warnings are present, downgrade 'correct' verdicts to 'uncertain'.
    Returns a list of newly added warnings (if any).
    """
    if not warnings:
        return []

    # Check for triggers
    detected_risks = []
    for w in warnings:
        w_lower = str(w).lower()
        for trigger in HIGH_RISK_WARNING_substrings:
            if trigger in w_lower:
                detected_risks.append(trigger)

    if not detected_risks:
        return []

    # Apply downgrade
    downgrade_count = 0
    new_warnings = []

    # Handle different result types
    wrong_items = getattr(result, "wrong_items", []) or []
    questions = getattr(result, "questions", []) or []

    # We iterate over 'questions' (full list) to find 'correct' items.
    # Note: MathGradingResult/EnglishGradingResult structure usually puts 'correct' items implicitly
    # or explicitly in a 'questions' list if comprehensive.
    # However, standard output mostly focuses on 'wrong_items'.
    # If the autonomous agent only returns 'wrong_items', we can't downgrade 'correct' ones easily
    # unless 'questions' contains ALL items.

    # In Phase 2 Step 0, we ensured 'questions' contains all items with 'verdict'.
    for q in questions:
        if not isinstance(q, dict):
            continue
        v = str(q.get("verdict") or "").strip().lower()
        if v == "correct":
            q["verdict"] = "uncertain"
            q["verdict_reason"] = (
                f"Conservative downgrade due to risks: {','.join(detected_risks)}"
            )
            downgrade_count += 1

            # Also ensure this item appears in 'wrong_items' list if it wasn't there
            # (since it's now uncertain, it counts as 'not correct').
            # But 'wrong_items' usually drives the 'mistakes' DB.
            # We should append it to wrong_items if not present.
            q_idx = str(q.get("question_idx") or q.get("question_number") or "")
            if q_idx:
                already_in_wrong = any(
                    str(w.get("question_idx") or w.get("question_number") or "")
                    == q_idx
                    for w in wrong_items
                )
                if not already_in_wrong:
                    # Construct a wrong item entry from the question
                    item_entry = q.copy()
                    # ensure minimal fields
                    if "wrong_reason" not in item_entry:
                        item_entry["wrong_reason"] = item_entry.get("verdict_reason")
                    wrong_items.append(item_entry)

    if downgrade_count > 0:
        msg = f"Conservative Gate: Downgraded {downgrade_count} correct items due to risks: {list(set(detected_risks))}"
        logger.warning(msg)
        new_warnings.append(msg)

    return new_warnings
