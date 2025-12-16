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
from homework_agent.services.qindex_queue import enqueue_qindex_job
from homework_agent.utils.settings import get_settings
from homework_agent.core.qbank import _normalize_question_number, build_question_bank_from_vision_raw_text
from homework_agent.core.slice_policy import analyze_visual_risk, should_create_slices_for_bank, pick_question_numbers_for_slices
from homework_agent.core.qindex import qindex_is_configured
from homework_agent.api.session import (
    SESSION_TTL_SECONDS,
    get_session, save_session, delete_session,
    get_question_bank, save_question_bank, get_question_index,
    save_question_index,
    save_qindex_placeholder,
    _merge_bank_meta,
    _now_ts, _coerce_ts,
)
from homework_agent.utils.observability import get_request_id_from_headers, log_event
from homework_agent.utils.user_context import get_user_id
from homework_agent.utils.submission_store import touch_submission, load_qindex_image_refs

logger = logging.getLogger(__name__)

router = APIRouter()

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

    # Normalize common fullwidth punctuation for Chinese input / voice transcription.
    msg = (
        msg.replace("（", "(")
        .replace("）", ")")
        .replace("，", ",")
        .replace("。", ".")
        .replace("？", "?")
        .replace("：", ":")
        .replace("；", ";")
    )

    qtoken = r"(\d{1,3}(?:\s*\(\s*\d+\s*\)\s*)?(?:[①②③④⑤⑥⑦⑧⑨])?)"

    # Case 1: user sends a bare question number like "20(2)" / "28(1)②" / "27".
    bare = re.fullmatch(rf"\s*{qtoken}\s*[。．.!！?？]*\s*", msg)
    if bare:
        return _normalize_question_number(bare.group(1))

    # Case 1.25: inline sub-question token anywhere (e.g. "我的20(3)哪里有问题？").
    # Safe because it requires a numeric "(n)" pattern, unlikely to appear in algebraic expressions.
    inline_sub = re.search(r"(\d{1,3}\s*\(\s*\d+\s*\)\s*(?:[①②③④⑤⑥⑦⑧⑨])?)", msg)
    if inline_sub:
        return _normalize_question_number(inline_sub.group(1))

    # Case 1.5: Chinese-style "第20题第一小题 / 20题的第一小题 / 二十题第一小题" (voice input friendly).
    # We only support a small set of Chinese ordinals for sub-question mapping.
    cn_ord_map = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }

    def _parse_cn_int(s: str) -> Optional[int]:
        s = (s or "").strip()
        if not s:
            return None
        if s.isdigit():
            try:
                return int(s)
            except ValueError:
                return None
        # Basic Chinese numerals up to 99: 十, 二十, 二十一, 十一, 三十六
        chars = [c for c in s if c in "零一二三四五六七八九十两"]
        if not chars:
            return None
        s2 = "".join("二" if c == "两" else c for c in chars)
        if s2 == "十":
            return 10
        if "十" in s2:
            parts = s2.split("十")
            left = parts[0]
            right = parts[1] if len(parts) > 1 else ""
            tens = cn_ord_map.get(left, 1) if left else 1
            ones = cn_ord_map.get(right, 0) if right else 0
            return tens * 10 + ones
        # single digit
        return cn_ord_map.get(s2)

    # Match like: "讲解20题的第一小题" / "二十题第一小题" / "第20题(1)" etc.
    m_sub = re.search(
        r"(?:第\s*)?([0-9一二三四五六七八九十两]{1,6})\s*题.*?(?:第\s*)?([0-9一二三四五六七八九十]{1,3})\s*(?:小题|小问|问)",
        msg,
    )
    if m_sub:
        base = _parse_cn_int(m_sub.group(1))
        sub = _parse_cn_int(m_sub.group(2))
        if base and sub:
            return _normalize_question_number(f"{base}({sub})")

    # Case 2: explicit "question" context. Avoid capturing negatives: "-8" should not mean "第8题".
    if re.search(r"(第\s*\d|题\s*\d|\d+\s*题|讲|聊|解释|辅导|说说|再讲|再聊)", msg):
        # Prefer forms like "第20题" / "讲20(2)" / "聊第28(1)②题" / "题27".
        m = re.search(rf"第\s*{qtoken}\s*题", msg)
        if m:
            return _normalize_question_number(m.group(1))
        # "20题" form (common Chinese input)
        m = re.search(rf"{qtoken}\s*题", msg)
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
    msg = msg.replace("（", "(").replace("）", ")")
    # Explicit cues.
    if re.search(r"(第\s*\d|题\s*\d|\d+\s*题|讲|聊|解释|辅导|换一题|下一题)", msg):
        return True
    # A bare question number should also count (e.g. "20(2)").
    if re.search(r"\d{1,3}\s*\(\s*\d+\s*\)", msg):
        return True
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


