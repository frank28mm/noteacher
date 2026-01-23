from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Tuple
import re

from fastapi import APIRouter, HTTPException, status, Request, Header
from fastapi.responses import StreamingResponse

from homework_agent.models.schemas import (
    ChatRequest,
    ChatResponse,
    Subject,
    VisionProvider,
)
from homework_agent.services.llm import LLMClient
from homework_agent.utils.settings import get_settings
from homework_agent.utils.feature_flags import decide as decide_feature_flag
from homework_agent.core.qbank import _normalize_question_number
from homework_agent.core.qindex import qindex_is_configured  # noqa: F401
from homework_agent.api.session import (
    SESSION_TTL_SECONDS,
    get_session,
    save_session,
    delete_session,
    persist_question_bank,
    save_mistakes,
    get_question_bank,
    save_question_bank,
    _merge_bank_meta,
    _now_ts,
    _coerce_ts,
)
from homework_agent.services.qindex_queue import enqueue_qindex_job  # noqa: F401
from homework_agent.utils.observability import get_request_id_from_headers, log_event
from homework_agent.utils.user_context import require_user_id
from homework_agent.utils.errors import build_error_payload, ErrorCode
from homework_agent.services.quota_service import load_wallet
from homework_agent.utils.submission_store import (
    touch_submission,
    link_session_to_submission,
)
from homework_agent.utils.supabase_image_proxy import _create_proxy_image_urls
from homework_agent.utils.supabase_client import get_storage_client

from homework_agent.core.qbank_builder import build_question_bank

from homework_agent.models.vision_facts import GateResult, SceneType, VisualFacts
from homework_agent.services.vision_facts import (
    VFE_CONF_MIN,
    VFE_CONF_GEOMETRY,
    detect_scene_type,
    extract_visual_facts,
    gate_visual_facts,
    select_vfe_images,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _safe_table(name: str):
    storage = get_storage_client()
    return storage.client.table(name)


# 并发保护：防止线程池堆积导致“越跑越慢/无响应”
_settings_for_limits = get_settings()
VISION_SEMAPHORE = asyncio.Semaphore(
    max(1, int(_settings_for_limits.max_concurrent_vision))
)
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


_QNUM_SYMBOL_RE = re.compile(r"[★☆◆◇●•·◎○※▲△]")


def _strip_qnum_symbols(value: Any) -> str:
    return _QNUM_SYMBOL_RE.sub("", str(value or "")).strip()


def _select_question_number_from_text(
    message: str,
    available: List[str],
    question_meta: Optional[Dict[str, Any]] = None,
    *,
    allow_numeric_fallback: bool = True,
) -> Tuple[Optional[str], str]:
    """
    Choose the best matching question_number from user message.
    Strategy (heuristic, deterministic):
    - Prefer the question number that is explicitly being requested (e.g. "聊/讲/说 第28题"),
      and de-prioritize negated mentions (e.g. "不聊25题了，聊28题").
    - If multiple candidates remain, prefer the latest mention in the message.
    - Fallback to common patterns like "第27题/27题/题27".
    """
    if not message or not available:
        return None, "none"
    msg = str(message)
    msg_norm = msg.replace("（", "(").replace("）", ")")
    msg_norm = _strip_qnum_symbols(msg_norm)
    avail = [str(q) for q in (available or []) if q is not None and str(q).strip()]
    if not avail:
        return None, "none"

    # Collect all mentions with positions.
    mentions: List[Dict[str, Any]] = []

    def _is_numeric_question_number(value: Optional[str]) -> bool:
        if not value:
            return False
        s = str(value).strip().replace("（", "(").replace("）", ")")
        s = _strip_qnum_symbols(s)
        s = re.sub(r"\s+", "", s)
        s = re.sub(r"[①②③④⑤⑥⑦⑧⑨]", "", s)
        return re.fullmatch(r"\d+(?:\(\d+\))?", s) is not None

    def _normalize_text(value: str) -> str:
        return str(value or "").strip().replace("（", "(").replace("）", ")")

    def _find_mentions(term: str, numeric: bool) -> List[tuple[int, int]]:
        if not term:
            return []
        if numeric:
            # Stricter check for numeric terms to avoid math expressions
            # e.g. "3" should not match in "3x", "x^3", "3+5", "5-3"

            # Check if term is just digits (simple number case)
            is_simple_number = re.fullmatch(r"\d+", term) is not None

            if is_simple_number:
                # For simple numbers, enforce stricter boundaries:
                # Not preceded/followed by digits, letters, or math operators (+-*/^=)
                # We do NOT include () in exclusion because "20(1)" is valid context for "20",
                # and "Question (3)" is valid for "3".
                exclusion = r"[A-Za-z0-9+\-*/^=]"
                pat = re.compile(rf"(?<!{exclusion}){re.escape(term)}(?!{exclusion})")
                return [(m.start(), m.end()) for m in pat.finditer(msg_norm)]

            # For complex numbers like "20(1)", standard digit boundaries are sufficient
            pat = re.compile(rf"(?<!\d){re.escape(term)}(?!\d)")
            return [(m.start(), m.end()) for m in pat.finditer(msg_norm)]

        # Generic substring scan.
        out: List[tuple[int, int]] = []
        start = 0
        while True:
            idx = msg_norm.find(term, start)
            if idx < 0:
                break
            out.append((idx, idx + len(term)))
            start = idx + max(1, len(term))
        return out

    for q in avail:
        qn = str(q)
        qn_norm = _normalize_text(qn)
        if not qn_norm:
            continue
        q_meta = question_meta.get(qn) if isinstance(question_meta, dict) else None
        aliases: List[str] = [qn]
        if isinstance(q_meta, dict):
            extra = q_meta.get("question_aliases")
            if isinstance(extra, list):
                aliases.extend([str(a) for a in extra if a])

        no_paren = re.sub(r"[（(][^）)]*[)）]", "", qn_norm).strip()
        if no_paren and no_paren not in aliases:
            aliases.append(no_paren)
        stripped_symbol = _strip_qnum_symbols(qn_norm)
        if stripped_symbol and stripped_symbol not in aliases:
            aliases.append(stripped_symbol)
        alias_seen: set[str] = set()
        numeric_qn = _is_numeric_question_number(qn_norm)
        for alias in aliases:
            alias_norm = _normalize_text(alias)
            if not alias_norm or alias_norm in alias_seen:
                continue
            alias_seen.add(alias_norm)
            if numeric_qn and alias_norm != qn_norm and alias_norm != stripped_symbol:
                continue

            for s, e in _find_mentions(alias_norm, numeric=numeric_qn):
                if msg_norm == alias_norm:
                    match_type = "exact"
                elif qn_norm.startswith(alias_norm):
                    match_type = "prefix"
                elif alias_norm != qn_norm and alias_norm != no_paren:
                    match_type = "keyword"
                else:
                    match_type = "contains"
                mentions.append(
                    {
                        "q": qn,
                        "start": s,
                        "end": e,
                        "match_type": match_type,
                        "alias": alias_norm,
                    }
                )

    if not mentions or not allow_numeric_fallback:
        if mentions and not allow_numeric_fallback:
            # Only allow non-numeric matches when numeric fallback is disabled.
            non_numeric = [
                m for m in mentions if not _is_numeric_question_number(m.get("q"))
            ]
            if non_numeric:
                # Prefer exact > prefix > contains > keyword, then latest mention.
                priority = {"exact": 0, "prefix": 1, "contains": 2, "keyword": 3}
                non_numeric.sort(
                    key=lambda m: (
                        priority.get(m["match_type"], 99),
                        -m["start"],
                        -len(m["alias"]),
                    )
                )
                chosen = non_numeric[0]
                return chosen["q"], chosen["match_type"]
            return None, "none"
        if not allow_numeric_fallback:
            return None, "none"

    if not mentions:
        # Fallback: patterns like "第27题/27题/题27/28(1)②"
        pattern = re.compile(
            r"(?:第\\s*)?(\\d{1,3}(?:\\s*\\(\\s*\\d+\\s*\\)\\s*)?(?:[①②③④⑤⑥⑦⑧⑨])?)(?:\\s*题)?"
        )
        found = [(m.group(1), m.start(1), m.end(1)) for m in pattern.finditer(msg_norm)]
        if not found:
            return None, "none"
        # Prefer the latest mention.
        raw, _, _ = sorted(found, key=lambda x: x[1])[-1]
        raw = _normalize_question_number(raw)
        if not raw:
            return None, "none"
        # Map to available keys.
        if raw in avail:
            return raw, "numeric_fallback"
        pref = [q for q in avail if q.startswith(f"{raw}(") or q.startswith(raw)]
        if pref:
            # Prefer the shortest matching key (treat as "whole question" if available).
            return sorted(pref, key=len)[0], "numeric_fallback"
        return None, "none"

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
    best_match_type = "none"
    best_score = -(10**18)
    weights = {"exact": 4000, "prefix": 3000, "contains": 2000, "keyword": 1000}
    for m in mentions:
        q = m["q"]
        s = int(m["start"])
        e = int(m["end"])
        left = msg_norm[max(0, s - 8) : s]
        around = msg_norm[max(0, s - 12) : min(len(msg_norm), e + 12)]
        match_type = m.get("match_type") or "contains"
        alias_len = len(str(m.get("alias") or q))

        score = weights.get(match_type, 0)
        score += alias_len * 100  # specificity
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
            best_match_type = match_type

    return best, best_match_type


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
    msg_num = _strip_qnum_symbols(msg)

    qtoken = r"(\d{1,3}(?:\s*\(\s*\d+\s*\)\s*)?(?:[①②③④⑤⑥⑦⑧⑨])?)"

    # Case 1: user sends a bare question number like "20(2)" / "28(1)②" / "27".
    bare = re.fullmatch(rf"\s*{qtoken}\s*[。．.!！?？]*\s*", msg_num)
    if bare:
        return _normalize_question_number(bare.group(1))

    # Case 1.25: inline sub-question token anywhere (e.g. "我的20(3)哪里有问题？").
    # Safe because it requires a numeric "(n)" pattern, unlikely to appear in algebraic expressions.
    inline_sub = re.search(r"(\d{1,3}\s*\(\s*\d+\s*\)\s*(?:[①②③④⑤⑥⑦⑧⑨])?)", msg_num)
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
        msg_num,
    )
    if m_sub:
        base = _parse_cn_int(m_sub.group(1))
        sub = _parse_cn_int(m_sub.group(2))
        if base and sub:
            return _normalize_question_number(f"{base}({sub})")

    # Case 2: explicit "question" context. Avoid capturing negatives: "-8" should not mean "第8题".
    if re.search(r"(第\s*\d|题\s*\d|\d+\s*题|讲|聊|解释|辅导|说说|再讲|再聊)", msg_num):
        # Prefer forms like "第20题" / "讲20(2)" / "聊第28(1)②题" / "题27".
        m = re.search(rf"第\s*{qtoken}\s*题", msg_num)
        if m:
            return _normalize_question_number(m.group(1))
        # "20题" form (common Chinese input)
        m = re.search(rf"{qtoken}\s*题", msg_num)
        if m:
            return _normalize_question_number(m.group(1))
        m = re.search(rf"(?:题\s*|题号\s*){qtoken}", msg_num)
        if m and not re.search(r"[-+*/^=]\s*$", msg_num[: m.start(1)]):
            return _normalize_question_number(m.group(1))
        m = re.search(
            rf"(?:讲|聊|解释|辅导|说说|再讲|再聊)\s*第?\s*{qtoken}\s*题?", msg_num
        )
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
                # Prefer figure/diagram slices when available (geometry/pattern questions).
                regions = p.get("regions")
                if isinstance(regions, list):
                    for r in regions:
                        if not isinstance(r, dict):
                            continue
                        if (r.get("kind") or "").lower() == "figure" and r.get(
                            "slice_image_url"
                        ):
                            return str(r.get("slice_image_url"))
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


