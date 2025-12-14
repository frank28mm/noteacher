from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from homework_agent.models.schemas import GeometryInfo, Severity, Subject


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


def sanitize_wrong_items(wrong_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize LLM输出，避免 Severity/geometry_check 等字段导致 Pydantic 校验错误。"""
    allowed_sev = {s.value for s in Severity}
    cleaned: List[Dict[str, Any]] = []
    for item in wrong_items or []:
        copy_item = dict(item)
        # Normalize question_number to string for schema compatibility
        qn = _normalize_question_number(
            copy_item.get("question_number") or copy_item.get("question_index") or copy_item.get("id")
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
                    step["severity"] = sev_norm if sev_norm in allowed_sev else Severity.UNKNOWN.value
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


def normalize_questions(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize question entries for storage (ensure strings and safe defaults)."""
    normalized: List[Dict[str, Any]] = []
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

        # Contract: do not store standard answers in the question bank (avoid leakage + reduce payload).
        if "standard_answer" in copy_q:
            copy_q.pop("standard_answer", None)

        # Contract: keep only the first error step for incorrect/uncertain; omit for correct.
        verdict = (copy_q.get("verdict") or "").strip().lower()
        steps = copy_q.get("math_steps") or copy_q.get("steps")
        if verdict == "correct":
            copy_q.pop("math_steps", None)
            copy_q.pop("steps", None)
        else:
            if isinstance(steps, list) and steps:
                first_bad = None
                for s in steps:
                    if isinstance(s, dict) and (s.get("verdict") or "").strip().lower() != "correct":
                        first_bad = s
                        break
                first_bad = first_bad or steps[0]
                if isinstance(first_bad, dict):
                    copy_q["math_steps"] = [first_bad]
            else:
                copy_q.pop("math_steps", None)
                copy_q.pop("steps", None)

        # Keep geometry_check out of the qbank for now (future work).
        copy_q.pop("geometry_check", None)

        # Normalize options (choice questions) to a compact dict[str, str] if present.
        opts = copy_q.get("options")
        if opts is None:
            pass
        elif isinstance(opts, dict):
            clean_opts: Dict[str, str] = {}
            for k, v in opts.items():
                kk = str(k).strip()
                vv = str(v).strip()
                if kk and vv:
                    clean_opts[kk] = vv
            copy_q["options"] = clean_opts or None
        else:
            copy_q["options"] = None
        normalized.append(copy_q)
    return normalized


def build_question_bank(
    *,
    session_id: str,
    subject: Subject,
    questions: List[Dict[str, Any]],
    vision_raw_text: str,
    page_image_urls: List[str],
) -> Dict[str, Any]:
    """Build a queryable question bank snapshot keyed by question_number."""
    qlist = normalize_questions(questions)

    # Enrich question_content/options/student_answer from Vision raw text when possible.
    # This avoids relying on the grader to re-state long stems/options (reduces token use + prevents hallucination).
    vision_qbank = build_question_bank_from_vision_raw_text(
        session_id=session_id,
        subject=subject,
        vision_raw_text=vision_raw_text,
        page_image_urls=page_image_urls,
    )
    vision_questions = vision_qbank.get("questions") if isinstance(vision_qbank, dict) else None
    vision_questions = vision_questions if isinstance(vision_questions, dict) else {}

    by_qn: Dict[str, Any] = {}
    for q in qlist:
        qn = q.get("question_number")
        if not qn:
            continue
        qn_str = str(qn)
        vq = vision_questions.get(qn_str)
        if isinstance(vq, dict):
            # Prefer OCR/vision-grounded content to prevent grader-side drift.
            if vq.get("question_content"):
                q["question_content"] = vq.get("question_content")
            if vq.get("student_answer"):
                q["student_answer"] = vq.get("student_answer")
            if vq.get("options"):
                q["options"] = vq.get("options")
            if vq.get("answer_status"):
                q["answer_status"] = vq.get("answer_status")
            # Preserve "可能误读公式" hints from vision.
            vw = vq.get("warnings")
            if isinstance(vw, list) and vw:
                q["warnings"] = list(dict.fromkeys((q.get("warnings") or []) + vw))
        by_qn[qn_str] = q
    return {
        "session_id": session_id,
        "subject": subject.value if hasattr(subject, "value") else str(subject),
        "vision_raw_text": vision_raw_text,
        "page_image_urls": [str(u) for u in (page_image_urls or []) if u],
        "questions": by_qn,
    }


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
    num_re = re.compile(r"^\s*(\d{1,3}(?:\s*\(\s*\d+\s*\)\s*)?(?:[①②③④⑤⑥⑦⑧⑨])?)\s*[\.．]\s*$")
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
        m2 = re.search(r"(?:\*\*学生作答状态\*\*|学生作答状态|作答状态)\s*[:：]\s*(.+)", block)
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
        if ("选项" in block) or ("A." in block and "B." in block) or ("A、" in block and "B、" in block):
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
                for k, v in re.findall(r"([A-D])[\.\、:：]\s*([^\n]+?)(?=(?:\s+[A-D][\.\、:：])|$)", block):
                    kk = str(k).strip()
                    vv = str(v).strip().rstrip(";；")
                    if kk and vv:
                        options[kk] = vv

        warnings: List[str] = []
        # Extract concrete misread warnings when present (avoid losing details).
        for kind, detail in re.findall(r"(可能误读(?:公式|规律))\s*[:：]\s*([^\n]+)", block):
            d = str(detail).strip()
            if d:
                warnings.append(f"{kind}：{d}")
        if not warnings and "可能误读" in block:
            warnings.append("可能误读公式：请人工复核题干/图示/指数/分式细节")

        questions[str(current_qn)] = {
            "question_number": str(current_qn),
            "verdict": "uncertain",
            "question_content": q_content or "（批改未完成，题干请参考 vision_raw_text）",
            "student_answer": student_ans or "（未提取到，题干/作答请参考 vision_raw_text）",
            "reason": "批改未完成（LLM 超时/失败），暂无法判定对错；可先基于识别原文进行辅导。",
            "warnings": warnings,
            "knowledge_tags": [],
            "answer_status": answer_status or None,
            "options": options or None,
        }
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


def derive_wrong_items_from_questions(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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

