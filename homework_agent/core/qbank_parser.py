from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from homework_agent.core.slice_policy import analyze_visual_risk
from homework_agent.models.schemas import Subject


def _normalize_question_number(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"\\s+", "", s)
    s = re.sub(r"^第", "", s)
    s = re.sub(r"题$", "", s)
    return s or None


def build_question_bank_from_vision_raw_text(
    *,
    session_id: str,
    subject: Subject,
    vision_raw_text: str,
    page_image_urls: List[str],
) -> Dict[str, Any]:
    """
    Build a minimal question bank from Vision raw text when grading LLM fails.
    This enables /chat to route by question number even if verdicts are unknown.
    """
    text = vision_raw_text or ""
    lines = text.splitlines()
    questions: Dict[str, Any] = {}

    # Split by headings like "### 第28题" or numbered lines like "28."
    # NOTE: Use real whitespace escapes; avoid double-escaping (\\s) which would match a literal backslash.
    header_re = re.compile(r"^#{2,4}\s*第\s*([^题\s]+)\s*题\s*$")
    num_re = re.compile(
        r"^\s*(\d{1,3}(?:\s*\(\s*\d+\s*\)\s*)?(?:[①②③④⑤⑥⑦⑧⑨])?)\s*[\.．]\s*$"
    )
    current_qn: Optional[str] = None
    current_buf: List[str] = []

    def _flush() -> None:
        nonlocal current_qn, current_buf
        if not current_qn:
            current_buf = []
            return
        block = "\n".join(current_buf).strip()
        # best-effort extraction
        q_content = ""
        student_ans = ""
        answer_status = ""
        options: Dict[str, str] = {}

        # 题干：支持 "**题目**：" / "- 题目：" / "题目："，并尽量把后续的示例/图示说明一并带上（直到出现“答案/作答状态/步骤”等标签）。
        blk_lines = [ln.rstrip() for ln in block.splitlines()]
        label_stop = re.compile(
            r"^\s*[\-\*\s]*((\*\*)?(答案|作答状态|学生作答状态|学生答案|学生作答|学生作答步骤|作答步骤|解题步骤)(\*\*)?)\s*[:：]"
        )
        for i, ln in enumerate(blk_lines):
            if re.search(r"(?:\*\*题目\*\*|题目)\s*[:：]", ln):
                first = re.split(r"[:：]", ln, maxsplit=1)
                head = (first[1] if len(first) > 1 else "").strip()
                collected: List[str] = [head] if head else []
                for j in range(i + 1, min(len(blk_lines), i + 12)):
                    nxt = blk_lines[j].strip()
                    if not nxt:
                        continue
                    if label_stop.search(nxt):
                        break
                    # drop leading bullets for readability
                    nxt = re.sub(r"^[\-\*\s]+", "", nxt).strip()
                    if nxt:
                        collected.append(nxt)
                q_content = "\n".join([c for c in collected if c]).strip()
                break

        # Some vision formats emit 学生答案/答案 instead of 作答状态
        m2 = re.search(
            r"(?:\*\*学生作答状态\*\*|学生作答状态|作答状态)\s*[:：]\s*(.+)", block
        )
        if m2:
            answer_status = m2.group(1).strip()
        if not student_ans:
            m3 = re.search(r"(?:\*\*学生答案\*\*|学生答案)\s*[:：]\s*(.+)", block)
            if m3:
                student_ans = m3.group(1).strip()
        # fallback: look for "答案："
        if not student_ans:
            m4 = re.search(r"(?:\*\*答案\*\*|答案)\s*[:：]\s*([^\n]+)", block)
            if m4:
                student_ans = m4.group(1).strip()

        # Extract choice options if present (A/B/C/D)
        # Common patterns: "A. xxx", "A、xxx", "A: xxx" (often under a line like "选项：").
        if (
            ("选项" in block)
            or ("A." in block and "B." in block)
            or ("A、" in block and "B、" in block)
        ):
            for line in block.splitlines():
                s = line.strip()
                mopt = re.match(r"^[\-\*\s]*([A-D])[\.\、:：]\s*(.+)$", s)
                if mopt:
                    k = mopt.group(1).strip()
                    v = mopt.group(2).strip()
                    if v:
                        options[k] = v
            # Fallback: options may be in a single line, e.g. "选项：A. ... B. ... C. ... D. ..."
            if not options:
                for k, v in re.findall(
                    r"([A-D])[\.\、:：]\s*([^\n]+?)(?=(?:\s+[A-D][\.\、:：])|$)", block
                ):
                    kk = str(k).strip()
                    vv = str(v).strip().rstrip(";；")
                    if kk and vv:
                        options[kk] = vv

        warnings: List[str] = []
        # Extract concrete misread warnings when present (avoid losing details).
        for kind, detail in re.findall(
            r"(可能误读(?:公式|规律))\s*[:：]\s*([^\n]+)", block
        ):
            d = str(detail).strip()
            if d:
                warnings.append(f"{kind}：{d}")
        if not warnings and "可能误读" in block:
            warnings.append("可能误读公式：请人工复核题干/图示/指数/分式细节")

        questions[str(current_qn)] = {
            "question_number": str(current_qn),
            "verdict": "uncertain",
            "question_content": q_content
            or "（批改未完成，题干请参考 vision_raw_text）",
            "student_answer": student_ans
            or "（未提取到，题干/作答请参考 vision_raw_text）",
            "reason": "批改未完成（LLM 超时/失败），暂无法判定对错；可先基于识别原文进行辅导。",
            "warnings": warnings,
            "knowledge_tags": [],
            "answer_status": answer_status or None,
            "options": options or None,
        }
        vr, reasons = analyze_visual_risk(
            subject=subject,
            question_content=questions[str(current_qn)].get("question_content"),
            warnings=warnings,
        )
        questions[str(current_qn)]["visual_risk"] = bool(vr)
        if reasons:
            questions[str(current_qn)]["visual_risk_reasons"] = reasons
        current_buf = []

    for line in lines:
        stripped = line.strip()
        m = header_re.match(stripped)
        m2 = num_re.match(stripped)
        if m or m2:
            _flush()
            current_qn = _normalize_question_number((m.group(1) if m else m2.group(1)))
            current_buf = []
            continue
        if current_qn is not None:
            current_buf.append(line)

    _flush()

    # If we couldn't find headings, create a single placeholder question.
    if not questions:
        questions["N/A"] = {
            "question_number": "N/A",
            "verdict": "uncertain",
            "question_content": "（批改未完成，题干请参考 vision_raw_text）",
            "student_answer": "（批改未完成，作答请参考 vision_raw_text）",
            "reason": "批改未完成（LLM 超时/失败），暂无法判定对错。",
            "warnings": [],
            "knowledge_tags": [],
        }

    return {
        "session_id": session_id,
        "subject": subject.value if hasattr(subject, "value") else str(subject),
        "vision_raw_text": vision_raw_text,
        "page_image_urls": [str(u) for u in (page_image_urls or []) if u],
        "questions": questions,
    }