def _qindex_has_slices_for_question(
    qindex: Dict[str, Any], question_number: str
) -> bool:
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
        if isinstance(regions, list) and any(
            isinstance(r, dict) and r.get("slice_image_url") for r in regions
        ):
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
            "形状",
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


def _should_relook_focus_question(
    user_msg: str, focus_question: Dict[str, Any]
) -> bool:
    """Heuristic: decide whether to re-run Vision for a focused question (diagram/pattern issues)."""
    msg = (user_msg or "").strip()
    qcontent = str((focus_question or {}).get("question_content") or "")
    warnings = focus_question.get("warnings") or []
    warnings_s = (
        " ".join([str(w) for w in warnings])
        if isinstance(warnings, list)
        else str(warnings)
    )

    # Avoid repeated re-looks unless the user explicitly challenges recognition again.
    already_relooked = bool((focus_question or {}).get("vision_recheck_text")) or bool(
        (focus_question or {}).get("relook_error")
    )

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
            "看不到图片",
            "你看不到图",
            "你没看到图",
            "你没看图",
            "你有没有看图",
            "图在哪里",
            "看图",
            "如图",
            "见图",
            "你看不到图",
            "看不到图",
            "形状",
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
    ):
        return True

    if already_relooked:
        return False

    # If grade flagged this question as visually risky (or qindex has a figure slice),
    # proactively re-look once on first entry of that question.
    has_figure_slice = False
    try:
        refs = (focus_question or {}).get("image_refs")
        pages = None
        if isinstance(refs, dict):
            pages = refs.get("pages")
        if not isinstance(pages, list):
            pages = (focus_question or {}).get("pages")
        if isinstance(pages, list):
            for p in pages:
                if not isinstance(p, dict):
                    continue
                regions = p.get("regions")
                if isinstance(regions, list) and any(
                    isinstance(r, dict)
                    and (r.get("kind") or "").lower() == "figure"
                    and r.get("slice_image_url")
                    for r in regions
                ):
                    has_figure_slice = True
                    break
    except Exception:
        has_figure_slice = False

    if (focus_question or {}).get("visual_risk") is True or has_figure_slice:
        if _extract_requested_question_number(
            msg
        ) or _has_explicit_question_switch_intent(msg):
            return True

    # Pattern/diagram questions often need the visual example; if missing, relook.
    if "可能误读规律" in warnings_s or "可能误读公式" in warnings_s:
        if (
            ("→" not in qcontent)
            and ("顺序" not in qcontent)
            and ("规律" in qcontent or "出现" in qcontent)
        ):
            return True

    # Very short stems are suspicious for multi-part questions.
    if len(qcontent) < 18 and any(
        k in qcontent for k in ("出现", "规律", "图", "示意")
    ):
        return True

    # Geometry/diagram disputes: if the user argues about angle/position relations, relook once.
    if any(
        k in msg
        for k in (
            "同位角",
            "内错角",
            "位置关系",
            "像F",
            "像Z",
            "左侧",
            "右侧",
            "上方",
            "下方",
        )
    ):
        if ("图" in qcontent) or ((focus_question or {}).get("visual_risk") is True):
            return True

    return False


