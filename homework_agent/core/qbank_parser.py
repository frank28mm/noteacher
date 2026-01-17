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


def _split_subquestions(
    *, base_number: str, question_content: str
) -> Dict[str, str]:
    """
    Split a compound question like "15. 计算： (1)... (2)..." into sub-questions:
    - returns {"15(1)": "<content without (1)>", "15(2)": "..."}
    We intentionally remove the leading "(n)" marker because the UI already shows the sub-number.
    """
    qn = str(base_number or "").strip()
    content = str(question_content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not qn or not content:
        return {}
    # If the question number already contains a sub-index, don't split again.
    if "(" in qn or "（" in qn:
        return {}

    lines = content.split("\n")
    marker_re = re.compile(r"^\s*[\(（]\s*(\d{1,3})\s*[\)）]\s*(.*)\s*$")

    # Only keep the *first* occurrence for each (n) marker. Later repeats are often
    # student solution lines, which we don't want to treat as new sub-questions.
    first_pos: Dict[str, int] = {}
    order: List[str] = []
    for i, ln in enumerate(lines):
        m = marker_re.match(ln)
        if not m:
            continue
        num = str(m.group(1) or "").strip()
        if not num or num in first_pos:
            continue
        first_pos[num] = i
        order.append(num)

    if not order:
        return {}

    prefix = "\n".join(lines[: first_pos[order[0]]]).strip()
    out: Dict[str, str] = {}
    for idx_pos, num in enumerate(order):
        start = first_pos[num]
        end = first_pos[order[idx_pos + 1]] if idx_pos + 1 < len(order) else len(lines)
        m0 = marker_re.match(lines[start])
        first_line = str(m0.group(2) if m0 else "").strip()

        body_lines: List[str] = []
        if first_line:
            # If this sub-question is purely a math expression line, keep only the
            # prompt expression (avoid including student's transformation steps).
            if first_line.startswith("\\(") or first_line.startswith("$"):
                body_lines = [first_line]
            else:
                body_lines = [first_line]
                # Stop when we hit the beginning of student working (often "(1) \\(...", "\\(...", "答：...").
                solution_start_re = re.compile(r"^\s*[\(（]\s*\d{1,3}\s*[\)）]\s*\\\(")
                for ln in lines[start + 1 : end]:
                    s = str(ln).strip()
                    if not s:
                        break
                    if solution_start_re.match(s) or s.startswith("\\(") or s.startswith("$") or s.startswith("答"):
                        break
                    body_lines.append(s)

        body = "\n".join(body_lines).strip()
        seg = "\n".join([s for s in (prefix, body) if s]).strip()
        if seg:
            out[f"{qn}({num})"] = seg
    return out


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
    # Also support inline formats like "28. 题干..." where stem is on the same line.
    # NOTE: Use real whitespace escapes; avoid double-escaping (\\s) which would match a literal backslash.
    header_re = re.compile(r"^#{2,4}\s*第\s*([^题\s]+)\s*题\s*$")
    num_re = re.compile(
        r"^\s*(\d{1,3}(?:\s*\(\s*\d+\s*\)\s*)?(?:[①②③④⑤⑥⑦⑧⑨])?)\s*[\.．]\s*$"
    )
    num_inline_re = re.compile(
        r"^\s*(\d{1,3}(?:\s*\(\s*\d+\s*\)\s*)?(?:[①②③④⑤⑥⑦⑧⑨])?)\s*[\.．]\s*(.+)\s*$"
    )
    section_re = re.compile(
        r"^\s*[一二三四五六七八九十]+、\s*(选择题|填空题|解答题|计算题|证明题)\s*$"
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

        # 题干：支持 "**题目**：" / "- 题目：" / "题目："。
        # 为避免把选择题选项混进题干：遇到明显的选项行（A/B/C/D）则停止收集后续行。
        blk_lines = [ln.rstrip() for ln in block.splitlines()]
        label_stop = re.compile(
            r"^\s*[\-\*\s]*((\*\*)?(答案|作答状态|学生作答状态|学生答案|学生作答|学生作答步骤|作答步骤|解题步骤)(\*\*)?)\s*[:：]"
        )
        option_line = re.compile(
            r"^\s*[\-\*\s]*([\(\（]?[A-D][\)\）]?)[\.\、:：]?\s+"
        )
        for i, ln in enumerate(blk_lines):
            if re.search(r"(?:\*\*题目\*\*|题目)\s*[:：]", ln):
                first = re.split(r"[:：]", ln, maxsplit=1)
                head = (first[1] if len(first) > 1 else "").strip()
                # If the head already contains inline options, keep only the stem.
                for marker in ("(A)", "(B)", "(C)", "(D)", "（A）", "（B）", "（C）", "（D）"):
                    idx = head.find(marker)
                    if idx > 0:
                        head = head[:idx].strip()
                        break
                collected: List[str] = [head] if head else []
                # Don't hard-cap too aggressively: reading comprehension / long word problems
                # often exceed 12 lines. We still stop on known labels/options below.
                max_follow_lines = 120
                for j in range(i + 1, min(len(blk_lines), i + 1 + max_follow_lines)):
                    nxt = blk_lines[j].strip()
                    if not nxt:
                        continue
                    if label_stop.search(nxt):
                        break
                    if option_line.match(nxt) or ("(A)" in nxt and "(B)" in nxt) or ("（A）" in nxt and "（B）" in nxt):
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
        # Common patterns:
        # - "A. xxx", "A、xxx", "A: xxx"
        # - "(A) xxx" / "（A）xxx" (OCR style)
        if (
            ("选项" in block)
            or ("A." in block and "B." in block)
            or ("A、" in block and "B、" in block)
            or ("(A)" in block and "(B)" in block)
            or ("（A）" in block and "（B）" in block)
        ):
            for line in block.splitlines():
                s = line.strip()
                mopt = re.match(r"^[\-\*\s]*([A-D])[\.\、:：]\s*(.+)$", s)
                if mopt:
                    k = mopt.group(1).strip()
                    v = mopt.group(2).strip()
                    if v:
                        options[k] = v
                        continue
                # OCR style: (A) xxx / （A）xxx
                mopt2 = re.match(r"^[\-\*\s]*[\(（]([A-D])[\)）]\s*(.+)$", s)
                if mopt2:
                    k = mopt2.group(1).strip()
                    v = mopt2.group(2).strip()
                    if v:
                        # If this line actually contains multiple options, let the inline splitter handle it.
                        if any(mark in v for mark in ("(A)", "(B)", "(C)", "(D)", "（A）", "（B）", "（C）", "（D）")):
                            pass
                        else:
                            options[k] = v
                            continue

                # Inline OCR style: "(A) ...; (B) ...; (C) ...; (D) ..."
                if re.search(r"[\(（][A-D][\)）].*[\(（][A-D][\)）]", s):
                    for kk, vv in re.findall(
                        r"(?:^|[;；,，]\s*)[\(（]([A-D])[\)）]\s*([^;；\n]+?)(?=(?:\s*[;；,，]\s*[\(（][A-D][\)）])|\s*[;；,，]?\s*$)",
                        s,
                    ):
                        k = str(kk).strip()
                        v = str(vv).strip().rstrip(";；")
                        if k and v:
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

        # If the OCR block contains sub-questions "(1)(2)...", also materialize them
        # so UI can match grade_result question_number like "15(1)".
        try:
            splits = _split_subquestions(
                base_number=str(current_qn),
                question_content=str(questions[str(current_qn)].get("question_content") or ""),
            )
            for sub_qn, sub_content in splits.items():
                if not sub_qn or sub_qn in questions:
                    continue
                sub_warnings = list(warnings)
                questions[sub_qn] = {
                    "question_number": sub_qn,
                    "verdict": "uncertain",
                    "question_content": sub_content,
                    "student_answer": questions[str(current_qn)].get("student_answer"),
                    "reason": questions[str(current_qn)].get("reason"),
                    "warnings": sub_warnings,
                    "knowledge_tags": [],
                    "answer_status": questions[str(current_qn)].get("answer_status"),
                    "options": None,
                }
                vr2, reasons2 = analyze_visual_risk(
                    subject=subject, question_content=sub_content, warnings=sub_warnings
                )
                questions[sub_qn]["visual_risk"] = bool(vr2)
                if reasons2:
                    questions[sub_qn]["visual_risk_reasons"] = reasons2
        except Exception:
            pass
        current_buf = []

    for line in lines:
        stripped = line.strip()
        m = header_re.match(stripped)
        m2 = num_re.match(stripped)
        m3 = num_inline_re.match(stripped)
        if m or m2 or m3:
            _flush()
            if m:
                current_qn = _normalize_question_number(m.group(1))
                current_buf = []
                continue
            if m2:
                current_qn = _normalize_question_number(m2.group(1))
                current_buf = []
                continue
            # Inline question: seed a synthetic "题目：" line so _flush() can extract stem.
            current_qn = _normalize_question_number(m3.group(1)) if m3 else None
            current_buf = []
            if current_qn and m3:
                seed = str(m3.group(2) or "").strip()
                if seed:
                    current_buf.append(f"题目：{seed}")
            continue
        if current_qn is not None:
            # Skip section/page headings inside a question block (common OCR noise).
            if section_re.match(stripped) or stripped.startswith("### Page"):
                continue
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
