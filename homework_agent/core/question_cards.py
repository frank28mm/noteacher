from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Import from qbank_parser directly to avoid circular import
from homework_agent.core.qbank_parser import _normalize_question_number


AnswerState = str


def make_card_item_id(*, page_index: int, question_number: Optional[str]) -> str:
    qn = _normalize_question_number(question_number)
    if qn:
        return f"p{int(page_index)+1}:q:{qn}"
    return f"p{int(page_index)+1}:q:unknown"


def _is_placeholder_text(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return False
    return t.startswith("（未提取到") or t.startswith("（批改未完成")


def infer_answer_state(
    *,
    student_answer: Any = None,
    answer_status: Any = None,
) -> AnswerState:
    status = str(answer_status or "").strip()
    if status:
        if any(x in status for x in ("未作答", "未答", "空白", "未填写")):
            return "blank"
        if "看不清" in status or "缺失" in status:
            return "unknown"
        if any(x in status for x in ("已作答", "已填写", "有作答")):
            return "has_answer"

    if student_answer is None:
        return "unknown"
    ans = str(student_answer)
    ans = ans.strip()
    if not ans:
        return "blank"
    if _is_placeholder_text(ans):
        return "unknown"
    if ans in {"未作答", "未答", "空白", "无", "—", "-", "N/A"}:
        return "blank"
    if "看不清" in ans or "缺失" in ans:
        return "unknown"
    return "has_answer"


def _first_line_snippet(text: Any, *, max_len: int = 20) -> Optional[str]:
    """
    Back-compat helper (kept for older imports).
    Prefer `_normalize_question_text` which does not truncate.
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    s = re.sub(r"\s+", " ", s)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _normalize_question_text(text: Any) -> Optional[str]:
    """
    Normalize question text for UI:
    - keep it plain text
    - preserve line breaks (e.g. options list)
    - trim and collapse excessive whitespace within each line
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    lines = []
    for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        t = re.sub(r"\s+", " ", str(ln)).strip()
        if t:
            lines.append(t)
    return "\n".join(lines) if lines else None


def build_question_cards_from_questions_map(
    *,
    page_index: int,
    questions: Dict[str, Any],
    card_state: str,
) -> List[Dict[str, Any]]:
    cards: List[Dict[str, Any]] = []
    if not isinstance(questions, dict):
        return cards
    for raw_qn, raw_q in questions.items():
        qn = _normalize_question_number(raw_qn) or _normalize_question_number(
            (raw_q or {}).get("question_number") if isinstance(raw_q, dict) else None
        )
        item_id = make_card_item_id(page_index=page_index, question_number=qn)
        q = raw_q if isinstance(raw_q, dict) else {}
        cards.append(
            {
                "item_id": item_id,
                "question_number": qn or "N/A",
                "page_index": int(page_index),
                "answer_state": infer_answer_state(
                    student_answer=q.get("student_answer"),
                    answer_status=q.get("answer_status"),
                ),
                "question_content": _normalize_question_text(
                    q.get("question_text") or q.get("question_content")
                ),
                "card_state": str(card_state),
            }
        )
    return cards


def build_question_cards_from_questions_list(
    *,
    page_index: int,
    questions: Iterable[Dict[str, Any]],
    card_state: str,
) -> Tuple[List[Dict[str, Any]], int]:
    cards: List[Dict[str, Any]] = []
    blank_count = 0
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        qn = _normalize_question_number(q.get("question_number") or q.get("question_index"))
        item_id = make_card_item_id(page_index=page_index, question_number=qn)
        ans_state = infer_answer_state(
            student_answer=q.get("student_answer"),
            answer_status=q.get("answer_status"),
        )
        if ans_state == "blank":
            blank_count += 1
        verdict = str(q.get("verdict") or "").strip().lower() or None
        reason = str(q.get("reason") or "").strip() or None
        needs_review = None
        if "needs_review" in q:
            try:
                needs_review = bool(q.get("needs_review"))
            except Exception:
                needs_review = None
        if needs_review is None and verdict == "uncertain":
            needs_review = True

        cards.append(
            {
                "item_id": item_id,
                "question_number": qn or "N/A",
                "page_index": int(page_index),
                "answer_state": ans_state,
                "question_content": _normalize_question_text(
                    q.get("question_text") or q.get("question_content")
                ),
                "card_state": str(card_state),
                "verdict": verdict,
                "reason": reason,
                "needs_review": needs_review,
            }
        )
    return cards, blank_count


def merge_question_cards(
    existing: Dict[str, Dict[str, Any]],
    updates: Iterable[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    merged = dict(existing or {})
    for card in updates or []:
        if not isinstance(card, dict):
            continue
        item_id = str(card.get("item_id") or "").strip()
        if not item_id:
            continue
        cur = merged.get(item_id)
        if isinstance(cur, dict):
            cur.update({k: v for k, v in card.items() if v is not None})
            merged[item_id] = cur
        else:
            merged[item_id] = dict(card)
    return merged


def sort_question_cards(cards_by_id: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    cards = [c for c in (cards_by_id or {}).values() if isinstance(c, dict)]

    def _key(c: Dict[str, Any]):
        pi = c.get("page_index")
        try:
            pi_i = int(pi)
        except Exception:
            pi_i = 999
        qn = str(c.get("question_number") or "")
        return (pi_i, len(qn), qn)

    return sorted(cards, key=_key)