async def _relook_focus_question_via_vision(
    *,
    session_id: str,
    subject: Subject,
    question_number: str,
    focus_question: Dict[str, Any],
    user_text: str,
    request_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Best-effort: run Vision Fact Extraction (VFE) on the best available slice for the focus question.
    Returns a dict that can be merged into focus_question, or None if relook failed.
    """
    settings = get_settings()
    sel = select_vfe_images(focus_question=focus_question)
    if not sel.image_urls:
        return None

    prefer_ark = bool(settings.ark_api_key and settings.ark_base_url)
    provider = VisionProvider.DOUBAO if prefer_ark else VisionProvider.QWEN3
    qcontent = str((focus_question or {}).get("question_content") or "")
    visual_risk = bool((focus_question or {}).get("visual_risk") is True)
    has_figure = bool(sel.image_source == "slice_figure")
    image_urls = list(sel.image_urls)
    image_source = sel.image_source

    # For large page images, proactively generate a lightweight proxy to reduce VFE timeouts.
    if image_source == "page":
        proxy_urls = _create_proxy_image_urls(
            image_urls, session_id=session_id, prefix="vfe_proxy/"
        )
        if proxy_urls:
            image_urls = proxy_urls
            image_source = "page_proxy"
    scene_type = detect_scene_type(
        subject=subject,
        user_text=user_text,
        question_content=qcontent,
        visual_risk=visual_risk,
        has_figure_slice=has_figure,
    )

    budget = min(60.0, float(settings.grade_vision_timeout_seconds))
    if request_id:
        log_event(
            logger,
            "vfe_start",
            level="warning",
            request_id=request_id,
            session_id=session_id,
            focus_qn=str(question_number),
            scene_type=scene_type.value,
            image_source=image_source,
            image_url=image_urls[0],
            budget_s=int(budget),
        )
    try:
        facts, repaired_json, raw = await _call_blocking_in_thread(
            extract_visual_facts,
            image_urls=image_urls,
            scene_type=scene_type,
            provider=provider,
            timeout_seconds=budget,
            semaphore=VISION_SEMAPHORE,
        )
    except asyncio.TimeoutError:
        # Retry once with proxy-sized images (helps provider-side timeouts on large slices).
        if image_source != "page_proxy":
            proxy_urls = _create_proxy_image_urls(
                image_urls, session_id=session_id, prefix="vfe_proxy/"
            )
            if proxy_urls:
                retry_budget = min(40.0, budget)
                try:
                    facts, repaired_json, raw = await _call_blocking_in_thread(
                        extract_visual_facts,
                        image_urls=proxy_urls,
                        scene_type=scene_type,
                        provider=provider,
                        timeout_seconds=retry_budget,
                        semaphore=VISION_SEMAPHORE,
                    )
                    image_urls = proxy_urls
                    image_source = f"{image_source}_proxy"
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    pass
        if "facts" in locals():
            # Retry succeeded, continue with gating below.
            pass
        else:
            gate = GateResult(
                passed=False,
                trigger="vision_timeout",
                critical_unknowns_hit=[],
                user_facing_message=f"我这边看图超时了（{int(budget)}s），暂时无法确认图形位置关系。",
                repaired_json=False,
            )
            if request_id:
                log_event(
                    logger,
                    "vfe_gate",
                    level="warning",
                    request_id=request_id,
                    session_id=session_id,
                    focus_qn=str(question_number),
                    scene_type=scene_type.value,
                    trigger=gate.trigger,
                    image_source=image_source,
                    critical_unknowns_hit=[],
                )
            return {
                "relook_error": f"VFE fail-closed: {gate.trigger}",
                "vfe_gate": gate.model_dump(),
            }
    except Exception as e:
        gate = GateResult(
            passed=False,
            trigger="vision_api_failed",
            critical_unknowns_hit=[],
            user_facing_message="视觉服务暂时不可用，我目前无法确认图形位置关系；请稍后重试或发更清晰的局部截图。",
            repaired_json=False,
        )
        if request_id:
            log_event(
                logger,
                "vfe_gate",
                request_id=request_id,
                session_id=session_id,
                focus_qn=str(question_number),
                scene_type=scene_type.value,
                trigger=gate.trigger,
                image_source=image_source,
                critical_unknowns_hit=[],
                error_type=e.__class__.__name__,
                error=str(e),
                level="warning",
            )
        return {
            "relook_error": f"VFE fail-closed: {gate.trigger}",
            "vfe_gate": gate.model_dump(),
        }

    if not isinstance(facts, VisualFacts):
        gate = GateResult(
            passed=False,
            trigger="parse_failure",
            critical_unknowns_hit=[],
            user_facing_message="我没能从图片里稳定提取到结构化事实，因此不能可靠判断图形位置关系；请发更清晰的局部截图或稍后重试。",
            repaired_json=bool(repaired_json),
        )
        if request_id:
            log_event(
                logger,
                "vfe_gate",
                request_id=request_id,
                session_id=session_id,
                focus_qn=str(question_number),
                scene_type=scene_type.value,
                trigger=gate.trigger,
                image_source=sel.image_source,
                critical_unknowns_hit=[],
                repaired_json=bool(repaired_json),
                level="warning",
            )
        return {
            "relook_error": f"VFE fail-closed: {gate.trigger}",
            "vfe_gate": gate.model_dump(),
        }

    gate = gate_visual_facts(
        facts=facts,
        scene_type=scene_type,
        visual_risk=visual_risk,
        user_text=user_text,
        image_source=sel.image_source,
        repaired_json=bool(repaired_json),
    )

    if request_id:
        log_event(
            logger,
            "vfe_done",
            level="warning",
            request_id=request_id,
            session_id=session_id,
            focus_qn=str(question_number),
            scene_type=scene_type.value,
            confidence=float(getattr(facts, "confidence", 0.0) or 0.0),
            unknowns_count=len(getattr(facts, "unknowns", []) or []),
            warnings_count=len(getattr(facts, "warnings", []) or []),
            repaired_json=bool(repaired_json),
            image_source=image_source,
        )
        if not gate.passed:
            log_event(
                logger,
                "vfe_gate",
                request_id=request_id,
                session_id=session_id,
                focus_qn=str(question_number),
                scene_type=scene_type.value,
                trigger=gate.trigger,
                image_source=image_source,
                critical_unknowns_hit=gate.critical_unknowns_hit,
                repaired_json=bool(repaired_json),
                level="warning",
            )

    payload: Dict[str, Any] = {
        "visual_facts": facts.model_dump(),
        "vfe_gate": gate.model_dump(),
        "vfe_scene_type": scene_type.value,
        "vfe_image_source": image_source,
        "vfe_image_urls": image_urls[:2],
    }

    # Keep backward-compatible "vision_recheck_text" only when facts are usable.
    if gate.passed:
        preview_lines: List[str] = []
        try:
            bundle = facts.facts
            for line in (bundle.lines or [])[:6]:
                parts = [
                    getattr(line, "name", None),
                    getattr(line, "direction", None),
                    getattr(line, "relative", None),
                ]
                preview_lines.append("- " + " ".join([str(p) for p in parts if p]))
            for ang in (bundle.angles or [])[:6]:
                parts = [
                    getattr(ang, "name", None),
                    (
                        f"at {getattr(ang, 'at', None)}"
                        if getattr(ang, "at", None)
                        else None
                    ),
                    (
                        f"between {','.join(getattr(ang, 'between', None) or [])}"
                        if getattr(ang, "between", None)
                        else None
                    ),
                    f"side={getattr(ang, 'transversal_side', None)}",
                    f"between_lines={getattr(ang, 'between_lines', None)}",
                ]
                preview_lines.append("- " + " ".join([str(p) for p in parts if p]))
        except Exception:
            preview_lines = []
        if not preview_lines and raw:
            preview_lines = [raw[:800]]
        payload["vision_recheck_text"] = "\n".join(preview_lines)[:2200]
    else:
        payload["relook_error"] = f"VFE fail-closed: {gate.trigger}"

    # If confidence is borderline, keep a hint in warnings for transparency.
    conf_threshold = (
        VFE_CONF_GEOMETRY
        if scene_type in (SceneType.MATH_GEOMETRY_2D, SceneType.MATH_GEOMETRY_3D)
        else VFE_CONF_MIN
    )
    if float(getattr(facts, "confidence", 0.0) or 0.0) < float(conf_threshold):
        ws = (
            focus_question.get("warnings")
            if isinstance(focus_question.get("warnings"), list)
            else []
        )
        payload["warnings"] = list(dict.fromkeys((ws or []) + ["VFE: low confidence"]))

    return payload


def _format_math_for_display(text: str) -> str:
    """
    Make math in assistant messages more readable in demo UI:
    - Normalize LaTeX delimiters to $ and $$ for KaTeX rendering
    - Auto-wrap bare LaTeX expressions (e.g., a^{12} -> $a^{12}$)
    - Strip markdown artifacts
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

        # Normalize LaTeX delimiters for KaTeX:
        # IMPORTANT: Only replace actual delimiters, not LaTeX commands like \left[ \right
        # Replace \\[ ... \\] first (double backslash = display math delimiter)
        s = s.replace("\\[", "$$").replace("\\]", "$$")
        # Then replace \( ... \) (single backslash = inline math delimiter)
        s = s.replace("\\(", "$").replace("\\)", "$")

        # Auto-wrap bare LaTeX math expressions that aren't already wrapped
        # This catches patterns like a^{12}, \frac{1}{2}, \sqrt{x}, etc.
        # Pattern: backslash followed by LaTeX command OR {}/[]/^_
        # But only if not already between $ signs
        def wrap_bare_latex(match):
            content = match.group(0)
            # Don't wrap if already has $ delimiters nearby
            if "$" in content:
                return content
            # Wrap in $ delimiters
            return f"${content}$"

        # Pattern 1: Things like \frac{...}{...}, \sqrt[...]{...}, \sum, \int, etc.
        # Pattern 2: Things followed by ^{...} or _{...}
        # Pattern 3: Things like a^{b}, x_{n}, etc.
        latex_patterns = [
            r"\\[a-zA-Z]+\{[^}]*\}(?:\{[^}]*\})?",  # \frac{a}{b}, \sqrt{a}
            r"\\[a-zA-Z]+",  # \alpha, \beta, \sum, \int (without args)
            r"[a-zA-Z0-9]+\^\{[^}]+\}",  # a^{12}, x^2
            r"[a-zA-Z0-9]+_\{[^}]+\}",  # x_{n}, a_{i}
            r"\\\{[^}]+\\\}",  # \{ ... \} for grouping
            r"\\[a-zA-Z]+\[[^\]]*\](?:\{[^}]*\})?",  # \sqrt[n]{x}
        ]

        # Apply patterns, but be careful not to wrap things that are already wrapped
        # First, mark existing $...$ sections to avoid double-wrapping
        placeholder_marker = "__MATH_BLOCK__"
        math_blocks = []

        def preserve_math(match):
            math_blocks.append(match.group(0))
            return f"{placeholder_marker}{len(math_blocks) - 1}__"

        # Temporarily replace existing math blocks
        s = re.sub(r"\$\$[^$]+\$\$|\$[^$]+\$", preserve_math, s)

        # Now apply auto-wrapping to remaining text
        for pattern in latex_patterns:
            s = re.sub(pattern, wrap_bare_latex, s)

        # Restore preserved math blocks
        for i, block in enumerate(math_blocks):
            s = s.replace(f"{placeholder_marker}{i}__", block)

        # Clean up boldsymbol wrappers
        s = re.sub(r"\\boldsymbol\{([^{}]+)\}", r"\1", s)

        # Re-apply tilde ban in case the model emitted it inside math blocks.
        s = s.replace("~", "").replace("～", "")
    except Exception as e:
        logger.debug(f"_format_math_for_display failed: {e}")
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
            "question_number": item.get("question_number")
            or item.get("question_index")
            or item.get("id"),
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
                    for k in [
                        "index",
                        "verdict",
                        "expected",
                        "observed",
                        "hint",
                        "severity",
                    ]
                    if k in first_bad
                }
        geom = item.get("geometry_check")
        if geom:
            ci["geometry_check"] = geom
        compacted.append(ci)
    return compacted