def _qindex_has_slices_for_question(qindex: Dict[str, Any], question_number: str) -> bool:
    if not isinstance(qindex, dict) or not question_number:
        return False
    qs = qindex.get("questions")
    if not isinstance(qs, dict):
        return False
    q = qs.get(str(question_number))
    if not isinstance(q, dict):
        return False
    pages = q.get("pages")
    if not isinstance(pages, list):
        return False
    for p in pages:
        if not isinstance(p, dict):
            continue
        su = p.get("slice_image_urls") or p.get("slice_image_url")
        if isinstance(su, str) and su.strip():
            return True
        if isinstance(su, list) and any(str(u).strip() for u in su if u):
            return True
        regions = p.get("regions")
        if isinstance(regions, list) and any(isinstance(r, dict) and r.get("slice_image_url") for r in regions):
            return True
    return False


def _user_requests_visual_check(message: str) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    return any(
        k in msg
        for k in (
            "看图",
            "如图",
            "见图",
            "你看不到图",
            "看不到图",
            "看不到图片",
            "你没看到图",
            "你没看图",
            "形状"
            "位置关系",
            "表格",
            "统计图",
            "折线图",
            "柱状图",
            "图形拼接",
            "数列规律",
            "图不对",
            "和图对不上",
            "图不正确",
            "二次函数",
            "二次函数图",
            "函数图像",
            "几何",
            "正方形",
            "长方形",
            "三角形",
            "平行四边形",
            "矩形",
            "正方体",
            "长方体",
            "圆锥",
        )
    )


