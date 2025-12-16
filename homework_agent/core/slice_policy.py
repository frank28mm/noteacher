from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from homework_agent.models.schemas import Subject


_VISUAL_KEYWORDS_STRONG = (
    # Explicit diagram references
    "如图",
    "见图",
    "看图",
    "图1",
    "图2",
    "图①",
    "图②",
    "示意图",
    "示意",
    "下图",
    "图表",
    "统计图",
    "折线图",
    "柱状图",
    "条形图",
    "扇形统计图",
    "统计表",
    "表格",
    "图案",
    "图形拼接",
    "拼图",
    "数列规律",
    "规律",
    "观察图形",
    "观察规律",
    # Coordinate / function graphs
    "坐标",
    "坐标系",
    "坐标轴",
    "抛物线",
    "函数图像",
    "图像",
    "二次函数",
    "一次函数",
    "反比例函数",
    # Geometry shapes (often diagram-dependent)
    "几何",
    "三角形",
    "四边形",
    "圆",
    "扇形",
    "角",
    "∠",
    "平行",
    "垂直",
    "辅助线",
    # English OCR may keep these tokens
    "table",
    "chart",
    "graph",
    "figure",
    "diagram",
    "picture",
    "image",
)

_VISUAL_WARNING_KEYWORDS = (
    "可能误读公式",
    "可能误读规律",
    "示例未识别到",
    "看不清",
    "无法识别",
)


def analyze_visual_risk(
    *,
    subject: Subject,
    question_content: str | None,
    warnings: Iterable[Any] | None,
) -> Tuple[bool, List[str]]:
    """
    Decide whether a question is likely to require visual re-check (diagram / example / layout).

    Returns: (visual_risk, reasons)
    """
    content = (question_content or "").strip()
    warnings_list = [str(w).strip() for w in (warnings or []) if str(w).strip()]
    warnings_text = " ".join(warnings_list)

    reasons: List[str] = []

    if any(k in warnings_text for k in _VISUAL_WARNING_KEYWORDS):
        reasons.append("vision_warnings")

    if any(k in content for k in _VISUAL_KEYWORDS_STRONG):
        reasons.append("visual_keywords")

    return (bool(reasons), reasons)


def should_create_slices_for_bank(bank: Dict[str, Any]) -> bool:
    """
    Background slice indexing (qindex) is an optional optimization.
    Keep it conservative to avoid unnecessary OCR cost:
    - Trigger only when we have strong visual-risk signals (warnings or explicit diagram keywords).
    """
    if not isinstance(bank, dict):
        return False
    subject_raw = bank.get("subject")
    try:
        subject = subject_raw if isinstance(subject_raw, Subject) else Subject(str(subject_raw))
    except Exception:
        return False

    questions = bank.get("questions")
    if not isinstance(questions, dict):
        return False

    for q in questions.values():
        if not isinstance(q, dict):
            continue
        # Prefer a precomputed field if present.
        if q.get("visual_risk") is True:
            return True
        visual_risk, _ = analyze_visual_risk(
            subject=subject,
            question_content=q.get("question_content"),
            warnings=q.get("warnings") if isinstance(q.get("warnings"), list) else [],
        )
        if visual_risk:
            return True
    return False


def pick_question_numbers_for_slices(bank: Dict[str, Any]) -> List[str]:
    """
    Pick a conservative list of question_numbers worth slicing.
    - If qindex is triggered for the bank, we still avoid slicing everything.
    - Default policy: slice only questions with strong visual-risk signals.
    """
    if not isinstance(bank, dict):
        return []
    subject_raw = bank.get("subject")
    try:
        subject = subject_raw if isinstance(subject_raw, Subject) else Subject(str(subject_raw))
    except Exception:
        return []

    questions = bank.get("questions")
    if not isinstance(questions, dict):
        return []

    picked: List[str] = []
    for qn, q in questions.items():
        if not isinstance(q, dict):
            continue
        qn_str = str(q.get("question_number") or qn).strip()
        if not qn_str:
            continue
        # Prefer a precomputed field if present.
        if q.get("visual_risk") is True:
            picked.append(qn_str)
            continue
        visual_risk, _ = analyze_visual_risk(
            subject=subject,
            question_content=q.get("question_content"),
            warnings=q.get("warnings") if isinstance(q.get("warnings"), list) else [],
        )
        if visual_risk:
            picked.append(qn_str)

    # Keep stable order (as in qbank).
    return picked