def assistant_tail(
    history: List[Dict[str, Any]], max_messages: int = 3
) -> List[Dict[str, Any]]:
    """Return last N assistant messages in chronological order for replay."""
    assistants = [m for m in history if m.get("role") == "assistant"]
    if not assistants:
        return []
    tail = assistants[-max_messages:]
    return tail


def _init_chat_request(
    *,
    req: ChatRequest,
    headers: Any,
    last_event_id: Optional[str],
    request_id_override: Optional[str] = None,
) -> tuple[str, str, str, float, float, Optional[Dict[str, Any]]]:
    """
    Initialize per-request identifiers and load session data (best-effort).
    Returns: (session_id, request_id, user_id, started_m, now_ts, session_data)
    """
    # Session restore or create; last_event_id is only used to recover session_id.
    session_id = req.session_id or last_event_id or f"session_{uuid.uuid4().hex[:8]}"
    request_id = (
        str(request_id_override).strip() if request_id_override else None
    ) or get_request_id_from_headers(headers)
    if not request_id:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
    user_id = require_user_id(
        authorization=(
            headers.get("Authorization") if hasattr(headers, "get") else None
        ),
        x_user_id=(headers.get("X-User-Id") if hasattr(headers, "get") else None),
    )
    started_m = time.monotonic()
    now_ts = _now_ts()
    session_data = get_session(session_id)
    return session_id, request_id, user_id, started_m, now_ts, session_data


def _format_session_history_for_display(session_data: Dict[str, Any]) -> None:
    """Best-effort: normalize past assistant messages for UI display."""
    # Get question-specific history if focus_question_number is set
    focus_q = session_data.get("focus_question_number")
    if focus_q:
        from homework_agent.api.session import get_question_history

        q_hist = get_question_history(session_data, focus_q)
        if q_hist:
            hist = q_hist
        else:
            hist = session_data.get("history") or []
    else:
        hist = session_data.get("history") or []

    if isinstance(hist, list):
        for m in hist:
            if (
                isinstance(m, dict)
                and m.get("role") == "assistant"
                and isinstance(m.get("content"), str)
            ):
                m["content"] = _format_math_for_display(m.get("content") or "")
        session_data["history"] = hist


class _ChatAbort(Exception):
    """Internal control-flow: terminate chat_stream with pre-built SSE chunks."""

    def __init__(self, *, chunks: List[bytes]):
        super().__init__("chat aborted")
        self.chunks = chunks


def _sse_event(event: str, data: str, event_id: Optional[str] = None) -> bytes:
    parts = [f"event: {event}", f"data: {data}"]
    if event_id:
        parts.append(f"id: {event_id}")
    return ("\n".join(parts) + "\n\n").encode("utf-8")