def _should_relook_focus_question(user_msg: str, focus_question: Dict[str, Any]) -> bool:
    """Heuristic: decide whether to re-run Vision for a focused question (diagram/pattern issues)."""
    msg = (user_msg or "").strip()
    qcontent = str((focus_question or {}).get("question_content") or "")
    warnings = focus_question.get("warnings") or []
    warnings_s = " ".join([str(w) for w in warnings]) if isinstance(warnings, list) else str(warnings)

    # Avoid repeated re-looks unless the user explicitly challenges recognition again.
    already_relooked = bool((focus_question or {}).get("vision_recheck_text")) or bool((focus_question or {}).get("relook_error"))

    # User explicitly challenges recognition / asks to see the exact problem.
    if any(
        k in msg
        for k in (
            "题目不对",
            "识别错",
            "你识别到的题目",
            "看不清",
            "原题",
            "题干不对",
            "你看一下图",
            "看不到图",
            "看不到图片",
            "你看不到图",
            "你没看到图",
            "你没看图",
            "你有没有看图",
            "图在哪里",
        )
    ):
        return True

    if already_relooked:
        return False

    # If grade flagged this question as visually risky, proactively re-look once on first entry.
    if (focus_question or {}).get("visual_risk") is True:
        if _extract_requested_question_number(msg) or _has_explicit_question_switch_intent(msg):
            return True

    # Pattern/diagram questions often need the visual example; if missing, relook.
    if "可能误读规律" in warnings_s or "可能误读公式" in warnings_s:
        if ("→" not in qcontent) and ("顺序" not in qcontent) and ("规律" in qcontent or "出现" in qcontent):
            return True

    # Very short stems are suspicious for multi-part questions.
    if len(qcontent) < 18 and any(k in qcontent for k in ("出现", "规律", "图", "示意")):
        return True

    # Geometry/diagram disputes: if the user argues about angle/position relations, relook once.
    if any(k in msg for k in ("同位角", "内错角", "位置关系", "像F", "像Z", "左侧", "右侧", "上方", "下方")):
        if ("图" in qcontent) or ((focus_question or {}).get("visual_risk") is True):
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

    # Prefer local download + data URI to avoid provider-side URL fetch flakiness.
    data_uri = _download_as_data_uri(img_url)
    prefer_ark = bool(settings.ark_api_key and settings.ark_base_url)
    provider = VisionProvider.DOUBAO if prefer_ark else VisionProvider.QWEN3
    images = [ImageRef(base64=data_uri)] if data_uri else [ImageRef(url=img_url)]

    prompt = (
        f"请只关注第{question_number}题。"
        "如果题目包含示意图/箭头/表格/序列示例（如 ABCD 出现顺序、对应数字位置），必须原样抄写示例并用文字说明顺序/位置关系；不要推断。"
        "请输出：题目原文、选项（如有）、学生作答（如有）、学生作答状态，以及任何“可能误读公式/规律”的风险提示。"
    )
    # Re-look is user-facing; keep it bounded but not so short that it always times out on slow vision.
    budget = min(60.0, float(settings.grade_vision_timeout_seconds))
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
    except asyncio.TimeoutError:
        return {"relook_error": f"重识别超时: {int(budget)}s"}
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
        # Hard-ban tildes because they trigger markdown strikethrough and also appear as casual tone markers.
        s = s.replace("~", "").replace("～", "")
        s = re.sub(r"```+", "", s)
        s = s.replace("`", "")
        # Strip HTML strikethrough tags if the model emits them.
        s = re.sub(r"</?\s*(?:del|s|strike)\b[^>]*>", "", s, flags=re.IGNORECASE)
        # Strip unicode combining long stroke (strikethrough-like) if present.
        s = re.sub(r"[\u0336\u0335\u0334\u0333]", "", s)

        # Best-effort normalization:
        # - keep TeX in-place (Gradio Chatbot handles LaTeX rendering via latex_delimiters)
        # - normalize \(...\), \[...\] to $...$, $$...$$
        # - strip boldsymbol wrappers for readability
        s = s.replace("\\[", "$$").replace("\\]", "$$")
        s = s.replace("\\(", "$").replace("\\)", "$")
        s = re.sub(r"\\boldsymbol\{([^{}]+)\}", r"\1", s)

        # Some providers/models return *double-escaped* LaTeX commands inside $...$,
        # e.g. `\\frac{3}{8}` which breaks MathJax (treated as a newline `\\` + text).
        # Fix ONLY inside math blocks to avoid mangling normal text.
        def _fix_latex_inner(inner: str) -> str:
            if not inner:
                return inner
            # Convert "\\frac" -> "\frac", "\\pm" -> "\pm", etc. (only when a command name follows).
            inner = re.sub(r"\\\\([A-Za-z]+)", r"\\\1", inner)
            # Spacing commands: "\\," "\\;" "\\!" -> "\," "\;" "\!"
            inner = re.sub(r"\\\\([,;!])", r"\\\1", inner)
            # Improve mixed-number readability: 99\frac{3}{8} -> 99\,\frac{3}{8}
            inner = re.sub(r"(\d)(\\(?:frac|tfrac)\b)", r"\1\\,\2", inner)
            return inner

        def _fix_display(m: re.Match) -> str:
            inner = _fix_latex_inner(m.group(1))
            # Also remove nested single-$ markers inside display blocks.
            inner = inner.replace("$", "")
            return "$$" + inner + "$$"

        def _fix_inline(m: re.Match) -> str:
            return "$" + _fix_latex_inner(m.group(1)) + "$"

        # Fix display first, then inline (avoid $$ being caught by inline regex).
        s = re.sub(r"\$\$(.*?)\$\$", _fix_display, s, flags=re.S)
        s = re.sub(r"(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)", _fix_inline, s, flags=re.S)

        # Best-effort: convert programming-style powers outside math blocks, e.g. x^(6n) -> $x^{6n}$.
        # This is intentionally conservative (avoid touching already-formatted LaTeX).
        def _protect_math(m: re.Match) -> str:
            idx = len(_protected)
            _protected.append(m.group(0))
            return f"@@MATH{idx}@@"

        _protected: List[str] = []
        s2 = re.sub(r"\$\$.*?\$\$", _protect_math, s, flags=re.S)
        s2 = re.sub(r"(?<!\$)\$(?!\$).*?(?<!\$)\$(?!\$)", _protect_math, s2, flags=re.S)
        s2 = re.sub(
            r"\b([A-Za-z][A-Za-z0-9]*)\s*\^\s*\(\s*([0-9A-Za-z+\-*/ ]{1,12})\s*\)",
            lambda m: f"${m.group(1)}^{{{m.group(2).strip().replace(' ', '')}}}$",
            s2,
        )
        for i, chunk in enumerate(_protected):
            s2 = s2.replace(f"@@MATH{i}@@", chunk)
        s = s2

        # Re-apply tilde ban in case the model emitted it inside math blocks.
        s = s.replace("~", "").replace("～", "")
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
    user_id = get_user_id(request.headers.get("X-User-Id"))
    started_m = time.monotonic()
    now_ts = _now_ts()
    session_data = get_session(session_id)
    log_event(
        logger,
        "chat_request",
        request_id=request_id,
        session_id=session_id,
        user_id=user_id,
        subject=getattr(req.subject, "value", str(req.subject)),
        question_len=len(req.question or ""),
        has_last_event_id=bool(last_event_id),
    )

    # Best-effort: touch Submission last_active_at (180-day inactivity cleanup uses this).
    try:
        touch_submission(user_id=user_id, session_id=session_id)
    except Exception:
        pass

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

        # If the user didn't explicitly switch focus this turn, emit a small log for debugging.
        try:
            if not requested_qn and not _has_explicit_question_switch_intent(req.question):
                log_event(
                    logger,
                    "chat_focus_question_maintained",
                    request_id=request_id,
                    session_id=session_id,
                    focus_question_number=session_data.get("focus_question_number"),
                )
        except Exception:
            pass

        # Optional optimization: if this session likely contains visual/diagram risks, enqueue qindex slices in background.
        # This is best-effort and must never block chat (user should not be aware of it).
        try:
            qindex_now = get_question_index(session_id) if session_id else None
            queued_already = False
            if isinstance(qindex_now, dict):
                ws = qindex_now.get("warnings") or []
                if isinstance(ws, list) and any("queued" in str(w) for w in ws):
                    queued_already = True
                if qindex_now.get("questions"):
                    queued_already = True

            focus_obj_for_qindex = wrong_item_context.get("focus_question")
            focus_qn_for_qindex = wrong_item_context.get("focus_question_number")
            user_visual_hint = False
            try:
                user_visual_hint, _ = analyze_visual_risk(
                    subject=req.subject,
                    question_content=req.question,
                    warnings=None,
                )
            except Exception:
                user_visual_hint = False
            if (
                not queued_already
                and isinstance(focus_obj_for_qindex, dict)
                and (focus_obj_for_qindex.get("visual_risk") is True or user_visual_hint)
            ):
                qbank_now = get_question_bank(session_id) if session_id else None
                if isinstance(qbank_now, dict) and (should_create_slices_for_bank(qbank_now) or user_visual_hint):
                    page_urls = qbank_now.get("page_image_urls")
                    if isinstance(page_urls, list) and page_urls:
                        allow = pick_question_numbers_for_slices(qbank_now)
                        # If user explicitly hints there is a diagram/table/etc, make sure we slice the focused question.
                        if user_visual_hint and focus_qn_for_qindex:
                            fq = str(focus_qn_for_qindex).strip()
                            if fq and fq not in allow:
                                allow = [*allow, fq]
                        if not allow and focus_qn_for_qindex:
                            allow = [str(focus_qn_for_qindex).strip()]

                        ok, reason = qindex_is_configured()
                        if not ok:
                            save_qindex_placeholder(session_id, f"qindex skipped: {reason}")
                        else:
                            if enqueue_qindex_job(
                                session_id,
                                [str(u) for u in page_urls if u],
                                question_numbers=allow,
                            ):
                                save_question_index(session_id, {"questions": {}, "warnings": ["qindex queued (chat)"]})
                                log_event(logger, "chat_qindex_enqueued", request_id=request_id, session_id=session_id)
                            else:
                                save_qindex_placeholder(session_id, "qindex skipped: redis_unavailable")
        except Exception:
            pass

        # ---- Mandatory visual path (product requirement) ----
        # When the user requests "look at the picture"/diagram-related judgement:
        # - Ensure qindex slices exist (enqueue + wait).
        # - Run vision relook on the slice.
        # - If still unavailable, explicitly say we cannot see the diagram (no guessing).
        try:
            focus_obj = wrong_item_context.get("focus_question")
            fqnum = wrong_item_context.get("focus_question_number")
            if isinstance(focus_obj, dict) and fqnum:
                user_visual_hint, _ = analyze_visual_risk(
                    subject=req.subject,
                    question_content=req.question,
                    warnings=None,
                )
                explicit_visual = bool(_user_requests_visual_check(req.question))
                must_visual = bool(explicit_visual or user_visual_hint)

                if must_visual:
                    # 1) Ensure qindex slices (for focused question)
                    qindex_now = get_question_index(session_id) if session_id else None
                    ready = isinstance(qindex_now, dict) and _qindex_has_slices_for_question(qindex_now, str(fqnum))
                    if not ready:
                        # DB fallback: if Redis lost/restarted, still try to load slices within TTL.
                        try:
                            db_refs = load_qindex_image_refs(
                                user_id=user_id,
                                session_id=session_id,
                                question_number=str(fqnum),
                            )
                            if isinstance(db_refs, dict) and db_refs:
                                focus_obj["image_refs"] = db_refs
                                ready = True
                        except Exception:
                            pass

                    if not ready:
                        ok, reason = qindex_is_configured()
                        if not ok:
                            save_qindex_placeholder(session_id, f"qindex skipped: {reason}")
                            reply = (
                                "这题需要看图/切片才能确认关键位置关系，但当前环境未配置可用的切片能力，"
                                f"所以我看不到图（{reason}）。你可以补齐配置后重试，或把该题局部截图发我。"
                            )
                            session_data["history"].append({"role": "user", "content": req.question})
                            session_data["history"].append({"role": "assistant", "content": reply})
                            save_session(session_id, session_data)
                            payload = ChatResponse(messages=[{"role": "assistant", "content": reply}], session_id=session_id, retry_after_ms=None)
                            yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")
                            yield b"event: done\ndata: {\"status\":\"continue\",\"session_id\":\"%b\"}\n\n" % session_id.encode("utf-8")
                            return

                        # Enqueue if not already queued.
                        queued_already = False
                        if isinstance(qindex_now, dict):
                            ws = qindex_now.get("warnings") or []
                            if isinstance(ws, list) and any("queued" in str(w) for w in ws):
                                queued_already = True
                            if qindex_now.get("questions"):
                                queued_already = True

                        qbank_now = get_question_bank(session_id) if session_id else None
                        page_urls = (qbank_now or {}).get("page_image_urls") if isinstance(qbank_now, dict) else None
                        allow = pick_question_numbers_for_slices(qbank_now) if isinstance(qbank_now, dict) else []
                        fq = str(fqnum).strip()
                        if fq and fq not in allow:
                            allow = [*allow, fq] if allow else [fq]

                        if (not queued_already) and isinstance(page_urls, list) and page_urls:
                            if enqueue_qindex_job(session_id, [str(u) for u in page_urls if u], question_numbers=allow):
                                save_question_index(session_id, {"questions": {}, "warnings": ["qindex queued (chat)"]})
                            else:
                                save_qindex_placeholder(session_id, "qindex skipped: redis_unavailable")

                        # Tell user we are reading the picture and wait for slices.
                        wait_s = 120.0
                        poll = 1.0
                        info = f"我正在读取图片并生成切片（第{fq}题），请稍等…"
                        session_data["history"].append({"role": "user", "content": req.question})
                        session_data["history"].append({"role": "assistant", "content": info})
                        save_session(session_id, session_data)
                        payload = ChatResponse(messages=[{"role": "assistant", "content": info}], session_id=session_id, retry_after_ms=1500)
                        yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")

                        deadline = time.monotonic() + wait_s
                        last_beat = time.monotonic()
                        while time.monotonic() < deadline:
                            await asyncio.sleep(poll)
                            qindex_now = get_question_index(session_id) if session_id else None
                            if isinstance(qindex_now, dict) and _qindex_has_slices_for_question(qindex_now, str(fqnum)):
                                ready = True
                                break
                            # Also check DB as a fallback (Redis may have been restarted).
                            if time.monotonic() - last_beat >= 5.0:
                                try:
                                    db_refs = load_qindex_image_refs(
                                        user_id=user_id,
                                        session_id=session_id,
                                        question_number=str(fqnum),
                                    )
                                    if isinstance(db_refs, dict) and db_refs:
                                        focus_obj["image_refs"] = db_refs
                                        ready = True
                                        break
                                except Exception:
                                    pass
                            if time.monotonic() - last_beat >= 5.0:
                                yield b"event: heartbeat\ndata: {}\n\n"
                                last_beat = time.monotonic()

                        if not ready:
                            qindex_now = get_question_index(session_id) if session_id else None
                            ws = (qindex_now or {}).get("warnings") if isinstance(qindex_now, dict) else None
                            ws_txt = f"（{ws[0]}）" if isinstance(ws, list) and ws else ""
                            reply = (
                                "我这边还没成功拿到切片，所以目前看不到图，无法判断图形位置关系。"
                                + ws_txt
                                + "你可以再等一会儿再问，或直接把该题局部截图发我。"
                            )
                            session_data["history"].append({"role": "assistant", "content": reply})
                            save_session(session_id, session_data)
                            payload = ChatResponse(messages=[{"role": "assistant", "content": reply}], session_id=session_id, retry_after_ms=2000)
                            yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")
                            yield b"event: done\ndata: {\"status\":\"continue\",\"session_id\":\"%b\"}\n\n" % session_id.encode("utf-8")
                            return

                    # 2) Refresh image refs into focus_obj for relook
                    qindex_now = get_question_index(session_id) if session_id else None
                    if isinstance(qindex_now, dict):
                        qs = qindex_now.get("questions")
                        if isinstance(qs, dict) and str(fqnum) in qs:
                            focus_obj["image_refs"] = qs.get(str(fqnum))
                        if qindex_now.get("warnings"):
                            wrong_item_context["index_warnings"] = qindex_now.get("warnings")

                    # 3) Force relook when user explicitly asks to "看图"
                    if explicit_visual and (not focus_obj.get("vision_recheck_text") or focus_obj.get("relook_error")):
                        patch = await _relook_focus_question_via_vision(
                            session_id=session_id,
                            subject=req.subject,
                            question_number=str(fqnum),
                            focus_question=focus_obj,
                        )
                        if isinstance(patch, dict) and patch:
                            focus_obj.update({k: v for k, v in patch.items() if v is not None})
                            wrong_item_context["focus_question"] = focus_obj
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

                    # 4) Fail closed if user requested visual check but we still have no relook text.
                    if explicit_visual and not focus_obj.get("vision_recheck_text"):
                        reply = "我目前看不到图/没有拿到足够的图像信息，所以不能判断图形位置关系；请把该题局部截图发我，或稍后再试。"
                        session_data["history"].append({"role": "assistant", "content": reply})
                        save_session(session_id, session_data)
                        payload = ChatResponse(messages=[{"role": "assistant", "content": reply}], session_id=session_id, retry_after_ms=None)
                        yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")
                        yield b"event: done\ndata: {\"status\":\"continue\",\"session_id\":\"%b\"}\n\n" % session_id.encode("utf-8")
                        return
        except Exception:
            pass

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
                    # If we successfully relooked, clear stale error so we can proceed.
                    if patch.get("vision_recheck_text"):
                        try:
                            focus_obj.pop("relook_error", None)
                        except Exception:
                            pass
                    wrong_item_context["focus_question"] = focus_obj
                    # Persist patch back to qbank for subsequent turns (best-effort).
                    try:
                        qbank_now = get_question_bank(session_id)
                        if isinstance(qbank_now, dict):
                            qs = qbank_now.get("questions")
                            if isinstance(qs, dict) and str(fqnum) in qs and isinstance(qs.get(str(fqnum)), dict):
                                qs[str(fqnum)].update({k: v for k, v in patch.items() if v is not None})
                                if patch.get("vision_recheck_text"):
                                    qs[str(fqnum)].pop("relook_error", None)
                                qbank_now["questions"] = qs
                                qbank_now = _merge_bank_meta(qbank_now, {"updated_at": datetime.now().isoformat()})
                                save_question_bank(session_id, qbank_now)
                    except Exception:
                        pass
        except Exception as e:
            # Never crash chat for a best-effort relook, but record a hint so the tutor won't "guess the picture".
            try:
                focus_obj = wrong_item_context.get("focus_question")
                if isinstance(focus_obj, dict) and not focus_obj.get("vision_recheck_text"):
                    focus_obj["relook_error"] = f"重识别失败: {e}"
                    wrong_item_context["focus_question"] = focus_obj
            except Exception:
                pass

        # Guardrail: if the user is asking about diagram/position relations but vision re-look failed,
        # do NOT let the text-only tutor "guess the picture".
        try:
            focus_obj = wrong_item_context.get("focus_question")
            msg = (req.question or "").strip()
            asking_diagram = any(k in msg for k in ("看不到图", "没看到图", "同位角", "内错角", "位置关系", "像F", "像Z", "如图", "看图"))
            if asking_diagram and isinstance(focus_obj, dict):
                qcontent = str(focus_obj.get("question_content") or "")
                likely_needs_image = (focus_obj.get("visual_risk") is True) or ("如图" in qcontent) or ("图" in qcontent)
                has_any_image = bool(_pick_relook_image_url(focus_obj))
                if likely_needs_image and not focus_obj.get("vision_recheck_text") and (not has_any_image or focus_obj.get("relook_error")):
                    # Persist user msg + assistant response for session continuity.
                    session_data["history"].append({"role": "user", "content": req.question})
                    reply = (
                        "这题需要看图才能判断角的位置关系，但我这边目前没有成功拿到该题的图像/切片信息，"
                        "所以不能直接断言它是同位角还是内错角。"
                        "你可以等一会儿让系统生成切片后再问，或直接把第9题（含图）的局部截图发我。"
                    )
                    session_data["history"].append({"role": "assistant", "content": reply})
                    save_session(session_id, session_data)
                    payload = ChatResponse(
                        messages=[{"role": "assistant", "content": reply}],
                        session_id=session_id,
                        retry_after_ms=1500,
                        cross_subject_flag=None,
                    )
                    yield f"event: chat\ndata: {payload.model_dump_json()}\n\n".encode("utf-8")
                    yield b"event: done\ndata: {\"status\":\"continue\",\"session_id\":\"%b\"}\n\n" % session_id.encode("utf-8")
                    return
        except Exception:
            pass

        # ===== True streaming: LLM token stream -> SSE chat events =====
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        DONE = object()

        # Update session immediately with user's message so LLM can see the conversation history.
        # Avoid duplicating the same user message when we already appended it earlier
        # (e.g. during mandatory "读图/切片" prelude).
        already_has_user = False
        try:
            for m in reversed(session_data.get("history") or []):
                if isinstance(m, dict) and m.get("role") == "user":
                    already_has_user = (str(m.get("content") or "") == str(req.question))
                    break
        except Exception:
            already_has_user = False
        if not already_has_user:
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
