import hashlib
import json
import uuid
import logging
import asyncio
import time
import base64
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, status, Request, Header, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import AsyncIterator, Dict, Any, Optional, List, Tuple, Iterable
import re

from homework_agent.models.schemas import (
    GradeRequest, GradeResponse, ChatRequest, ChatResponse,
    VisionProvider, Message, Subject, SimilarityMode, ImageRef
)
from homework_agent.services.vision import VisionClient
from homework_agent.services.ocr_baidu import BaiduPaddleOCRVLClient
from homework_agent.services.qindex_queue import enqueue_qindex_job
from homework_agent.core.layout_index import (
    build_question_layouts_from_blocks,
    crop_and_upload_slices,
)
from homework_agent.services.llm import LLMClient, MathGradingResult, EnglishGradingResult
from homework_agent.utils.settings import get_settings
from homework_agent.utils.cache import get_cache_store, BaseCache
from homework_agent.models.schemas import Severity, GeometryInfo

logger = logging.getLogger(__name__)

router = APIRouter()

# 缓存：可配置 Redis，默认进程内存
cache_store: BaseCache = get_cache_store()

# 并发保护：防止线程池堆积导致“越跑越慢/无响应”
_settings_for_limits = get_settings()
VISION_SEMAPHORE = asyncio.Semaphore(max(1, int(_settings_for_limits.max_concurrent_vision)))
LLM_SEMAPHORE = asyncio.Semaphore(max(1, int(_settings_for_limits.max_concurrent_llm)))


async def _call_blocking_in_thread(
    fn,
    *args,
    timeout_seconds: float,
    semaphore: asyncio.Semaphore,
    **kwargs,
):
    """Run a blocking function in a thread with a timeout + concurrency guard."""
    async with semaphore:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs),
            timeout=timeout_seconds,
        )

# 常量
# 取消硬性 5 轮上限；仅保留计数用于提示递进
MAX_SOCRATIC_TURNS = 999999
SESSION_TTL_HOURS = 24
IDP_TTL_HOURS = 24
SESSION_TTL_SECONDS = SESSION_TTL_HOURS * 3600


def _ensure_session_id(value: Optional[str]) -> str:
    """Ensure we always have a stable session_id for grade→chat delivery."""
    v = (value or "").strip()
    if v:
        return v
    return f"session_{uuid.uuid4().hex[:8]}"


def _count_questions_with_options(bank: Dict[str, Any]) -> int:
    qs = bank.get("questions")
    if not isinstance(qs, dict):
        return 0
    n = 0
    for q in qs.values():
        if isinstance(q, dict) and q.get("options"):
            n += 1
    return n


def persist_question_bank(
    *,
    session_id: str,
    bank: Dict[str, Any],
    grade_status: str,
    grade_summary: str,
    grade_warnings: List[str],
    timings_ms: Optional[Dict[str, int]] = None,
) -> None:
    """Persist the canonical qbank snapshot that /chat must rely on."""
    if not session_id:
        return
    now = datetime.now().isoformat()
    meta = bank.get("meta") if isinstance(bank.get("meta"), dict) else {}
    meta.update(
        {
            "updated_at": now,
            "grade_status": grade_status,
            "grade_summary": grade_summary,
            "warnings": grade_warnings or [],
        }
    )
    if timings_ms:
        meta["timings_ms"] = {str(k): int(v) for k, v in timings_ms.items() if v is not None}
    # Derived stats for acceptance checks
    try:
        meta["vision_raw_len"] = int(len(bank.get("vision_raw_text") or ""))
        meta["questions_count"] = int(len(bank.get("questions") or {})) if isinstance(bank.get("questions"), dict) else 0
        meta["questions_with_options"] = int(_count_questions_with_options(bank))
    except Exception:
        pass
    bank["meta"] = meta
    save_question_bank(session_id, bank)
    try:
        logger.info(
            "qbank_saved session_id=%s status=%s questions=%s options=%s vision_raw_len=%s timings_ms=%s",
            session_id,
            grade_status,
            meta.get("questions_count"),
            meta.get("questions_with_options"),
            meta.get("vision_raw_len"),
            meta.get("timings_ms"),
        )
    except Exception:
        pass