def _abort_with_error_event(code: str, message: str) -> None:
    """Abort with SSE error + done events (used for session lifecycle failures)."""
    raise _ChatAbort(
        chunks=[
            _sse_event("error", json.dumps({"code": code, "message": message})),
            _sse_event("done", json.dumps({"status": "error"})),
        ]
    )


def _abort_with_assistant_message(
    *,
    session_id: str,
    session_data: Dict[str, Any],
    message: str,
    done_status: str,
    retry_after_ms: Optional[int] = None,
    question_candidates: Optional[List[str]] = None,
) -> None:
    session_data["history"].append({"role": "assistant", "content": message})
    try:
        from homework_agent.security.safety import sanitize_session_data_for_persistence

        sanitize_session_data_for_persistence(session_data)
    except Exception as e:
        logger.debug(f"Sanitizing session for persistence failed (best-effort): {e}")
    save_session(session_id, session_data)
    payload = ChatResponse(
        messages=[{"role": "assistant", "content": message}],
        session_id=session_id,
        retry_after_ms=retry_after_ms,
        cross_subject_flag=None,
        question_candidates=question_candidates,
    )
    chunks = [
        _sse_event("chat", payload.model_dump_json(), event_id=session_id),
        _sse_event(
            "done",
            json.dumps({"status": done_status, "session_id": session_id}),
            event_id=session_id,
        ),
    ]
    raise _ChatAbort(chunks=chunks)


def _abort_with_user_and_assistant_message(
    *,
    session_id: str,
    session_data: Dict[str, Any],
    user_message: str,
    assistant_message: str,
    done_status: str,
    retry_after_ms: Optional[int] = None,
    question_candidates: Optional[List[str]] = None,
) -> None:
    session_data["history"].append({"role": "user", "content": user_message})
    session_data["history"].append({"role": "assistant", "content": assistant_message})
    try:
        from homework_agent.security.safety import sanitize_session_data_for_persistence

        sanitize_session_data_for_persistence(session_data)
    except Exception as e:
        logger.debug(f"Sanitizing session for persistence failed (best-effort): {e}")
    save_session(session_id, session_data)
    payload = ChatResponse(
        messages=[{"role": "assistant", "content": assistant_message}],
        session_id=session_id,
        retry_after_ms=retry_after_ms,
        cross_subject_flag=None,
        question_candidates=question_candidates,
    )
    chunks = [
        _sse_event("chat", payload.model_dump_json(), event_id=session_id),
        _sse_event(
            "done",
            json.dumps({"status": done_status, "session_id": session_id}),
            event_id=session_id,
        ),
    ]
    raise _ChatAbort(chunks=chunks)


def _touch_submission_best_effort(*, user_id: str, session_id: str) -> None:
    try:
        touch_submission(user_id=user_id, session_id=session_id)
    except Exception as e:
        logger.debug(f"touch_submission failed (best-effort): {e}")


def _load_submission_snapshot_for_chat(
    *, user_id: str, submission_id: str
) -> Optional[Dict[str, Any]]:
    """
    Load a durable submission snapshot for chat rehydrate.
    Returns None if not found.
    """
    uid = (user_id or "").strip()
    sid = (submission_id or "").strip()
    if not uid or not sid:
        return None
    try:
        resp = (
            _safe_table("submissions")
            .select(
                "submission_id,user_id,subject,created_at,session_id,page_image_urls,grade_result,vision_raw_text,warnings"
            )
            .eq("user_id", str(uid))
            .eq("submission_id", str(sid))
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None)
        row = (
            rows[0]
            if isinstance(rows, list) and rows and isinstance(rows[0], dict)
            else None
        )
        return row if isinstance(row, dict) else None
    except Exception:
        return None


def _rehydrate_session_from_submission_or_abort(
    *,
    req: ChatRequest,
    request_id: str,
    user_id: str,
    submission_id: str,
    now_ts: float,
) -> tuple[str, Dict[str, Any]]:
    """
    Create a new session_id and seed minimal session/qbank/mistakes from durable submission facts.
    Returns (new_session_id, new_session_data). Aborts the SSE stream on deterministic failures.
    """
    row = _load_submission_snapshot_for_chat(
        user_id=user_id, submission_id=submission_id
    )
    if not isinstance(row, dict):
        _abort_with_error_event("SUBMISSION_NOT_FOUND", "submission not found")

    subj = str(row.get("subject") or "").strip().lower()
    req_subj = getattr(req.subject, "value", str(req.subject)).strip().lower()
    if subj and req_subj and subj != req_subj:
        _abort_with_error_event("SUBJECT_MISMATCH", "subject mismatch for submission")

    grade_result = (
        row.get("grade_result") if isinstance(row.get("grade_result"), dict) else {}
    )
    questions = grade_result.get("questions")
    if not isinstance(questions, list) or not questions:
        _abort_with_error_event(
            "SUBMISSION_NOT_GRADED", "submission has no grade_result.questions"
        )

    page_image_urls = (
        row.get("page_image_urls")
        if isinstance(row.get("page_image_urls"), list)
        else []
    )
    page_image_urls = [str(u).strip() for u in page_image_urls if str(u).strip()]
    vision_raw_text = str(row.get("vision_raw_text") or "")

    new_session_id = f"session_{uuid.uuid4().hex[:8]}"

    # Seed qbank from durable facts (OCR text + structured questions).
    bank = build_question_bank(
        session_id=new_session_id,
        subject=req.subject,
        questions=[q for q in questions if isinstance(q, dict)],
        vision_raw_text=vision_raw_text,
        page_image_urls=page_image_urls,
        visual_facts_map=None,
    )

    warnings = (
        grade_result.get("warnings")
        if isinstance(grade_result.get("warnings"), list)
        else []
    )
    grade_summary = str(grade_result.get("summary") or "").strip()
    persist_question_bank(
        session_id=new_session_id,
        bank=_merge_bank_meta(
            bank, {"rehydrated_from_submission_id": str(submission_id)}
        ),
        grade_status="done",
        grade_summary=grade_summary,
        grade_warnings=[str(w) for w in warnings if str(w).strip()],
        request_id=request_id,
        timings_ms=None,
    )

    # Seed mistakes for context_item_ids routing (optional; but required for "Ask Teacher" deep links).
    wrong_items = grade_result.get("wrong_items")
    if isinstance(wrong_items, list) and wrong_items:
        save_mistakes(new_session_id, [w for w in wrong_items if isinstance(w, dict)])

    # Seed session. Keep it minimal and deterministic.
    session_data: Dict[str, Any] = {
        "history": req.history or [],
        "interaction_count": 0,
        "created_at": now_ts,
        "updated_at": now_ts,
        "context_item_ids": normalize_context_ids(req.context_item_ids or []),
        "submission_id": str(submission_id),
    }
    try:
        from homework_agent.security.safety import sanitize_session_data_for_persistence

        sanitize_session_data_for_persistence(session_data)
    except Exception as e:
        logger.debug(f"Sanitizing rehydrated session failed (best-effort): {e}")
    save_session(new_session_id, session_data)

    # Best-effort link for observability + future slice lookups.
    try:
        link_session_to_submission(
            user_id=str(user_id),
            submission_id=str(submission_id),
            session_id=str(new_session_id),
            subject=req_subj or None,
        )
    except Exception:
        pass

    return new_session_id, session_data


