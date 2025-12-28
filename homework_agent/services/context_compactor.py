from __future__ import annotations

import logging
from typing import Any, Dict, List

from homework_agent.services.llm import LLMClient
from homework_agent.utils.settings import get_settings
from homework_agent.utils.observability import log_event

logger = logging.getLogger(__name__)


_SUMMARY_SYSTEM_PROMPT = (
    "你是对话摘要助手。请把历史对话压缩为简洁中文摘要，保留：\n"
    "1) 已知题目/题号与学生作答；\n"
    "2) 已确认的关键事实/结论；\n"
    "3) 用户纠错/偏好（如必须看图/必须信任视觉事实）。\n"
    "要求：不超过200字。"
)


def _deterministic_summary(
    history: List[Dict[str, Any]], *, max_chars: int = 200
) -> str:
    """
    CI-safe / provider-free summary.
    Keep only high-signal snippets from user/assistant messages.
    """
    if not history:
        return ""
    parts: List[str] = []
    for m in history:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "").strip().lower()
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            parts.append(f"用户: {content}")
        elif role == "assistant":
            parts.append(f"助理: {content}")
    if not parts:
        return ""
    tail = parts[-6:]
    joined = " | ".join(tail)
    if len(joined) <= max_chars:
        return joined
    return joined[: max(0, max_chars - 1)] + "…"


def summarize_history(
    history: List[Dict[str, Any]], *, provider: str = "silicon"
) -> str:
    if not history:
        return ""
    client = LLMClient()
    text_lines = []
    for m in history:
        role = (m.get("role") if isinstance(m, dict) else None) or ""
        content = (m.get("content") if isinstance(m, dict) else None) or ""
        if not content:
            continue
        text_lines.append(f"{role}: {str(content)}")
    if not text_lines:
        return ""

    prompt = "\n".join(text_lines)
    try:
        res = client.generate(
            prompt=prompt,
            system_prompt=_SUMMARY_SYSTEM_PROMPT,
            provider=provider,
            max_tokens=400,
            temperature=0.2,
        )
        summary = (res.text or "").strip()
        return summary
    except Exception as e:
        logger.debug(f"Summarize history failed: {e}")
        return ""


def compact_session_history(
    session_data: Dict[str, Any],
    *,
    provider: str = "silicon",
) -> bool:
    settings = get_settings()
    mode = (
        str(
            getattr(settings, "context_compaction_mode", "deterministic")
            or "deterministic"
        )
        .strip()
        .lower()
    )
    enabled_llm = bool(getattr(settings, "context_compaction_enabled", False))
    if mode in {"0", "false", "off", "disabled", "none"}:
        return False
    if mode not in {"deterministic", "llm"}:
        mode = "deterministic"

    history = session_data.get("history") or []
    if not isinstance(history, list):
        return False

    max_messages = int(settings.context_compaction_max_messages)
    overlap = int(settings.context_compaction_overlap)
    interval = int(settings.context_compaction_interval)
    if max_messages <= 0 or len(history) <= max_messages:
        return False

    # Only compact when history grows beyond interval to avoid frequent summaries.
    if len(history) % max(1, interval) != 0:
        return False

    to_summarize = history[:-overlap] if overlap > 0 else history
    if not to_summarize:
        return False

    if mode == "llm" and enabled_llm:
        summary = summarize_history(to_summarize, provider=provider)
    else:
        summary = _deterministic_summary(to_summarize)
    if not summary:
        return False

    session_data["summary"] = summary
    session_data["history"] = history[-overlap:] if overlap > 0 else []

    log_event(
        logger,
        "session_compacted",
        mode="llm" if (mode == "llm" and enabled_llm) else "deterministic",
        kept=len(session_data.get("history") or []),
        summarized=len(to_summarize),
    )
    return True