def _merge_bank_meta(bank: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(bank, dict):
        return bank
    meta = bank.get("meta") if isinstance(bank.get("meta"), dict) else {}
    meta.update({k: v for k, v in (extra or {}).items() if v is not None})
    bank["meta"] = meta
    return bank


def _now_ts() -> float:
    return time.time()


def _coerce_ts(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, datetime):
        return float(v.timestamp())
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            pass
        try:
            return float(datetime.fromisoformat(s).timestamp())
        except Exception:
            return None
    return None


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    data = cache_store.get(f"sess:{session_id}")
    if not isinstance(data, dict):
        return None
    # Normalize timestamps for runtime logic.
    for k in ("created_at", "updated_at"):
        ts = _coerce_ts(data.get(k))
        if ts is not None:
            data[k] = ts
    return data


def save_session(session_id: str, data: Dict[str, Any]) -> None:
    copy = dict(data or {})
    copy["created_at"] = _coerce_ts(copy.get("created_at")) or _now_ts()
    copy["updated_at"] = _coerce_ts(copy.get("updated_at")) or _now_ts()
    cache_store.set(f"sess:{session_id}", copy, ttl_seconds=SESSION_TTL_SECONDS)


def delete_session(session_id: str) -> None:
    cache_store.delete(f"sess:{session_id}")


def save_mistakes(session_id: str, wrong_items: List[Dict[str, Any]]) -> None:
    """缓存错题列表供辅导上下文使用，仅限当前批次，会话 TTL 同步。"""
    # 为每个 wrong_item 补充本地索引与稳定 item_id，便于后续检索
    enriched = []
    for idx, item in enumerate(wrong_items):
        enriched_item = dict(item)
        # ensure question_number preserved as string
        qn = _normalize_question_number(enriched_item.get("question_number") or enriched_item.get("question_index"))
        if qn is not None:
            enriched_item["question_number"] = qn
        item_id = enriched_item.get("item_id") or enriched_item.get("id")
        if not item_id:
            item_id = f"item-{idx}"
        enriched_item["item_id"] = str(item_id)
        enriched_item.setdefault("id", idx)
        enriched.append(enriched_item)
    cache_store.set(
        f"mistakes:{session_id}",
        {"wrong_items": enriched, "ts": datetime.now().isoformat()},
        ttl_seconds=SESSION_TTL_SECONDS,
    )


def get_mistakes(session_id: str) -> Optional[List[Dict[str, Any]]]:
    data = cache_store.get(f"mistakes:{session_id}")
    if not data:
        return None
    return data.get("wrong_items")


def save_question_index(session_id: str, index: Dict[str, Any]) -> None:
    cache_store.set(
        f"qindex:{session_id}",
        {"index": index, "ts": datetime.now().isoformat()},
        ttl_seconds=SESSION_TTL_SECONDS,
    )


def get_question_index(session_id: str) -> Optional[Dict[str, Any]]:
    data = cache_store.get(f"qindex:{session_id}")
    if not data:
        return None
    idx = data.get("index")
    return idx if isinstance(idx, dict) else None


def save_question_bank(session_id: str, bank: Dict[str, Any]) -> None:
    cache_store.set(
        f"qbank:{session_id}",
        {"bank": bank, "ts": datetime.now().isoformat()},
        ttl_seconds=SESSION_TTL_SECONDS,
    )


def get_question_bank(session_id: str) -> Optional[Dict[str, Any]]:
    data = cache_store.get(f"qbank:{session_id}")
    if not data:
        return None
    bank = data.get("bank")
    return bank if isinstance(bank, dict) else None


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

    def _flush():
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


def _select_question_number_from_text(message: str, available: List[str]) -> Optional[str]:
    """
    Choose the best matching question_number from user message.
    Strategy (heuristic, deterministic):
    - Prefer the question number that is explicitly being requested (e.g. "聊/讲/说 第28题"),
      and de-prioritize negated mentions (e.g. "不聊25题了，聊28题").
    - If multiple candidates remain, prefer the latest mention in the message.
    - Fallback to common patterns like "第27题/27题/题27".
    """
    if not message or not available:
        return None
    msg = str(message)
    avail = [str(q) for q in (available or []) if q is not None and str(q).strip()]
    if not avail:
        return None

    # Collect all mentions with positions.
    mentions: List[Dict[str, Any]] = []

    def _find_mentions(q: str) -> List[tuple[int, int]]:
        if not q:
            return []
        if q.isdigit():
            # Avoid matching "2" inside "28".
            pat = re.compile(rf"(?<!\\d){re.escape(q)}(?!\\d)")
            return [(m.start(), m.end()) for m in pat.finditer(msg)]
        # Generic substring scan.
        out: List[tuple[int, int]] = []
        start = 0
        while True:
            idx = msg.find(q, start)
            if idx < 0:
                break
            out.append((idx, idx + len(q)))
            start = idx + max(1, len(q))
        return out

    for q in avail:
        for s, e in _find_mentions(q):
            mentions.append({"q": q, "start": s, "end": e})

    if not mentions:
        # Fallback: patterns like "第27题/27题/题27/28(1)②"
        pattern = re.compile(
            r"(?:第\\s*)?(\\d{1,3}(?:\\s*\\(\\s*\\d+\\s*\\)\\s*)?(?:[①②③④⑤⑥⑦⑧⑨])?)(?:\\s*题)?"
        )
        found = [(m.group(1), m.start(1), m.end(1)) for m in pattern.finditer(msg)]
        if not found:
            return None
        # Prefer the latest mention.
        raw, _, _ = sorted(found, key=lambda x: x[1])[-1]
        raw = _normalize_question_number(raw)
        if not raw:
            return None
        # Map to available keys.
        if raw in avail:
            return raw
        pref = [q for q in avail if q.startswith(f"{raw}(") or q.startswith(raw)]
        if pref:
            # Prefer the shortest matching key (treat as "whole question" if available).
            return sorted(pref, key=len)[0]
        return None

    # Score mentions: prefer requested vs negated, then latest occurrence, then specificity.
    POS_HINTS = (
        "聊",
        "讲",
        "说",
        "讨论",
        "解释",
        "辅导",
        "再讲",
        "再聊",
        "换",
        "切换",
        "聊聊",
        "讲讲",
        "说说",
    )
    NEG_HINTS = (
        "不聊",
        "别聊",
        "不要聊",
        "不讲",
        "别讲",
        "不要讲",
        "不说",
        "别说",
        "不要说",
        "不谈",
        "别谈",
        "不讨论",
        "别讨论",
        "先不",
        "不再",
        "先别",
    )

    best = None
    best_score = -10**18
    for m in mentions:
        q = m["q"]
        s = int(m["start"])
        e = int(m["end"])
        left = msg[max(0, s - 8) : s]
        around = msg[max(0, s - 12) : min(len(msg), e + 12)]

        score = 0
        score += len(q) * 100  # specificity
        score += s  # prefer later mention
        if any(h in left for h in POS_HINTS):
            score += 500
        if any(h in around for h in NEG_HINTS):
            score -= 10_000
        # If directly in "第XX题" form, give a small boost.
        if s > 0 and msg[max(0, s - 1) : s] == "第":
            score += 50

        if score > best_score:
            best_score = score
            best = q

    return best


def _extract_requested_question_number(message: str) -> Optional[str]:
    """Best-effort extraction of a requested question number from user text."""
    if not message:
        return None
    msg = str(message)
    m = re.search(
        r"(?:第\s*)?(\d{1,3}(?:\s*\(\s*\d+\s*\)\s*)?(?:[①②③④⑤⑥⑦⑧⑨])?)(?:\s*题)?",
        msg,
    )
    if not m:
        return None
    return _normalize_question_number(m.group(1))


def _extract_user_correction(message: str) -> Optional[str]:
    """
    Best-effort extraction of user "corrections" to the recognized problem statement.
    We keep it lightweight and store the original user sentence for the focused question.
    Examples:
      - "不是 b^3，是 b^2"
      - "确认是2啦"
      - "原题是 x^{3n}=2"
    """
    if not message:
        return None
    msg = str(message).strip()
    if not msg:
        return None
    # Common correction intents.
    if re.search(r"(不是|并不是).{0,60}?(而)?是", msg):
        return msg
    if re.search(r"(确认|应该|原题|题目).{0,30}?是", msg):
        return msg
    return None


def _pick_relook_image_url(focus_question: Dict[str, Any]) -> Optional[str]:
    """Choose the best available image URL for re-reading a specific question."""
    if not isinstance(focus_question, dict):
        return None
    refs = focus_question.get("image_refs")
    if isinstance(refs, dict):
        pages = refs.get("pages")
        if isinstance(pages, list):
            for p in pages:
                if not isinstance(p, dict):
                    continue
                slice_urls = p.get("slice_image_urls") or p.get("slice_image_url") or []
                if isinstance(slice_urls, str) and slice_urls:
                    return slice_urls
                if isinstance(slice_urls, list) and slice_urls:
                    for u in slice_urls:
                        if u:
                            return str(u)
    page_urls = focus_question.get("page_image_urls")
    if isinstance(page_urls, list):
        for u in page_urls:
            if u:
                return str(u)
    page_url = focus_question.get("page_image_url")
    if page_url:
        return str(page_url)
    return None


def _should_relook_focus_question(user_msg: str, focus_question: Dict[str, Any]) -> bool:
    """Heuristic: decide whether to re-run Vision for a focused question (diagram/pattern issues)."""
    msg = (user_msg or "").strip()
    qcontent = str((focus_question or {}).get("question_content") or "")
    warnings = focus_question.get("warnings") or []
    warnings_s = " ".join([str(w) for w in warnings]) if isinstance(warnings, list) else str(warnings)

    # User explicitly challenges recognition / asks to see the exact problem.
    if any(k in msg for k in ("题目不对", "识别错", "你识别到的题目", "看不清", "原题", "题干不对", "你看一下图")):
        return True

    # Pattern/diagram questions often need the visual example; if missing, relook.
    if "可能误读规律" in warnings_s or "可能误读公式" in warnings_s:
        if ("→" not in qcontent) and ("顺序" not in qcontent) and ("规律" in qcontent or "出现" in qcontent):
            return True

    # Very short stems are suspicious for multi-part questions.
    if len(qcontent) < 18 and any(k in qcontent for k in ("出现", "规律", "图", "示意")):
        return True

    return False


async def _relook_focus_question_via_vision(
    *,
    session_id: str,
    subject: Subject,
    question_number: str,
    focus_question: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Best-effort: run Vision again with a question-specific prompt to recover missing stem/examples.
    Returns a dict that can be merged into focus_question, or None if relook failed.
    """
    settings = get_settings()
    img_url = _pick_relook_image_url(focus_question)
    if not img_url:
        return None

    # Prefer local download + base64 for Qwen3 to avoid Ark URL fetch flakiness.
    data_uri = _download_as_data_uri(img_url)
    provider = VisionProvider.QWEN3 if data_uri else VisionProvider.DOUBAO
    images = [ImageRef(base64=data_uri)] if data_uri else [ImageRef(url=img_url)]

    prompt = (
        f"请只关注第{question_number}题。"
        "如果题目包含示意图/箭头/表格/序列示例（如 ABCD 出现顺序、对应数字位置），必须原样抄写示例并用文字说明顺序/位置关系；不要推断。"
        "请输出：题目原文、选项（如有）、学生作答（如有）、学生作答状态，以及任何“可能误读公式/规律”的风险提示。"
    )
    budget = min(15.0, float(settings.grade_vision_timeout_seconds))
    client = VisionClient()
    try:
        res = await _call_blocking_in_thread(
            client.analyze,
            images=images,
            prompt=prompt,
            provider=provider,
            timeout_seconds=budget,
            semaphore=VISION_SEMAPHORE,
        )
    except Exception as e:
        return {"relook_error": f"重识别失败: {e}"}

    # Parse the relook text into a minimal per-question payload.
    parsed = build_question_bank_from_vision_raw_text(
        session_id=session_id,
        subject=subject,
        vision_raw_text=res.text or "",
        page_image_urls=[img_url],
    )
    q = None
    qs = parsed.get("questions") if isinstance(parsed, dict) else None
    if isinstance(qs, dict):
        q = qs.get(str(question_number))
    payload: Dict[str, Any] = {"vision_recheck_text": (res.text or "")[:2200]}
    if isinstance(q, dict):
        for k in ("question_content", "student_answer", "answer_status", "options"):
            if q.get(k):
                payload[k] = q.get(k)
        vw = q.get("warnings")
        if isinstance(vw, list) and vw:
            payload["warnings"] = list(dict.fromkeys((focus_question.get("warnings") or []) + vw))
    return payload


def _format_math_for_display(text: str) -> str:
    """
    Make math in assistant messages more readable in demo UI:
    - Strip LaTeX delimiters like \\( \\) \\[ \\]
    - Replace a few common TeX commands with Unicode (× ÷ ± ∠ ·)
    This is best-effort and should never raise.
    """
    if not text:
        return text
    s = str(text)
    try:
        s = s.replace("\\(", "").replace("\\)", "").replace("\\[", "").replace("\\]", "")
        s = re.sub(r"\\boldsymbol\{([^{}]+)\}", r"\1", s)
        s = s.replace("\\times", "×").replace("\\div", "÷").replace("\\cdot", "·").replace("\\pm", "±")
        s = s.replace("\\angle", "∠")
        # \frac{a}{b} -> a/b (simple)
        s = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"\1/\2", s)

        # Convert caret-style exponents (e.g., 3^m, x^2, x^(n+1)) to LaTeX inline math to avoid "code-like" style.
        # Best-effort: avoid touching existing $...$ spans and backticks.
        def _wrap_symbolic_pow(segment: str) -> str:
            def repl(m: re.Match) -> str:
                base = m.group(1)
                exp = m.group(2)
                exp = exp.strip()
                # Normalize parentheses exponent: x^(n+1) -> x^{n+1}
                if exp.startswith("(") and exp.endswith(")"):
                    exp = exp[1:-1].strip()
                return f"${base}^{{{exp}}}$"

            # base can be 1-3 tokens (x, 3, (-x), 3^m already handled above for numeric)
            return re.sub(
                r"(?<![\\$])\b([A-Za-z]|\d+|\([^\s()]{1,6}\))\s*\^\s*(\(\s*[A-Za-z0-9+\-\s]+\s*\)|[A-Za-z0-9]+(?:\s*[+\-]\s*[A-Za-z0-9]+)*)",
                repl,
                segment,
            )

        out: List[str] = []
        plain: List[str] = []
        mode: str = "plain"  # plain | code | math
        i = 0
        while i < len(s):
            ch = s[i]
            if mode == "plain":
                if ch == "`":
                    if plain:
                        out.append(_wrap_symbolic_pow("".join(plain)))
                        plain = []
                    out.append("`")
                    mode = "code"
                    i += 1
                    continue
                if ch == "$":
                    if plain:
                        out.append(_wrap_symbolic_pow("".join(plain)))
                        plain = []
                    out.append("$")
                    mode = "math"
                    i += 1
                    continue
                plain.append(ch)
                i += 1
                continue
            elif mode == "code":
                out.append(ch)
                i += 1
                if ch == "`":
                    mode = "plain"
                continue
            else:  # math
                out.append(ch)
                i += 1
                if ch == "$":
                    mode = "plain"
                continue
        if plain:
            out.append(_wrap_symbolic_pow("".join(plain)))
        s = "".join(out)
    except Exception:
        return str(text)
    return s


def _build_question_index_for_pages(page_urls: List[str]) -> Dict[str, Any]:
    """
    Build per-question bbox/slice index using Baidu PaddleOCR-VL.
    Returns dict keyed by question_number.
    """
    settings = get_settings()
    ocr = BaiduPaddleOCRVLClient()
    if not ocr.is_configured():
        return {"questions": {}, "warnings": ["BAIDU_OCR 未配置，跳过 bbox/slice 生成"]}

    questions: Dict[str, Any] = {}
    warnings: List[str] = []
    for page_idx, page_url in enumerate(page_urls or []):
        if not page_url:
            continue
        try:
            task_id = ocr.submit(image_url=page_url)
            task = ocr.wait(task_id)
            blocks = ocr.extract_text_blocks(task.raw)
            if not blocks:
                warnings.append(f"page[{page_idx}]: OCR 未返回可用 blocks，改用整页")
                continue

            # We need image size for normalization. Prefer reading from first bbox if provided;
            # otherwise infer via download in crop_and_upload_slices (it loads the image anyway).
            # Here we download once for size.
            from homework_agent.core.layout_index import download_image

            img = download_image(page_url, timeout=30.0)
            w, h = img.size

            layouts = build_question_layouts_from_blocks(
                blocks=blocks,
                page_width=w,
                page_height=h,
                padding_ratio=settings.slice_padding_ratio,
            )
            # Upload slices (best-effort)
            layouts = crop_and_upload_slices(
                page_image_url=page_url,
                layouts=layouts,
                prefix=f"slices/{datetime.now().strftime('%Y%m%d')}/",
            )

            for qn, layout in layouts.items():
                # If same qn appears on multiple pages, keep first and attach extra pages as list
                entry = questions.get(qn) or {"question_number": qn, "pages": []}
                entry["pages"].append(
                    {
                        "page_index": page_idx,
                        "page_image_url": page_url,
                        "question_bboxes": [{"coords": b} for b in layout.bboxes_norm] if layout.bboxes_norm else [],
                        "slice_image_urls": layout.slice_image_urls,
                        "warnings": layout.warnings,
                        "ocr": {"provider": "baidu_paddleocr_vl", "task_id": task.task_id, "status": task.status},
                    }
                )
                questions[qn] = entry
        except Exception as e:
            warnings.append(f"page[{page_idx}]: OCR/切片失败，改用整页：{str(e)}")
            continue

    return {"questions": questions, "warnings": warnings}


def normalize_context_ids(raw_ids: Iterable[Any]) -> List[str | int]:
    """Normalize context ids: strip strings, cast digit strings to int, drop empties."""
    normalized: List[str | int] = []
    for cid in raw_ids:
        if cid is None:
            continue
        if isinstance(cid, str):
            trimmed = cid.strip()
            if not trimmed:
                continue
            if trimmed.isdigit():
                try:
                    normalized.append(int(trimmed))
                    continue
                except ValueError:
                    pass
            normalized.append(trimmed)
        elif isinstance(cid, int):
            normalized.append(cid)
    return normalized


def resolve_context_items(
    context_ids: List[str | int], mistakes: Optional[List[Dict[str, Any]]]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Select wrong_items by index or item_id/id. Returns (selected, missing_list).
    """
    if not mistakes:
        return [], [str(cid) for cid in context_ids]

    selected: List[Dict[str, Any]] = []
    missing: List[str] = []
    by_item_id = {str(m.get("item_id")): m for m in mistakes if m.get("item_id")}
    by_local_id = {str(m.get("id")): m for m in mistakes if m.get("id") is not None}

    for cid in context_ids:
        if isinstance(cid, int):
            if 0 <= cid < len(mistakes):
                selected.append(mistakes[cid])
            else:
                missing.append(str(cid))
        else:
            item = by_item_id.get(str(cid)) or by_local_id.get(str(cid))
            if item:
                selected.append(item)
            else:
                missing.append(str(cid))
    return selected, missing


def compact_wrong_items_for_chat(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reduce wrong item payload to speed up chat LLM calls."""
    compacted: List[Dict[str, Any]] = []
    for item in items or []:
        ci: Dict[str, Any] = {
            "question_number": item.get("question_number") or item.get("question_index") or item.get("id"),
            "question_content": item.get("question_content") or item.get("question"),
            "student_answer": item.get("student_answer") or item.get("answer"),
            "reason": item.get("reason"),
        }
        steps = item.get("math_steps") or item.get("steps")
        if isinstance(steps, list) and steps:
            first_bad = None
            for s in steps:
                if isinstance(s, dict) and s.get("verdict") != "correct":
                    first_bad = s
                    break
            first_bad = first_bad or steps[0]
            if isinstance(first_bad, dict):
                ci["key_step"] = {
                    k: first_bad.get(k)
                    for k in ["index", "verdict", "expected", "observed", "hint", "severity"]
                    if k in first_bad
                }
        geom = item.get("geometry_check")
        if geom:
            ci["geometry_check"] = geom
        compacted.append(ci)
    return compacted


def assistant_tail(history: List[Dict[str, Any]], max_messages: int = 3) -> List[Dict[str, Any]]:
    """Return last N assistant messages in chronological order for replay."""
    assistants = [m for m in history if m.get("role") == "assistant"]
    if not assistants:
        return []
    tail = assistants[-max_messages:]
    return tail


def validate_vision_provider(provider: VisionProvider) -> VisionProvider:
    """验证vision_provider是否在白名单中"""
    allowed_providers = [VisionProvider.QWEN3, VisionProvider.DOUBAO]
    if provider not in allowed_providers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid vision_provider. Allowed values: {[p.value for p in allowed_providers]}"
        )
    return provider


def _is_public_url(url: str) -> bool:
    url = str(url)
    if not url:
        return False
    if re.match(r"^https?://", url) is None:
        return False
    if url.startswith("http://127.") or url.startswith("https://127."):
        return False
    if url.startswith("http://localhost") or url.startswith("https://localhost"):
        return False
    return True


def _strip_base64_prefix(data: str) -> str:
    return re.sub(r"^data:image/[^;]+;base64,", "", data, flags=re.IGNORECASE)


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


def _first_public_image_url(images: List[Any]) -> Optional[str]:
    for img in images or []:
        url = getattr(img, "url", None) or (img.get("url") if isinstance(img, dict) else None)
        if url:
            return str(url)
    return None


def _probe_url_head(url: str) -> Optional[str]:
    """Best-effort HEAD probe for debugging (status/content-type/content-length)."""
    if not url:
        return None
    try:
        import httpx

        # Don't inherit local proxy env for public URL probes.
        with httpx.Client(timeout=5.0, follow_redirects=True, trust_env=False) as client:
            r = client.head(url)
        ct = r.headers.get("content-type")
        cl = r.headers.get("content-length")
        return f"url_head status={r.status_code} content-type={ct} content-length={cl}"
    except Exception as e:
        return f"url_head probe_failed: {e}"


def _download_as_data_uri(url: str) -> Optional[str]:
    """Best-effort: download image bytes locally and convert to data URI for Qwen3 base64 fallback."""
    if not url:
        return None
    try:
        import httpx

        # Avoid local proxy interference when downloading public object URLs.
        with httpx.Client(timeout=20.0, follow_redirects=True, trust_env=False) as client:
            r = client.get(url)
        if r.status_code != 200:
            return None
        content_type = r.headers.get("content-type", "image/jpeg").split(";")[0].strip() or "image/jpeg"
        data = r.content or b""
        if not data:
            return None
        if len(data) > 20 * 1024 * 1024:
            return None
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{content_type};base64,{b64}"
    except Exception:
        return None


def validate_images_payload(images: List[Dict[str, Any]], vision_provider: VisionProvider) -> None:
    """Early validation for /grade to reduce invalid calls."""
    if not images:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Images cannot be empty")
    for img in images:
        url = img.get("url")
        b64 = img.get("base64")
        if url:
            if not _is_public_url(url):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Image URL must be public HTTP/HTTPS (no localhost/127)",
                )
        elif b64:
            cleaned = _strip_base64_prefix(b64)
            est_bytes = int(len(cleaned) * 0.75)
            if est_bytes > 20 * 1024 * 1024:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image size exceeds 20MB; use URL")
            if vision_provider == VisionProvider.DOUBAO:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Doubao only supports URL; base64 not accepted")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Each image must provide url or base64")


def generate_job_id() -> str:
    """生成任务ID"""
    return f"job_{uuid.uuid4().hex[:16]}"


def get_idempotency_key(request: Request, x_idempotency_key: Optional[str] = None) -> Optional[str]:
    """获取幂等性键，只接受 Header。"""
    if x_idempotency_key:
        return x_idempotency_key.strip()
    return None


def check_idempotency(idempotency_key: str) -> Optional[GradeResponse]:
    """检查幂等性，如果存在则返回缓存结果"""
    cached = cache_store.get(f"idp:{idempotency_key}")
    if not cached:
        return None
    try:
        return GradeResponse(**cached["response"])
    except Exception:
        return None


def cache_response(idempotency_key: str, response: GradeResponse) -> None:
    """缓存响应结果"""
    cache_store.set(
        f"idp:{idempotency_key}",
        {"response": response.model_dump(), "ts": datetime.now().isoformat()},
        ttl_seconds=IDP_TTL_HOURS * 3600,
    )


async def perform_grading(req: GradeRequest, provider_str: str) -> GradeResponse:
    """执行批改（同步/后台共用）。"""
    # 提前确定 session_id，用于所有返回路径（grade→chat 必须可续接）
    session_for_ctx = _ensure_session_id(req.session_id or req.batch_id)
    try:
        # Best-effort: keep request/session aligned for downstream job records.
        req.session_id = session_for_ctx
    except Exception:
        pass

    settings = get_settings()
    started = time.monotonic()
    deadline = started + float(settings.grade_completion_sla_seconds)
    timings_ms: Dict[str, int] = {}

    def remaining_seconds() -> float:
        return max(0.0, deadline - time.monotonic())

    vision_prompt = (
        "请识别并提取作业内容，包括题目、答案和解题步骤。逐题输出“学生作答状态”：若看到答案/勾选则写明，若未看到答案/空白/未勾选，明确标注“未作答”或“可能未作答”。"
        "选择题必须完整列出选项（A/B/C/D 每一项的原文），并明确学生选择了哪个选项；若未勾选，标注未作答。"
        "对含幂/分式/下标的公式请双写：先按原式抄写（含上下标、分式），再给出纯文本展开形式（如 10^(n+1)、(a-b)^2/(c+d)）。"
        "特别自检指数/分母的 +1、±、平方/立方等细节，如有疑似误读，直接在结果中标注“可能误读公式：…”。"
        "对“规律/序列/图示题”（含箭头/示例/表格/图形），必须先原样抄写题目给出的示例（例如 A→B→C→D→C→B 或对应数字位置），不要凭空推断；若示例在图中，请描述图中出现的字母/顺序/位置关系。"
        "注意：你只负责识别与抄录（OCR+结构化），不要进行解题/判定/推理，不要写出你推断的正确答案或规律（例如“应为6n+3”这类）。如果示例/图中信息没识别出来，请明确写“示例未识别到/看不清”，并在 warnings 中标注风险。"
    )

    vision_client = VisionClient()
    vision_fallback_warning: Optional[str] = None
    meta_base: Dict[str, Any] = {
        "vision_provider_requested": getattr(req.vision_provider, "value", str(req.vision_provider)),
        "vision_provider_used": None,
        "vision_used_base64_fallback": False,
        "llm_provider_requested": provider_str,
        "llm_provider_used": None,
        "llm_used_fallback": False,
    }

    # Vision stage (offload to thread + sub-timeout)
    v_budget = min(float(settings.grade_vision_timeout_seconds), remaining_seconds())
    if v_budget <= 0:
        # Persist minimal snapshot so chat can deterministically explain the failure.
        persist_question_bank(
            session_id=session_for_ctx,
            bank=_merge_bank_meta(
                {
                "session_id": session_for_ctx,
                "subject": req.subject.value if hasattr(req.subject, "value") else str(req.subject),
                "vision_raw_text": None,
                "page_image_urls": [str(img.url) for img in (req.images or []) if getattr(img, "url", None)],
                "questions": {},
                },
                meta_base,
            ),
            grade_status="failed",
            grade_summary="Vision analysis not available",
            grade_warnings=["grade SLA exceeded before vision started"],
            timings_ms=timings_ms,
        )
        return GradeResponse(
            wrong_items=[],
            summary="Vision analysis not available",
            subject=req.subject,
            job_id=None,
            session_id=session_for_ctx,
            status="failed",
            total_items=None,
            wrong_count=None,
            cross_subject_flag=None,
            warnings=["grade SLA exceeded before vision started"],
            vision_raw_text=None,
        )

    async def _run_vision(provider: VisionProvider, budget: float):
        return await _call_blocking_in_thread(
            vision_client.analyze,
            images=req.images,
            prompt=vision_prompt,
            provider=provider,
            timeout_seconds=budget,
            semaphore=VISION_SEMAPHORE,
        )

    def _vision_err_str(err: Exception, budget: float) -> str:
        if isinstance(err, asyncio.TimeoutError):
            return f"timeout after {int(budget)}s"
        s = str(err).strip()
        return s or err.__class__.__name__

    try:
        v0 = time.monotonic()
        vision_result = await _run_vision(req.vision_provider, v_budget)
        timings_ms["vision_ms"] = int((time.monotonic() - v0) * 1000)
        meta_base["vision_provider_used"] = getattr(req.vision_provider, "value", str(req.vision_provider))
    except Exception as e:
        if req.vision_provider == VisionProvider.DOUBAO:
            probe = _probe_url_head(_first_public_image_url(req.images))
            # Fallback to qwen3 within remaining budget.
            v_budget2 = min(float(settings.grade_vision_timeout_seconds), remaining_seconds())
            if v_budget2 <= 0:
                persist_question_bank(
                    session_id=session_for_ctx,
                    bank=_merge_bank_meta(
                        {
                        "session_id": session_for_ctx,
                        "subject": req.subject.value if hasattr(req.subject, "value") else str(req.subject),
                        "vision_raw_text": None,
                        "page_image_urls": [str(img.url) for img in (req.images or []) if getattr(img, "url", None)],
                        "questions": {},
                        },
                        meta_base,
                    ),
                    grade_status="failed",
                    grade_summary="Vision analysis not available",
                    grade_warnings=[w for w in [
                        f"Vision(doubao) failed: {_vision_err_str(e, v_budget)}",
                        probe,
                        "grade SLA exceeded before vision fallback",
                    ] if w],
                    timings_ms=timings_ms,
                )
                return GradeResponse(
                    wrong_items=[],
                    summary="Vision analysis not available",
                    subject=req.subject,
                    job_id=None,
                    session_id=session_for_ctx,
                    status="failed",
                    total_items=None,
                    wrong_count=None,
                    cross_subject_flag=None,
                    warnings=[w for w in [
                        f"Vision(doubao) failed: {_vision_err_str(e, v_budget)}",
                        probe,
                        "grade SLA exceeded before vision fallback",
                    ] if w],
                    vision_raw_text=None,
                )
            try:
                # Strong fallback: if URL fetch is flaky for cloud providers, convert URLs to base64 locally for Qwen3.
                converted_images: List[Any] = []
                converted_any = False
                for img in req.images or []:
                    if getattr(img, "base64", None):
                        converted_images.append(img)
                        continue
                    url = getattr(img, "url", None)
                    if url:
                        data_uri = _download_as_data_uri(str(url))
                        if data_uri:
                            converted_any = True
                            converted_images.append(type(img)(base64=data_uri))
                        else:
                            converted_images.append(img)
                    else:
                        converted_images.append(img)

                if converted_any:
                    vision_result = await _call_blocking_in_thread(
                        vision_client.analyze,
                        images=converted_images,
                        prompt=vision_prompt,
                        provider=VisionProvider.QWEN3,
                        timeout_seconds=v_budget2,
                        semaphore=VISION_SEMAPHORE,
                    )
                else:
                    vision_result = await _run_vision(VisionProvider.QWEN3, v_budget2)
                meta_base["vision_provider_used"] = VisionProvider.QWEN3.value
                meta_base["vision_used_base64_fallback"] = bool(converted_any)
                vision_fallback_warning = (
                    f"Vision(doubao) 失败，已回退到 qwen3: {_vision_err_str(e, v_budget)}"
                    + (f"；{probe}" if probe else "")
                    + ("；qwen3 使用本地下载+base64 兜底" if converted_any else "")
                )
            except Exception as e2:
                persist_question_bank(
                    session_id=session_for_ctx,
                    bank=_merge_bank_meta(
                        {
                        "session_id": session_for_ctx,
                        "subject": req.subject.value if hasattr(req.subject, "value") else str(req.subject),
                        "vision_raw_text": None,
                        "page_image_urls": [str(img.url) for img in (req.images or []) if getattr(img, "url", None)],
                        "questions": {},
                        },
                        meta_base,
                    ),
                    grade_status="failed",
                    grade_summary="Vision analysis not available",
                    grade_warnings=[w for w in [
                        f"Vision(doubao) failed: {_vision_err_str(e, v_budget)}",
                        probe,
                        f"Vision fallback (qwen3) also failed: {_vision_err_str(e2, v_budget2)}",
                    ] if w],
                    timings_ms=timings_ms,
                )
                return GradeResponse(
                    wrong_items=[],
                    summary="Vision analysis not available",
                    subject=req.subject,
                    job_id=None,
                    session_id=session_for_ctx,
                    status="failed",
                    total_items=None,
                    wrong_count=None,
                    cross_subject_flag=None,
                    warnings=[w for w in [
                        f"Vision(doubao) failed: {_vision_err_str(e, v_budget)}",
                        probe,
                        f"Vision fallback (qwen3) also failed: {_vision_err_str(e2, v_budget2)}",
                    ] if w],
                    vision_raw_text=None,
                )
        else:
            persist_question_bank(
                session_id=session_for_ctx,
                bank=_merge_bank_meta(
                    {
                    "session_id": session_for_ctx,
                    "subject": req.subject.value if hasattr(req.subject, "value") else str(req.subject),
                    "vision_raw_text": None,
                    "page_image_urls": [str(img.url) for img in (req.images or []) if getattr(img, "url", None)],
                    "questions": {},
                    },
                    meta_base,
                ),
                grade_status="failed",
                grade_summary="Vision analysis not available",
                grade_warnings=[f"Vision analysis failed: {_vision_err_str(e, v_budget)}"],
                timings_ms=timings_ms,
            )
            return GradeResponse(
                wrong_items=[],
                summary="Vision analysis not available",
                subject=req.subject,
                job_id=None,
                session_id=session_for_ctx,
                status="failed",
                total_items=None,
                wrong_count=None,
                cross_subject_flag=None,
                warnings=[f"Vision analysis failed: {_vision_err_str(e, v_budget)}"],
                vision_raw_text=None,
            )

    llm_client = LLMClient()

    def _needs_fallback(result: Any) -> bool:
        """Detect Ark grading failure that should fall back to Qwen3."""
        summary = (getattr(result, "summary", "") or "").strip()
        if summary.startswith("批改失败") or summary.startswith("批改结果解析失败"):
            return True
        warnings = getattr(result, "warnings", None) or []
        for w in warnings:
            w_str = str(w)
            if any(
                key in w_str
                # Note: don't treat "Parse error" as fatal here because we may have already fallen back to Qwen3,
                # and we still want to return a successful grading result if the fallback succeeded.
                for key in ("InvalidEndpointOrModel", "NotFound", "Error code")
            ):
                return True
        return False

    try:
        if req.subject == Subject.MATH:
            async def _grade_math(provider: str):
                b = min(float(settings.grade_llm_timeout_seconds), remaining_seconds())
                if b <= 0:
                    raise asyncio.TimeoutError(
                        f"grade SLA exceeded before LLM started (elapsed={int(time.monotonic()-started)}s)"
                    )
                return await _call_blocking_in_thread(
                    llm_client.grade_math,
                    text_content=vision_result.text,
                    provider=provider,
                    timeout_seconds=b,
                    semaphore=LLM_SEMAPHORE,
                )

            try:
                g0 = time.monotonic()
                grading_result = await _grade_math(provider_str)
                timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                meta_base["llm_provider_used"] = provider_str
            except Exception as e:
                if provider_str == "ark":
                    g0 = time.monotonic()
                    grading_result = await _grade_math("silicon")
                    timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                    meta_base["llm_provider_used"] = "silicon"
                    meta_base["llm_used_fallback"] = True
                    grading_result.warnings = (grading_result.warnings or []) + [
                        f"Ark grading error, fell back to qwen3: {str(e)}"
                    ]
                else:
                    raise

            if provider_str == "ark" and _needs_fallback(grading_result):
                ark_summary = grading_result.summary
                ark_warnings = grading_result.warnings or []
                g0 = time.monotonic()
                grading_result = await _grade_math("silicon")
                timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                meta_base["llm_provider_used"] = "silicon"
                meta_base["llm_used_fallback"] = True
                grading_result.warnings = (grading_result.warnings or []) + [
                    f"Ark grading unavailable, fell back to qwen3. Ark summary: {ark_summary}"
                ] + ark_warnings

            grading_result.wrong_items = sanitize_wrong_items(grading_result.wrong_items)

            # Canonicalize wrong_items from the full question list whenever available.
            # This guarantees stable question_number routing for chat/UI (even if the model forgot to fill it in wrong_items).
            questions_list = getattr(grading_result, "questions", None) or []
            if isinstance(questions_list, list) and questions_list:
                grading_result.wrong_items = derive_wrong_items_from_questions(questions_list)
            else:
                # If wrong_items miss schema-required fields, derive from questions (best-effort fallback).
                wrong_items_invalid = (
                    not grading_result.wrong_items
                    or any(
                        (not isinstance(it, dict))
                        or (not isinstance(it.get("reason"), str))
                        or (not it.get("reason"))
                        for it in grading_result.wrong_items
                    )
                )
                if wrong_items_invalid:
                    grading_result.wrong_items = derive_wrong_items_from_questions(
                        getattr(grading_result, "questions", None) or []
                    )
            grading_result.wrong_items = dedupe_wrong_items(grading_result.wrong_items)
            grading_result.wrong_items = assign_stable_item_ids(grading_result.wrong_items)
            grading_result.wrong_items = sanitize_wrong_items(grading_result.wrong_items)

        elif req.subject == Subject.ENGLISH:
            async def _grade_english(provider: str):
                b = min(float(settings.grade_llm_timeout_seconds), remaining_seconds())
                if b <= 0:
                    raise asyncio.TimeoutError(
                        f"grade SLA exceeded before LLM started (elapsed={int(time.monotonic()-started)}s)"
                    )
                return await _call_blocking_in_thread(
                    llm_client.grade_english,
                    text_content=vision_result.text,
                    mode=req.mode or SimilarityMode.NORMAL,
                    provider=provider,
                    timeout_seconds=b,
                    semaphore=LLM_SEMAPHORE,
                )

            try:
                g0 = time.monotonic()
                grading_result = await _grade_english(provider_str)
                timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                meta_base["llm_provider_used"] = provider_str
            except Exception as e:
                if provider_str == "ark":
                    g0 = time.monotonic()
                    grading_result = await _grade_english("silicon")
                    timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                    meta_base["llm_provider_used"] = "silicon"
                    meta_base["llm_used_fallback"] = True
                    grading_result.warnings = (grading_result.warnings or []) + [
                        f"Ark grading error, fell back to qwen3: {str(e)}"
                    ]
                else:
                    raise

            if provider_str == "ark" and _needs_fallback(grading_result):
                ark_summary = grading_result.summary
                ark_warnings = grading_result.warnings or []
                g0 = time.monotonic()
                grading_result = await _grade_english("silicon")
                timings_ms["llm_ms"] = int((time.monotonic() - g0) * 1000)
                meta_base["llm_provider_used"] = "silicon"
                meta_base["llm_used_fallback"] = True
                grading_result.warnings = (grading_result.warnings or []) + [
                    f"Ark grading unavailable, fell back to qwen3. Ark summary: {ark_summary}"
                ] + ark_warnings
            grading_result.wrong_items = sanitize_wrong_items(grading_result.wrong_items)
            questions_list = getattr(grading_result, "questions", None) or []
            if isinstance(questions_list, list) and questions_list:
                grading_result.wrong_items = derive_wrong_items_from_questions(questions_list)
            else:
                wrong_items_invalid = (
                    not grading_result.wrong_items
                    or any(
                        (not isinstance(it, dict))
                        or (not isinstance(it.get("reason"), str))
                        or (not it.get("reason"))
                        for it in grading_result.wrong_items
                    )
                )
                if wrong_items_invalid:
                    grading_result.wrong_items = derive_wrong_items_from_questions(
                        getattr(grading_result, "questions", None) or []
                    )
            grading_result.wrong_items = dedupe_wrong_items(grading_result.wrong_items)
            grading_result.wrong_items = assign_stable_item_ids(grading_result.wrong_items)
            grading_result.wrong_items = sanitize_wrong_items(grading_result.wrong_items)

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported subject: {req.subject}",
            )

    except asyncio.TimeoutError as e:
        # Save vision-only qbank so /chat can still route by question number.
        if session_for_ctx:
            page_urls = [img.url for img in req.images if getattr(img, "url", None)]
            persist_question_bank(
                session_id=session_for_ctx,
                bank=_merge_bank_meta(
                    build_question_bank_from_vision_raw_text(
                    session_id=session_for_ctx,
                    subject=req.subject,
                    vision_raw_text=vision_result.text,
                    page_image_urls=[str(u) for u in page_urls if u],
                ),
                    meta_base,
                ),
                grade_status="failed",
                grade_summary="LLM grading timeout",
                grade_warnings=[f"LLM timeout: {str(e)}"],
                timings_ms=timings_ms,
            )
        return GradeResponse(
            wrong_items=[],
            summary="LLM grading timeout",
            subject=req.subject,
            job_id=None,
            session_id=session_for_ctx,
            status="failed",
            total_items=None,
            wrong_count=None,
            cross_subject_flag=None,
            warnings=[f"LLM timeout: {str(e)}"],
            vision_raw_text=vision_result.text,
        )
    except Exception as e:
        if session_for_ctx:
            page_urls = [img.url for img in req.images if getattr(img, "url", None)]
            persist_question_bank(
                session_id=session_for_ctx,
                bank=_merge_bank_meta(
                    build_question_bank_from_vision_raw_text(
                    session_id=session_for_ctx,
                    subject=req.subject,
                    vision_raw_text=vision_result.text,
                    page_image_urls=[str(u) for u in page_urls if u],
                ),
                    meta_base,
                ),
                grade_status="failed",
                grade_summary=f"LLM grading failed: {str(e)}",
                grade_warnings=[f"LLM error: {str(e)}"],
                timings_ms=timings_ms,
            )
        return GradeResponse(
            wrong_items=[],
            summary=f"LLM grading failed: {str(e)}",
            subject=req.subject,
            job_id=None,
            session_id=session_for_ctx,
            status="failed",
            total_items=None,
            wrong_count=None,
            cross_subject_flag=None,
            warnings=[f"LLM error: {str(e)}"],
            vision_raw_text=vision_result.text,
        )

    # If parsing still failed after fallbacks, treat grading as failed (avoid "done but empty").
    if _needs_fallback(grading_result):
        if session_for_ctx:
            page_urls = [img.url for img in req.images if getattr(img, "url", None)]
            persist_question_bank(
                session_id=session_for_ctx,
                bank=_merge_bank_meta(
                    build_question_bank_from_vision_raw_text(
                    session_id=session_for_ctx,
                    subject=req.subject,
                    vision_raw_text=vision_result.text,
                    page_image_urls=[str(u) for u in page_urls if u],
                ),
                    meta_base,
                ),
                grade_status="failed",
                grade_summary=(getattr(grading_result, "summary", "") or "批改失败").strip(),
                grade_warnings=(getattr(grading_result, "warnings", None) or [])
                + ([vision_fallback_warning] if vision_fallback_warning else []),
                timings_ms=timings_ms,
            )
        return GradeResponse(
            wrong_items=sanitize_wrong_items(getattr(grading_result, "wrong_items", []) or []),
            summary=(getattr(grading_result, "summary", "") or "批改失败").strip(),
            subject=req.subject,
            job_id=None,
            session_id=session_for_ctx,
            status="failed",
            total_items=getattr(grading_result, "total_items", None),
            wrong_count=getattr(grading_result, "wrong_count", None),
            cross_subject_flag=getattr(grading_result, "cross_subject_flag", None),
            warnings=(getattr(grading_result, "warnings", None) or []) + ([vision_fallback_warning] if vision_fallback_warning else []),
            vision_raw_text=vision_result.text,
        )

    # Persist question bank snapshot (full question list) for chat routing.
    if session_for_ctx:
        page_urls = [img.url for img in req.images if getattr(img, "url", None)]
        questions = getattr(grading_result, "questions", None) or []
        if isinstance(questions, list) and questions:
            bank = build_question_bank(
                session_id=session_for_ctx,
                subject=req.subject,
                questions=questions,
                vision_raw_text=vision_result.text,
                page_image_urls=page_urls,
            )
            persist_question_bank(
                session_id=session_for_ctx,
                bank=_merge_bank_meta(bank, meta_base),
                grade_status="done",
                grade_summary=(getattr(grading_result, "summary", "") or "").strip(),
                grade_warnings=(getattr(grading_result, "warnings", None) or [])
                + ([vision_fallback_warning] if vision_fallback_warning else []),
                timings_ms=timings_ms,
            )

    # Defensive: if LLM didn't output counts, compute from normalized results.
    if getattr(grading_result, "wrong_count", None) is None:
        try:
            grading_result.wrong_count = len(getattr(grading_result, "wrong_items", []) or [])
        except Exception:
            grading_result.wrong_count = None
    if getattr(grading_result, "total_items", None) is None:
        try:
            qs = getattr(grading_result, "questions", None) or []
            grading_result.total_items = len(qs) if isinstance(qs, list) and qs else None
        except Exception:
            grading_result.total_items = None

    return GradeResponse(
        wrong_items=grading_result.wrong_items,
        summary=grading_result.summary,
        subject=req.subject,
        job_id=None,
        session_id=session_for_ctx,
        status="done",
        total_items=grading_result.total_items,
        wrong_count=grading_result.wrong_count,
        cross_subject_flag=grading_result.cross_subject_flag,
        warnings=((grading_result.warnings or []) + ([vision_fallback_warning] if vision_fallback_warning else [])),
        vision_raw_text=vision_result.text,
    )


async def background_grade(job_id: str, req: GradeRequest, provider_str: str):
    """后台执行批改，更新 job_cache。"""
    try:
        result = await perform_grading(req, provider_str)
        cache_store.set(
            f"job:{job_id}",
            {
                "status": "done",
                "created_at": datetime.now().isoformat(),
                "request": req.model_dump(),
                "result": result.model_dump(),
                "finished_at": datetime.now().isoformat(),
            },
            ttl_seconds=IDP_TTL_HOURS * 3600,
        )
    except Exception as e:
        cache_store.set(
            f"job:{job_id}",
            {
                "status": "failed",
                "created_at": datetime.now().isoformat(),
                "request": req.model_dump(),
                "result": None,
                "error": str(e),
                "finished_at": datetime.now().isoformat(),
            },
            ttl_seconds=IDP_TTL_HOURS * 3600,
        )


def background_build_question_index(session_id: str, page_urls: List[str]) -> None:
    """Best-effort background job: build bbox/slice index and store in cache."""
    try:
        index = _build_question_index_for_pages(page_urls)
        save_question_index(session_id, index)
    except Exception as e:
        save_question_index(session_id, {"questions": {}, "warnings": [f"question index build failed: {str(e)}"]})


def validate_images(images: List[Any], provider: VisionProvider):
    """Early validation of image inputs to fail fast."""
    for idx, img in enumerate(images):
        if img.url:
            url_str = str(img.url)
            if not (url_str.startswith("http://") or url_str.startswith("https://")):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: URL must be HTTP/HTTPS"
                )
            if "localhost" in url_str or "127.0.0.1" in url_str:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: URL must be public (no localhost/127)"
                )
        elif img.base64:
            if provider == VisionProvider.DOUBAO:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: Doubao provider only accepts URLs, not Base64"
                )
            # Estimate size: len * 0.75
            est_size = len(img.base64) * 0.75
            if est_size > 20 * 1024 * 1024:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: Base64 image too large (>20MB), please use URL"
                )


@router.post("/grade", response_model=GradeResponse, status_code=status.HTTP_200_OK)
async def grade_homework(
    req: GradeRequest,
    background_tasks: BackgroundTasks,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """
    批改作业 API (Stub)
    """
    # 1. Early Validation（公共 URL/20MB/Doubao+base64 等）
    # 1. Early Validation
    validate_images(req.images, req.vision_provider)

    # 2. 幂等性校验
    idempotency_key = get_idempotency_key(None, x_idempotency_key)
    if idempotency_key:
        cached_response = check_idempotency(idempotency_key)
        if cached_response:
            return cached_response

    # 2.5 Ensure session_id is always present so results can be delivered to /chat
    session_for_ctx = _ensure_session_id(req.session_id or req.batch_id)
    req = req.model_copy(update={"session_id": session_for_ctx})

    # 3. 决定同步/异步
    is_large_batch = len(req.images) > 5
    provider_str = "silicon" if req.vision_provider == VisionProvider.QWEN3 else "ark"

    if is_large_batch:
        job_id = generate_job_id()
        cache_store.set(
            f"job:{job_id}",
            {
                "status": "processing",
                "created_at": datetime.now().isoformat(),
                "request": req.model_dump(),
                "result": None,
            },
            ttl_seconds=IDP_TTL_HOURS * 3600,
        )
        background_tasks.add_task(background_grade, job_id, req, provider_str)
        return GradeResponse(
            wrong_items=[],
            summary="任务已创建，正在处理中...",
            subject=req.subject,
            job_id=job_id,
            session_id=session_for_ctx,
            status="processing",
            total_items=None,
            wrong_count=None,
            cross_subject_flag=None,
            warnings=["大批量任务已转为异步处理"],
            vision_raw_text=None,
        )

    try:
        response = await perform_grading(req, provider_str)
        if session_for_ctx:
            wrong_items_payload: List[Dict[str, Any]] = []
            for item in response.wrong_items or []:
                if hasattr(item, "model_dump"):
                    wrong_items_payload.append(item.model_dump())
                elif isinstance(item, dict):
                    wrong_items_payload.append(item)
                else:
                    # last resort: attempt dict() conversion
                    try:
                        wrong_items_payload.append(dict(item))
                    except Exception:
                        continue
            save_mistakes(session_for_ctx, wrong_items_payload)
            # QIndex: enqueue bbox/slice indexing job to external worker (Redis required)
            page_urls = [img.url for img in req.images if getattr(img, "url", None)]
            if page_urls:
                enqueued = enqueue_qindex_job(session_for_ctx, [str(u) for u in page_urls if u])
                if enqueued:
                    save_question_index(session_for_ctx, {"questions": {}, "warnings": ["qindex queued"]})
                else:
                    save_question_index(session_for_ctx, {"questions": {}, "warnings": ["qindex queue unavailable; skipped"]})
        if idempotency_key:
            cache_response(idempotency_key, response)
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


async def chat_stream(
    req: ChatRequest,
    request: Request,
    last_event_id: Optional[str] = Header(None),
) -> AsyncIterator[bytes]:
    """
    SSE流式苏格拉底辅导:
    - heartbeat/chat/done/error事件
    - 5轮对话上限
    - Session 24小时TTL
    - last-event-id支持断线续接(仅用于恢复session)
    """
    llm_client = LLMClient()

    # session恢复或创建；last_event_id 用于断线续接（仅恢复 session_id）
    session_id = req.session_id or last_event_id or f"session_{uuid.uuid4().hex[:8]}"
    now_ts = _now_ts()
    session_data = get_session(session_id)

    # TTL检查，超期则报错
    if session_data:
        updated_ts = _coerce_ts(session_data.get("updated_at")) or now_ts
        if now_ts - updated_ts > SESSION_TTL_SECONDS:
            delete_session(session_id)
            error_msg = json.dumps({"code": "SESSION_EXPIRED", "message": "session expired"})
            yield f"event: error\ndata: {error_msg}\n\n".encode("utf-8")
            yield b"event: done\ndata: {\"status\":\"error\"}\n\n"
            return

    if not session_data:
        # last-event-id 提供但不存在的情况
        if last_event_id and not req.session_id:
            error_msg = json.dumps({"code": "SESSION_NOT_FOUND", "message": "session not found"})
            yield f"event: error\ndata: {error_msg}\n\n".encode("utf-8")
            yield b"event: done\ndata: {\"status\":\"error\"}\n\n"
            return
        session_data = {
            "history": req.history or [],
            "interaction_count": 0,
            "created_at": now_ts,
            "updated_at": now_ts,
            "context_item_ids": normalize_context_ids(req.context_item_ids or []),
        }
        save_session(session_id, session_data)

    # 不再做硬性 turn limit 检查

    # Normalize past assistant messages for display (avoid raw LaTeX delimiters in UI).
    try:
        hist = session_data.get("history") or []
        if isinstance(hist, list):
            for m in hist:
                if isinstance(m, dict) and m.get("role") == "assistant" and isinstance(m.get("content"), str):
                    m["content"] = _format_math_for_display(m.get("content") or "")
            session_data["history"] = hist
    except Exception:
        pass

    # Heartbeat
    yield b"event: heartbeat\ndata: {}\n\n"

    # 如果提供 last_event_id 且无显式 session_id，尝试重放上一条 assistant 消息，便于客户端续接
    if last_event_id and not req.session_id and session_data["history"]:
        replay_msgs = assistant_tail(session_data["history"], max_messages=3)
        for msg in replay_msgs:
            payload = ChatResponse(
                messages=[msg],
                session_id=session_id,
                retry_after_ms=None,
                cross_subject_flag=None,
            )
            yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")

    try:
        # Chat 默认使用 doubao (Ark) 推理模型（由环境变量 ARK_REASONING_MODEL 配置）
        provider_str = "ark"
        allowed_chat_models = {get_settings().ark_reasoning_model}
        model_override = None
        if req.llm_model:
            if req.llm_model not in allowed_chat_models:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid llm_model for chat. Allowed: {sorted(allowed_chat_models)}",
                )
            model_override = req.llm_model
        current_turn = session_data["interaction_count"]

        # 构造上下文：强制依赖 qbank（全题快照）。
        # 需求：chat 只能基于 /grade 交付的“识别/判定/题目信息”对话；缺失则直接提示先批改，禁止编造。
        qbank = get_question_bank(session_id) if session_id else None
        if not (isinstance(qbank, dict) and isinstance(qbank.get("questions"), dict) and qbank.get("questions")):
            msg = (
                "我还没有拿到本次作业的“题库快照”（识别原文/判定结果/题目信息）。"
                "请先在【智能批改】里上传照片并完成批改，然后用返回的 session_id 再来辅导。"
            )
            session_data["history"].append({"role": "assistant", "content": msg})
            save_session(session_id, session_data)
            payload = ChatResponse(
                messages=[{"role": "assistant", "content": msg}],
                session_id=session_id,
                retry_after_ms=None,
                cross_subject_flag=None,
            )
            yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")
            yield b"event: done\ndata: {\"status\":\"error\",\"session_id\":\"%b\"}\n\n" % session_id.encode("utf-8")
            return

        bank_questions = qbank.get("questions")
        bank_questions_str: Dict[str, Any] = {str(k): v for k, v in (bank_questions or {}).items()}
        available_qnums = sorted(bank_questions_str.keys(), key=len, reverse=True)

        wrong_item_context: Dict[str, Any] = {
            "available_question_numbers": available_qnums[:200],
        }

        # Determine requested question number (explicit) and bind focus deterministically.
        requested_qn = _extract_requested_question_number(req.question)
        requested_qn = _normalize_question_number(requested_qn) if requested_qn else None
        if requested_qn:
            # If user explicitly asked for a question that does not exist, do NOT keep old focus.
            if requested_qn not in bank_questions_str:
                # Allow prefix matching: "28" -> "28(1)②" etc.
                candidates = [k for k in available_qnums if str(k).startswith(f"{requested_qn}(") or str(k).startswith(requested_qn)]
                if candidates:
                    requested_qn = sorted(candidates, key=len)[0]
                else:
                    msg = (
                        f"我没能在本次批改结果里定位到第{requested_qn}题的题干/选项信息。"
                        + (f" 当前可聊题号：{', '.join(available_qnums[:30])}。" if available_qnums else "")
                        + " 你可以换一个题号再问，或重新上传更清晰的照片后再批改一次。"
                    )
                    session_data["history"].append({"role": "assistant", "content": msg})
                    save_session(session_id, session_data)
                    payload = ChatResponse(
                        messages=[{"role": "assistant", "content": msg}],
                        session_id=session_id,
                        retry_after_ms=None,
                        cross_subject_flag=None,
                    )
                    yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")
                    yield b"event: done\ndata: {\"status\":\"continue\",\"session_id\":\"%b\"}\n\n" % session_id.encode("utf-8")
                    return
            session_data["focus_question_number"] = str(requested_qn)
        else:
            # Heuristic: choose best match among available numbers mentioned in the message.
            mentioned = _select_question_number_from_text(req.question, available_qnums)
            if mentioned:
                session_data["focus_question_number"] = str(mentioned)

        focus_q = session_data.get("focus_question_number")
        focus_q = str(focus_q) if focus_q is not None else None
        if focus_q and focus_q in bank_questions_str:
            focus_payload = dict(bank_questions_str.get(focus_q) or {})
            focus_payload["question_number"] = str(focus_q)

            # Add image refs if available (bbox/slice index) - optional enhancement only.
            qindex = get_question_index(session_id) if session_id else None
            if isinstance(qindex, dict):
                qidx_questions = qindex.get("questions")
                if isinstance(qidx_questions, dict) and focus_q in qidx_questions:
                    focus_payload["image_refs"] = qidx_questions.get(focus_q)
                if qindex.get("warnings"):
                    wrong_item_context["index_warnings"] = qindex.get("warnings")

            # Always keep page urls for potential "re-look the page" fallback (geometry etc.)
            page_urls = qbank.get("page_image_urls")
            if isinstance(page_urls, list) and page_urls:
                focus_payload["page_image_urls"] = page_urls

            wrong_item_context["focus_question_number"] = str(focus_q)
            wrong_item_context["focus_question"] = focus_payload
        else:
            # No focus yet: ask user to specify a question number (avoid hallucination).
            msg = (
                "你想先聊哪一题？请直接说“讲第几题”。"
                + (f" 当前可聊题号：{', '.join(available_qnums[:30])}。" if available_qnums else "")
            )
            session_data["history"].append({"role": "assistant", "content": msg})
            save_session(session_id, session_data)
            payload = ChatResponse(
                messages=[{"role": "assistant", "content": msg}],
                session_id=session_id,
                retry_after_ms=None,
                cross_subject_flag=None,
            )
            yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")
            yield b"event: done\ndata: {\"status\":\"continue\",\"session_id\":\"%b\"}\n\n" % session_id.encode("utf-8")
            return

        # Capture user corrections so the tutor can override OCR/vision misreads during the session.
        focus_q_for_corr = (
            wrong_item_context.get("focus_question_number")
            or session_data.get("focus_question_number")
        )
        corr = _extract_user_correction(req.question)
        if focus_q_for_corr and corr:
            fq = str(focus_q_for_corr)
            corr_map = session_data.setdefault("corrections", {})
            corr_list = corr_map.setdefault(fq, [])
            if not corr_list or corr_list[-1] != corr:
                corr_list.append(corr)
            corr_map[fq] = corr_list[-5:]
            wrong_item_context["user_corrections"] = corr_map[fq]
            # If we have a focused question payload, attach corrections there too for clarity.
            if isinstance(wrong_item_context.get("focus_question"), dict):
                wrong_item_context["focus_question"]["user_corrections"] = corr_map[fq]

        # Deterministic routing already handled above; if we reached here without a focus_question,
        # it's a bug, so fail safe.
        if "focus_question" not in wrong_item_context:
            msg = "系统未能绑定到具体题目，请在【智能批改】中重新批改后再试。"
            session_data["history"].append({"role": "assistant", "content": msg})
            save_session(session_id, session_data)
            payload = ChatResponse(
                messages=[{"role": "assistant", "content": msg}],
                session_id=session_id,
                retry_after_ms=None,
                cross_subject_flag=None,
            )
            yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")
            yield b"event: done\ndata: {\"status\":\"error\",\"session_id\":\"%b\"}\n\n" % session_id.encode("utf-8")
            return

        # Best-effort: re-look the focused question when the prompt hints diagram/pattern info was missed.
        try:
            focus_obj = wrong_item_context.get("focus_question")
            fqnum = wrong_item_context.get("focus_question_number")
            if (
                isinstance(focus_obj, dict)
                and fqnum
                and _should_relook_focus_question(req.question, focus_obj)
            ):
                patch = await _relook_focus_question_via_vision(
                    session_id=session_id,
                    subject=req.subject,
                    question_number=str(fqnum),
                    focus_question=focus_obj,
                )
                if isinstance(patch, dict) and patch:
                    focus_obj.update({k: v for k, v in patch.items() if v is not None})
                    wrong_item_context["focus_question"] = focus_obj
                    # Persist patch back to qbank for subsequent turns (best-effort).
                    try:
                        qbank_now = get_question_bank(session_id)
                        if isinstance(qbank_now, dict):
                            qs = qbank_now.get("questions")
                            if isinstance(qs, dict) and str(fqnum) in qs and isinstance(qs.get(str(fqnum)), dict):
                                qs[str(fqnum)].update({k: v for k, v in patch.items() if v is not None})
                                qbank_now["questions"] = qs
                                qbank_now = _merge_bank_meta(qbank_now, {"updated_at": datetime.now().isoformat()})
                                save_question_bank(session_id, qbank_now)
                    except Exception:
                        pass
        except Exception:
            pass

        # ===== True streaming: LLM token stream -> SSE chat events =====
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        DONE = object()

        # Update session immediately with user's message so LLM can see the conversation history.
        session_data["history"].append({"role": "user", "content": req.question})
        llm_history = list(session_data["history"][-12:])

        def _producer():
            try:
                for chunk in llm_client.socratic_tutor_stream(
                    question=req.question,
                    wrong_item_context=wrong_item_context,
                    session_id=session_id,
                    interaction_count=current_turn,
                    provider=provider_str,
                    model_override=model_override,
                    history=llm_history,
                ):
                    asyncio.run_coroutine_threadsafe(q.put(chunk), loop)
                asyncio.run_coroutine_threadsafe(q.put(DONE), loop)
            except Exception as ex:
                asyncio.run_coroutine_threadsafe(q.put({"error": str(ex)}), loop)

        producer_task = asyncio.create_task(asyncio.to_thread(_producer))

        # Add placeholder assistant message for streaming updates
        assistant_msg = {"role": "assistant", "content": ""}
        session_data["history"].append(assistant_msg)

        # Emit initial state so clients can render immediately
        payload = ChatResponse(
            messages=session_data["history"],
            session_id=session_id,
            retry_after_ms=None,
            cross_subject_flag=None,
        )
        yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")

        buffer = ""
        last_emit = time.monotonic()
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=10.0)
            except asyncio.TimeoutError:
                # keep connection alive during long thinking
                yield b"event: heartbeat\ndata: {}\n\n"
                continue

            if item is DONE:
                break
            if isinstance(item, dict) and item.get("error"):
                raise RuntimeError(item.get("error"))

            chunk = str(item)
            buffer += chunk
            assistant_msg["content"] = _format_math_for_display(buffer)

            # throttle event frequency
            now_m = time.monotonic()
            if now_m - last_emit >= 0.25 or chunk.endswith(("。", "！", "？", "\n")):
                payload = ChatResponse(
                    messages=session_data["history"],
                    session_id=session_id,
                    retry_after_ms=None,
                    cross_subject_flag=None,
                )
                yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")
                last_emit = now_m

        # Ensure final content is emitted
        payload = ChatResponse(
            messages=session_data["history"],
            session_id=session_id,
            retry_after_ms=None,
            cross_subject_flag=None,
        )
        yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")

        # Persist session
        session_data["interaction_count"] = current_turn + 1
        session_data["updated_at"] = _now_ts()
        save_session(session_id, session_data)

        # Status: keep it simple for now
        yield f"event: done\ndata: {{\"status\":\"continue\",\"session_id\":\"{session_id}\"}}\n\n".encode("utf-8")
        await producer_task

    except Exception as e:
        logger.error(f"Chat stream failed: {e}", exc_info=True)
        error_msg = json.dumps({"error": str(e)})
        yield f"event: error\ndata: {error_msg}\n\n".encode("utf-8")
        yield b"event: done\ndata: {\"status\":\"error\"}\n\n"


@router.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    last_event_id: Optional[str] = Header(None),
):
    return StreamingResponse(
        chat_stream(req=req, request=request, last_event_id=last_event_id),
        media_type="text/event-stream",
    )


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = cache_store.get(f"job:{job_id}")
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get("/session/{session_id}/qbank")
async def get_session_qbank_meta(session_id: str):
    """
    验收/调试接口：查看本次批改是否已将“识别/判定/题目信息”写入 qbank（供 /chat 使用）。
    默认不返回整段 vision_raw_text，避免过大。
    """
    sid = _ensure_session_id(session_id)
    bank = get_question_bank(sid)
    if not bank:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="qbank not found for session_id")

    questions = bank.get("questions") if isinstance(bank, dict) else None
    qnums: List[str] = []
    if isinstance(questions, dict):
        qnums = [str(k) for k in questions.keys()]

    meta = bank.get("meta") if isinstance(bank.get("meta"), dict) else {}
    out: Dict[str, Any] = {
        "session_id": sid,
        "subject": bank.get("subject"),
        "page_image_urls_count": len(bank.get("page_image_urls") or []) if isinstance(bank.get("page_image_urls"), list) else 0,
        "vision_raw_len": len(bank.get("vision_raw_text") or ""),
        "questions_count": len(qnums),
        "questions_with_options": _count_questions_with_options(bank),
        "question_numbers": sorted(qnums, key=len, reverse=False)[:300],
        "meta": meta,
    }
    qindex = get_question_index(sid)
    if isinstance(qindex, dict):
        out["qindex_available"] = bool(qindex.get("questions"))
        out["qindex_warnings"] = qindex.get("warnings") or []
    else:
        out["qindex_available"] = False
        out["qindex_warnings"] = []
    return out