def _ensure_chat_session_or_abort(
    *,
    req: ChatRequest,
    session_id: str,
    session_data: Optional[Dict[str, Any]],
    now_ts: float,
    last_event_id: Optional[str],
) -> Dict[str, Any]:
    """Ensure session exists and is within TTL; otherwise abort with deterministic SSE error."""
    if session_data:
        updated_ts = _coerce_ts(session_data.get("updated_at")) or now_ts
        if now_ts - updated_ts > SESSION_TTL_SECONDS:
            delete_session(session_id)
            _abort_with_error_event("SESSION_EXPIRED", "session expired")

    if not session_data:
        if last_event_id and not req.session_id:
            _abort_with_error_event("SESSION_NOT_FOUND", "session not found")

        session_data = {
            "history": req.history or [],
            "interaction_count": 0,
            "created_at": now_ts,
            "updated_at": now_ts,
            "context_item_ids": normalize_context_ids(req.context_item_ids or []),
        }
        try:
            from homework_agent.security.safety import (
                sanitize_session_data_for_persistence,
            )

            sanitize_session_data_for_persistence(session_data)
        except Exception as e:
            logger.debug(
                f"Sanitizing new session for persistence failed (best-effort): {e}"
            )
        save_session(session_id, session_data)

    return session_data


def _emit_initial_events(
    *,
    req: "ChatRequest",
    session_id: str,
    session_data: Dict[str, Any],
    last_event_id: Optional[str],
    has_explicit_session_id: bool,
) -> List[bytes]:
    """Return initial SSE events: heartbeat + optional replay messages."""
    try:
        _format_session_history_for_display(session_data)
    except Exception as e:
        logger.debug(f"History formatting failed (best-effort): {e}")

    chunks: List[bytes] = [
        _sse_event(
            "heartbeat",
            json.dumps(
                {
                    "timestamp": datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    # Clients may use this to persist the (possibly rehydrated) session_id immediately.
                    "session_id": session_id,
                },
                ensure_ascii=False,
            ),
            event_id=session_id,
        )
    ]

    # Try to extract focus question number from context_item_ids BEFORE _prepare_chat_context_or_abort updates it
    # This ensures we get the correct question history when switching questions
    focus_q = None
    if req.context_item_ids:
        from homework_agent.api._chat_stages import (
            _try_extract_qn_from_context_id,
            _normalize_context_ids,
        )

        context_ids = _normalize_context_ids(req.context_item_ids or [])
        for cid in context_ids:
            if isinstance(cid, str):
                qn = _try_extract_qn_from_context_id(cid)
                if qn:
                    focus_q = qn
                    break

    # Fall back to session_data focus_question_number if not found in context_item_ids
    if not focus_q:
        focus_q = session_data.get("focus_question_number")

    logger.debug(
        f"[DEBUG _emit_initial_events] session_id={session_id}, focus_q={focus_q}, question_histories keys={list((session_data.get('question_histories') or {}).keys())}"
    )

    question_history = None
    if focus_q:
        from homework_agent.api.session import get_question_history

        question_history = get_question_history(session_data, focus_q)
        logger.debug(
            f"[DEBUG _emit_initial_events] question_history for focus_q={focus_q}: {len(question_history) if question_history else 0} messages"
        )

    # Use question-specific history if available, otherwise fall back to global history
    history_to_send = (
        question_history if question_history else (session_data.get("history") or [])
    )

    # Send full history in a single chat event (not one message per event)
    # This ensures chat history persists when re-entering a question
    if history_to_send:
        logger.debug(
            f"[DEBUG _emit_initial_events] Sending {len(history_to_send)} messages to client"
        )
        payload = ChatResponse(
            messages=history_to_send,
            session_id=session_id,
            retry_after_ms=None,
            cross_subject_flag=None,
        )
        chunks.append(
            _sse_event("chat", payload.model_dump_json(), event_id=session_id)
        )

    return chunks


def _select_chat_model_or_raise(req: ChatRequest) -> tuple[str, Optional[str]]:
    """Validate optional model override and return (provider_str, model_override)."""
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
    return provider_str, model_override


async def _run_mandatory_visual_path(
    *,
    req: ChatRequest,
    session_id: str,
    request_id: str,
    user_id: str,
    session_data: Dict[str, Any],
    wrong_item_context: Dict[str, Any],
) -> AsyncIterator[bytes]:
    from homework_agent.api._chat_stages import _run_mandatory_visual_path as _impl

    async for chunk in _impl(
        req=req,
        session_id=session_id,
        request_id=request_id,
        user_id=user_id,
        session_data=session_data,
        wrong_item_context=wrong_item_context,
    ):
        yield chunk


def _apply_user_corrections(
    *,
    session_data: Dict[str, Any],
    wrong_item_context: Dict[str, Any],
    user_message: str,
) -> None:
    focus_q_for_corr = wrong_item_context.get(
        "focus_question_number"
    ) or session_data.get("focus_question_number")
    corr = _extract_user_correction(user_message)
    if not (focus_q_for_corr and corr):
        return
    fq = str(focus_q_for_corr)
    corr_map = session_data.setdefault("corrections", {})
    corr_list = corr_map.setdefault(fq, [])
    if not corr_list or corr_list[-1] != corr:
        corr_list.append(corr)
    corr_map[fq] = corr_list[-5:]
    wrong_item_context["user_corrections"] = corr_map[fq]
    if isinstance(wrong_item_context.get("focus_question"), dict):
        wrong_item_context["focus_question"]["user_corrections"] = corr_map[fq]


async def _best_effort_relook_if_needed(
    *,
    req: ChatRequest,
    session_id: str,
    request_id: str,
    wrong_item_context: Dict[str, Any],
) -> None:
    """Best-effort: re-look focused question when user challenges recognition."""
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
                user_text=req.question,
                request_id=request_id,
            )
            if isinstance(patch, dict) and patch:
                # Mark that VFE/relook was attempted in this turn (used for fail-closed gating).
                if any(
                    k in patch
                    for k in (
                        "vfe_gate",
                        "visual_facts",
                        "relook_error",
                        "vision_recheck_text",
                    )
                ):
                    wrong_item_context["_vfe_attempted_this_turn"] = True
                log_event(
                    logger,
                    "chat_relook_applied",
                    request_id=request_id,
                    session_id=session_id,
                    focus_qn=str(fqnum),
                    patch_keys=list(patch.keys()),
                )
                focus_obj.update({k: v for k, v in patch.items() if v is not None})
                if patch.get("vision_recheck_text"):
                    try:
                        focus_obj.pop("relook_error", None)
                    except Exception as e:
                        logger.debug(f"Clearing relook_error failed: {e}")
                wrong_item_context["focus_question"] = focus_obj
                # Persist patch back to qbank for subsequent turns (best-effort).
                try:
                    qbank_now = get_question_bank(session_id)
                    if isinstance(qbank_now, dict):
                        qs = qbank_now.get("questions")
                        if (
                            isinstance(qs, dict)
                            and str(fqnum) in qs
                            and isinstance(qs.get(str(fqnum)), dict)
                        ):
                            qs[str(fqnum)].update(
                                {k: v for k, v in patch.items() if v is not None}
                            )
                            if patch.get("vision_recheck_text"):
                                qs[str(fqnum)].pop("relook_error", None)
                            qbank_now["questions"] = qs
                            qbank_now = _merge_bank_meta(
                                qbank_now, {"updated_at": datetime.now().isoformat()}
                            )
                            save_question_bank(session_id, qbank_now)
                except Exception as e:
                    logger.debug(f"Persisting relook patch to qbank failed: {e}")
    except Exception as e:
        # Never crash chat for a best-effort relook, but record a hint so the tutor won't "guess the picture".
        try:
            focus_obj = wrong_item_context.get("focus_question")
            if isinstance(focus_obj, dict) and not focus_obj.get("vision_recheck_text"):
                focus_obj["relook_error"] = f"重识别失败: {e}"
                wrong_item_context["focus_question"] = focus_obj
        except Exception as e2:
            logger.debug(f"Recording relook_error failed: {e2}")


