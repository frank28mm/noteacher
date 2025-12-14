from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Tuple
import re

from fastapi import APIRouter, HTTPException, status, Request, Header
from fastapi.responses import StreamingResponse

from homework_agent.models.schemas import (
    ChatRequest, ChatResponse, VisionProvider, ImageRef
)
from homework_agent.services.llm import LLMClient
from homework_agent.services.vision import VisionClient
from homework_agent.utils.settings import get_settings
from homework_agent.core.qbank import _normalize_question_number
from homework_agent.api.session import (
    SESSION_TTL_SECONDS,
    get_session, save_session, delete_session,
    get_question_bank, save_question_bank, get_question_index,
    _merge_bank_meta,
    _now_ts, _coerce_ts,
)
from homework_agent.utils.observability import get_request_id_from_headers, log_event

logger = logging.getLogger(__name__)

router = APIRouter()


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
    """
    Best-effort extraction of a requested question number from user text.

    IMPORTANT: avoid false-positives from math expressions like "t(t-8)+16".
    We only treat numbers as "question numbers" when:
      - the message is basically a bare question number (e.g. "20(2)"), OR
      - the number appears in an explicit "question" context (第/题/讲/聊/辅导/解释...).
    """
    if not message:
        return None
    msg = str(message).strip()
    if not msg:
        return None

    qtoken = r"(\d{1,3}(?:\s*\(\s*\d+\s*\)\s*)?(?:[①②③④⑤⑥⑦⑧⑨])?)"

    # Case 1: user sends a bare question number like "20(2)" / "28(1)②" / "27".
    bare = re.fullmatch(rf"\s*{qtoken}\s*[。．.!！?？]*\s*", msg)
    if bare:
        return _normalize_question_number(bare.group(1))

    # Case 2: explicit "question" context. Avoid capturing negatives: "-8" should not mean "第8题".
    if re.search(r"(第\s*\d|题\s*\d|\d+\s*题|讲|聊|解释|辅导|说说|再讲|再聊)", msg):
        # Prefer forms like "第20题" / "讲20(2)" / "聊第28(1)②题" / "题27".
        m = re.search(rf"第\s*{qtoken}\s*题", msg)
        if m:
            return _normalize_question_number(m.group(1))
        m = re.search(rf"(?:题\s*|题号\s*){qtoken}", msg)
        if m and not re.search(r"[-+*/^=]\s*$", msg[: m.start(1)]):
            return _normalize_question_number(m.group(1))
        m = re.search(rf"(?:讲|聊|解释|辅导|说说|再讲|再聊)\s*第?\s*{qtoken}\s*题?", msg)
        if m:
            return _normalize_question_number(m.group(1))

    return None


def _has_explicit_question_switch_intent(message: str) -> bool:
    """Heuristic: should we attempt to switch focus_question_number this turn?"""
    msg = (message or "").strip()
    if not msg:
        return False
    # Explicit cues.
    if re.search(r"(第\s*\d|题\s*\d|\d+\s*题|讲|聊|解释|辅导|换一题|下一题)", msg):
        return True
    # A bare question number should also count (e.g. "20(2)").
    return _extract_requested_question_number(msg) is not None


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
        # Avoid markdown artifacts in a chat bubble (code / strikethrough feel "unnatural" for students).
        s = s.replace("~~", "")
        s = re.sub(r"```+", "", s)
        s = s.replace("`", "")

        # Normalize LaTeX delimiters to $...$ for MathJax (demo UI injects MathJax).
        s = s.replace("\\[", "$$").replace("\\]", "$$")
        s = s.replace("\\(", "$").replace("\\)", "$")

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
    request_id = get_request_id_from_headers(request.headers) or f"req_{uuid.uuid4().hex[:12]}"
    started_m = time.monotonic()
    now_ts = _now_ts()
    session_data = get_session(session_id)
    log_event(
        logger,
        "chat_request",
        request_id=request_id,
        session_id=session_id,
        subject=getattr(req.subject, "value", str(req.subject)),
        question_len=len(req.question or ""),
        has_last_event_id=bool(last_event_id),
    )

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
            log_event(
                logger,
                "chat_qbank_missing",
                level="warning",
                request_id=request_id,
                session_id=session_id,
            )
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
                    log_event(
                        logger,
                        "chat_route_not_found",
                        level="warning",
                        request_id=request_id,
                        session_id=session_id,
                        requested_qn=requested_qn,
                        available_count=len(available_qnums),
                    )
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
            # Only attempt to switch focus when user explicitly intends to talk about a question.
            # This avoids false-positives from math expressions like "t(t-8)+16".
            if _has_explicit_question_switch_intent(req.question):
                mentioned = _select_question_number_from_text(req.question, available_qnums)
                if mentioned:
                    session_data["focus_question_number"] = str(mentioned)

        focus_q = session_data.get("focus_question_number")
        focus_q = str(focus_q) if focus_q is not None else None
        log_event(
            logger,
            "chat_focus_bound",
            request_id=request_id,
            session_id=session_id,
            focus_question_number=focus_q,
            requested_qn=requested_qn,
        )
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
            log_event(
                logger,
                "chat_context_ready",
                request_id=request_id,
                session_id=session_id,
                focus_qn=focus_q,
                has_qindex=bool(get_question_index(session_id)),
            )
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
                    log_event(
                        logger,
                        "chat_relook_applied",
                        request_id=request_id,
                        session_id=session_id,
                        focus_qn=str(fqnum),
                        patch_keys=list(patch.keys()),
                    )
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
        log_event(
            logger,
            "chat_done",
            request_id=request_id,
            session_id=session_id,
            status="continue",
            elapsed_ms=int((time.monotonic() - started_m) * 1000),
        )
        yield f"event: done\ndata: {{\"status\":\"continue\",\"session_id\":\"{session_id}\"}}\n\n".encode("utf-8")
        await producer_task

    except Exception as e:
        logger.error(f"Chat stream failed: {e}", exc_info=True)
        log_event(
            logger,
            "chat_failed",
            level="error",
            request_id=request_id,
            session_id=session_id,
            error_type=e.__class__.__name__,
            error=str(e),
            elapsed_ms=int((time.monotonic() - started_m) * 1000),
        )
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