def _fail_closed_if_vfe_failed_this_turn(
    *,
    req: ChatRequest,
    session_id: str,
    session_data: Dict[str, Any],
    wrong_item_context: Dict[str, Any],
) -> None:
    """
    P0: If this turn attempted VFE and it failed for a visually risky question,
    do NOT proceed to LLM (avoid "贴图但乱讲"). Return the gate's user-facing message.
    """
    if not wrong_item_context.get("_vfe_attempted_this_turn"):
        return
    focus_obj = wrong_item_context.get("focus_question")
    if not isinstance(focus_obj, dict):
        return
    if focus_obj.get("visual_risk") is not True:
        return
    gate = focus_obj.get("vfe_gate")
    if not (isinstance(gate, dict) and gate.get("passed") is False):
        return
    msg = str(gate.get("user_facing_message") or "").strip()
    if not msg:
        msg = "这题需要先稳定看清图形信息，但我本轮没有成功从图片里提取到可靠事实；请稍后再试或发更清晰的局部截图。"
    _abort_with_user_and_assistant_message(
        session_id=session_id,
        session_data=session_data,
        user_message=req.question,
        assistant_message=msg,
        done_status="continue",
        retry_after_ms=1500,
    )


def _diagram_guardrail_abort_if_needed(
    *,
    req: ChatRequest,
    session_id: str,
    session_data: Dict[str, Any],
    wrong_item_context: Dict[str, Any],
) -> None:
    """Guardrail: prevent text-only hallucination for diagram disputes."""
    focus_obj = wrong_item_context.get("focus_question")
    msg = (req.question or "").strip()
    asking_diagram = any(
        k in msg
        for k in (
            "看不到图",
            "没看到图",
            "同位角",
            "内错角",
            "位置关系",
            "像F",
            "像Z",
            "如图",
            "看图",
        )
    )
    if not (asking_diagram and isinstance(focus_obj, dict)):
        return
    qcontent = str(focus_obj.get("question_content") or "")
    likely_needs_image = (
        (focus_obj.get("visual_risk") is True)
        or ("如图" in qcontent)
        or ("图" in qcontent)
    )
    has_any_image = bool(_pick_relook_image_url(focus_obj))
    if (
        likely_needs_image
        and not focus_obj.get("vision_recheck_text")
        and (not has_any_image or focus_obj.get("relook_error"))
    ):
        _abort_with_user_and_assistant_message(
            session_id=session_id,
            session_data=session_data,
            user_message=req.question,
            assistant_message=(
                "这题需要看图才能判断角的位置关系，但我这边目前没有成功拿到该题的图像/切片信息，"
                "所以不能直接断言它是同位角还是内错角。"
                "你可以等一会儿让系统生成切片后再问，或直接把第9题（含图）的局部截图发我。"
            ),
            done_status="continue",
            retry_after_ms=1500,
        )


def _prompt_injection_guardrail_abort_if_needed(
    *,
    req: ChatRequest,
    session_id: str,
    session_data: Dict[str, Any],
    request_id: str,
) -> None:
    """
    Guardrail: block obvious prompt injection attempts before any LLM call.
    This is a hard rule (HITL): do not proceed, return a safe response.
    """
    try:
        from homework_agent.security.safety import scan_safety

        scan = scan_safety(req.question or "")
        if "prompt_injection" not in (scan.warning_codes or []):
            return
        log_event(
            logger,
            "chat_input_blocked",
            level="warning",
            request_id=request_id,
            session_id=session_id,
            needs_review=True,
            warning_codes=scan.warning_codes,
        )
        try:
            from homework_agent.services.review_queue import enqueue_review_item

            enqueue_review_item(
                request_id=request_id,
                session_id=session_id,
                subject=(
                    str(getattr(req.subject, "value", req.subject))
                    if getattr(req, "subject", None) is not None
                    else None
                ),
                warning_codes=list(scan.warning_codes or []),
                evidence_urls=[],
                run_versions={
                    "prompt_id": "chat",
                    "prompt_version": "socratic",
                    "provider": "n/a",
                    "model": "n/a",
                },
                note="chat_prompt_injection_blocked",
            )
        except Exception:
            pass
        msg = (
            "我检测到你的输入包含可能的提示注入/越权指令（例如“忽略系统指令/泄露 system prompt”等）。\n"
            "为保证安全，我不会执行这些指令。\n"
            "如果你需要作业讲解，请只描述具体题目与困惑点（不要包含让模型忽略规则的要求）。"
        )
        _abort_with_user_and_assistant_message(
            session_id=session_id,
            session_data=session_data,
            user_message=req.question,
            assistant_message=msg,
            done_status="continue",
            retry_after_ms=800,
        )
    except _ChatAbort:
        raise
    except Exception as e:
        logger.debug(f"prompt injection guardrail failed (best-effort): {e}")


def _prepare_chat_context_or_abort(
    *,
    req: ChatRequest,
    session_id: str,
    request_id: str,
    user_id: str,
    session_data: Dict[str, Any],
) -> Dict[str, Any]:
    from homework_agent.api._chat_stages import _prepare_chat_context_or_abort as _impl

    return _impl(
        req=req,
        session_id=session_id,
        request_id=request_id,
        user_id=user_id,
        session_data=session_data,
    )


async def _stream_socratic_llm_to_sse(
    *,
    llm_client: LLMClient,
    req: ChatRequest,
    session_id: str,
    user_id: str,
    session_data: Dict[str, Any],
    wrong_item_context: Dict[str, Any],
    current_turn: int,
    provider_str: str,
    model_override: Optional[str],
    prompt_variant: Optional[str],
    request_id: str,
    idempotency_key: Optional[str],
    started_m: float,
) -> AsyncIterator[bytes]:
    from homework_agent.api._chat_stages import _stream_socratic_llm_to_sse as _impl

    async for chunk in _impl(
        llm_client=llm_client,
        req=req,
        session_id=session_id,
        user_id=user_id,
        session_data=session_data,
        wrong_item_context=wrong_item_context,
        current_turn=current_turn,
        provider_str=provider_str,
        model_override=model_override,
        prompt_variant=prompt_variant,
        request_id=request_id,
        idempotency_key=idempotency_key,
        started_m=started_m,
    ):
        yield chunk


async def _run_chat_turn(
    *,
    llm_client: LLMClient,
    req: ChatRequest,
    session_id: str,
    request_id: str,
    user_id: str,
    idempotency_key: Optional[str],
    session_data: Dict[str, Any],
    started_m: float,
) -> AsyncIterator[bytes]:
    provider_str, model_override = _select_chat_model_or_raise(req)
    current_turn = session_data["interaction_count"]
    prompt_variant: Optional[str] = None
    prompt_version: Optional[str] = None
    try:
        settings = get_settings()
        flags_json = str(getattr(settings, "feature_flags_json", "{}") or "{}")
        salt = str(getattr(settings, "feature_flags_salt", "ff_v1") or "ff_v1")
        key = (user_id or session_id or "").strip() or "anonymous"
        d = decide_feature_flag(
            flags_json=flags_json,
            name="prompt.socratic_tutor_system",
            key=key,
            salt=salt,
        )
        if d.enabled and d.variant:
            prompt_variant = str(d.variant)
        try:
            from homework_agent.utils.prompt_manager import get_prompt_manager

            pm = get_prompt_manager()
            meta = pm.meta("socratic_tutor_system.yaml", variant=prompt_variant)
            prompt_version = str(meta.get("version") or "").strip() or None
        except Exception:
            prompt_version = None
    except Exception:
        prompt_variant = None
        prompt_version = None

    log_event(
        logger,
        "run_versions",
        request_id=request_id,
        session_id=session_id,
        prompt_id="socratic_tutor_system",
        prompt_version=prompt_version or "unknown",
        prompt_variant=prompt_variant,
        provider=provider_str,
        model=model_override or None,
    )
    try:
        from homework_agent.services.context_compactor import compact_session_history

        if compact_session_history(session_data, provider=provider_str):
            # Persist immediately so an early abort still keeps summary/history trimming.
            try:
                try:
                    from homework_agent.security.safety import (
                        sanitize_session_data_for_persistence,
                    )

                    sanitize_session_data_for_persistence(session_data)
                except Exception as e:
                    logger.debug(
                        f"Sanitizing compacted session for persistence failed (best-effort): {e}"
                    )
                save_session(session_id, session_data)
            except Exception as e:
                logger.debug(f"Persisting compacted session failed (best-effort): {e}")
    except Exception as e:
        logger.debug(f"Session compaction failed (best-effort): {e}")

    _prompt_injection_guardrail_abort_if_needed(
        req=req,
        session_id=session_id,
        session_data=session_data,
        request_id=request_id,
    )

    wrong_item_context = _prepare_chat_context_or_abort(
        req=req,
        session_id=session_id,
        request_id=request_id,
        user_id=user_id,
        session_data=session_data,
    )

    async for chunk in _run_mandatory_visual_path(
        req=req,
        session_id=session_id,
        request_id=request_id,
        user_id=user_id,
        session_data=session_data,
        wrong_item_context=wrong_item_context,
    ):
        yield chunk

    _apply_user_corrections(
        session_data=session_data,
        wrong_item_context=wrong_item_context,
        user_message=req.question,
    )

    if "focus_question" not in wrong_item_context:
        _abort_with_assistant_message(
            session_id=session_id,
            session_data=session_data,
            message="系统未能绑定到具体题目，请在【智能批改】中重新批改后再试。",
            done_status="error",
        )

    settings = get_settings()
    if bool(getattr(settings, "chat_relook_enabled", False)):
        await _best_effort_relook_if_needed(
            req=req,
            session_id=session_id,
            request_id=request_id,
            wrong_item_context=wrong_item_context,
        )
        _fail_closed_if_vfe_failed_this_turn(
            req=req,
            session_id=session_id,
            session_data=session_data,
            wrong_item_context=wrong_item_context,
        )

        # Guardrail: if user is challenging diagram relations but we still have no visual evidence, stop guessing.
        _diagram_guardrail_abort_if_needed(
            req=req,
            session_id=session_id,
            session_data=session_data,
            wrong_item_context=wrong_item_context,
        )

    async for chunk in _stream_socratic_llm_to_sse(
        llm_client=llm_client,
        req=req,
        session_id=session_id,
        user_id=user_id,
        session_data=session_data,
        wrong_item_context=wrong_item_context,
        current_turn=current_turn,
        provider_str=provider_str,
        model_override=model_override,
        prompt_variant=prompt_variant,
        request_id=request_id,
        idempotency_key=idempotency_key,
        started_m=started_m,
    ):
        yield chunk


async def chat_stream(
    req: ChatRequest,
    request: Request,
    last_event_id: Optional[str] = Header(None),
) -> AsyncIterator[bytes]:
    """
    SSE流式苏格拉底辅导:
    - heartbeat/chat/done/error事件
    - 默认不限轮（按交互轮次递进提示；是否限制由上层产品/前端控制）
    - Session 24小时TTL
    - last-event-id支持断线续接(仅用于恢复session)
    """
    llm_client = LLMClient()

    request_id_override = getattr(getattr(request, "state", None), "request_id", None)
    session_id, request_id, user_id, started_m, now_ts, session_data = (
        _init_chat_request(
            req=req,
            headers=request.headers,
            last_event_id=last_event_id,
            request_id_override=request_id_override,
        )
    )
    idempotency_key = (
        str(request.headers.get("X-Idempotency-Key") or "").strip() or None
    )

    # Client may request a history-only replay (no new LLM turn, no quota charge).
    # Used by frontend to show chat history immediately when entering AITutor page.
    is_init = str(request.headers.get("X-Chat-Init") or "").strip() == "1"

    settings = get_settings()
    if (not is_init) and str(
        getattr(settings, "auth_mode", "dev") or "dev"
    ).strip().lower() != "dev":
        wallet = load_wallet(user_id=user_id)
        if not wallet or wallet.bt_spendable <= 0:
            _abort_with_error_event(
                "quota_insufficient",
                "额度不足：请升级订阅或购买算力后再使用 AI 辅导。",
            )

    submission_id = str(getattr(req, "submission_id", "") or "").strip()
    rehydrated = False
    if submission_id:
        # If the client explicitly provides a submission_id, prefer rehydrate when:
        # - session is missing, OR
        # - session exists but is expired (TTL), OR
        # - client did not provide session_id explicitly.
        expired = False
        try:
            if session_data:
                updated_ts = _coerce_ts(session_data.get("updated_at")) or now_ts
                expired = (now_ts - float(updated_ts)) > float(SESSION_TTL_SECONDS)
        except Exception:
            expired = False
        if (not session_data) or expired or (not req.session_id):
            # Best-effort: build a new session from durable submission facts.
            # This keeps "Ask Teacher" usable for historical submissions.
            try:
                session_id, session_data = await asyncio.to_thread(
                    _rehydrate_session_from_submission_or_abort,
                    req=req,
                    request_id=request_id,
                    user_id=user_id,
                    submission_id=submission_id,
                    now_ts=now_ts,
                )
            except _ChatAbort as abort:
                for c in abort.chunks:
                    yield c
                return
            try:
                req.session_id = session_id
            except Exception:
                pass
            rehydrated = True

    log_event(
        logger,
        "chat_request",
        request_id=request_id,
        session_id=session_id,
        user_id=user_id,
        subject=getattr(req.subject, "value", str(req.subject)),
        question_len=len(req.question or ""),
        has_last_event_id=bool(last_event_id),
        submission_id=submission_id or None,
        rehydrated=rehydrated,
    )

    _touch_submission_best_effort(user_id=user_id, session_id=session_id)
    session_data = _ensure_chat_session_or_abort(
        req=req,
        session_id=session_id,
        session_data=session_data,
        now_ts=now_ts,
        last_event_id=last_event_id,
    )

    for c in _emit_initial_events(
        req=req,
        session_id=session_id,
        session_data=session_data,
        last_event_id=last_event_id,
        has_explicit_session_id=bool(req.session_id),
    ):
        yield c

    if is_init:
        yield _sse_event(
            "done", json.dumps({"status": "ready", "session_id": session_id})
        )
        return

    try:
        async for chunk in _run_chat_turn(
            llm_client=llm_client,
            req=req,
            session_id=session_id,
            request_id=request_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
            session_data=session_data,
            started_m=started_m,
        ):
            yield chunk

    except _ChatAbort as abort:
        for c in abort.chunks:
            yield c
        return
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
        error_msg = json.dumps(
            build_error_payload(
                code=ErrorCode.SERVICE_ERROR,
                message=str(e),
                request_id=request_id,
                session_id=session_id,
            )
        )
        yield f"event: error\ndata: {error_msg}\n\n".encode("utf-8")
        yield b'event: done\ndata: {"status":"error"}\n\n'


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
