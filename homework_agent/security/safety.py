from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_RE_CN_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_RE_CN_IDCARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_RE_STUDENT_ID = re.compile(
    r"(?:学号|student[_-]?id)\s*[:：]?\s*(\d{6,12})", re.IGNORECASE
)

# Common secret-ish patterns (best-effort). Keep conservative to avoid over-redaction.
_RE_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{10,}\b")
_RE_OPENAI_SK = re.compile(r"\bsk-[A-Za-z0-9]{10,}\b")
_RE_JWT = re.compile(
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)
_RE_HTTP_URL = re.compile(r"https?://[^\s)]+")


_PROMPT_INJECTION_MARKERS = (
    "ignore previous instructions",
    "disregard previous instructions",
    "system prompt",
    "developer message",
    "begin system prompt",
    "end system prompt",
    "你现在是",
    "请忽略",
    "忽略以上",
    "无视以上",
    "开发者消息",
    "系统提示",
)


def redact_url_query_params(
    url: str,
    *,
    redact_params: Tuple[str, ...] = (
        "access_token",
        "accesstoken",
        "authorization",
        "token",
        "sig",
        "signature",
        "x-amz-signature",
        "x-bce-signature",
        "x-bce-security-token",
    ),
) -> str:
    try:
        s = str(url or "").strip()
        if not s:
            return s
        parts = urlsplit(s)
        if not parts.scheme or not parts.netloc or not parts.query:
            return s
        redact_set = {p.lower() for p in redact_params}
        q = []
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            if str(k).lower() in redact_set:
                q.append((k, "***"))
            else:
                q.append((k, v))
        new_query = urlencode(q, doseq=True)
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)
        )
    except Exception:
        try:
            return str(url)
        except Exception:
            return ""


@dataclass(frozen=True)
class SafetyScan:
    warning_codes: List[str]
    needs_review: bool


def _is_url(s: str) -> bool:
    ss = str(s or "").strip().lower()
    return ss.startswith("http://") or ss.startswith("https://")


def detect_pii_codes(text: str) -> List[str]:
    if not text:
        return []
    s = str(text)
    codes: List[str] = []
    if _RE_EMAIL.search(s):
        codes.append("pii_email")
    if _RE_CN_PHONE.search(s):
        codes.append("pii_phone")
    if _RE_CN_IDCARD.search(s):
        codes.append("pii_idcard")
    if _RE_STUDENT_ID.search(s):
        codes.append("pii_student_id")
    return codes


def detect_prompt_injection(text: str) -> bool:
    if not text:
        return False
    s = str(text).lower()
    return any(marker in s for marker in _PROMPT_INJECTION_MARKERS)


def redact_secrets(text: str) -> str:
    if not text:
        return ""
    s = str(text)
    s = _RE_BEARER.sub("Bearer ***", s)
    s = _RE_OPENAI_SK.sub("sk-***", s)
    s = _RE_JWT.sub("***.***.***", s)
    return s


def redact_pii(text: str) -> str:
    if not text:
        return ""
    s = str(text)
    s = _RE_EMAIL.sub("***@***", s)
    s = _RE_CN_PHONE.sub("***PHONE***", s)
    s = _RE_CN_IDCARD.sub("***IDCARD***", s)
    s = _RE_STUDENT_ID.sub(lambda m: m.group(0).split(m.group(1))[0] + "***", s)
    return s


def sanitize_text_for_log(text: str) -> str:
    s = str(text or "")
    if _is_url(s):
        s = redact_url_query_params(s)
    else:
        # Redact query params in embedded URLs inside a larger text.
        if "http://" in s or "https://" in s:
            s = _RE_HTTP_URL.sub(lambda m: redact_url_query_params(m.group(0)), s)
    s = redact_secrets(s)
    s = redact_pii(s)
    return s


def sanitize_value_for_log(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return sanitize_text_for_log(value)
    if isinstance(value, (list, tuple)):
        return [sanitize_value_for_log(v) for v in value]
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            kk = str(k)
            out[kk] = sanitize_value_for_log(v)
        return out
    try:
        return sanitize_text_for_log(str(value))
    except Exception:
        return ""


def scan_safety(value: Any) -> SafetyScan:
    """
    Best-effort scan of a value for PII / prompt-injection markers.
    Returns machine-readable warning codes and whether it should trigger needs_review.
    """
    try:
        if isinstance(value, (dict, list, tuple)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value or "")
    except Exception:
        text = str(value or "")

    pii_codes = detect_pii_codes(text)
    injection = detect_prompt_injection(text)
    codes: List[str] = []
    if pii_codes:
        codes.append("pii_detected")
        codes.extend(pii_codes)
    if injection:
        codes.append("prompt_injection")
        codes.append("prompt_injection_suspected")
    # Needs review on any PII or injection.
    return SafetyScan(warning_codes=_dedupe_codes(codes), needs_review=bool(codes))


def sanitize_session_data_for_persistence(session_data: Dict[str, Any]) -> None:
    """
    Ensure secrets/PII never enter persisted session payloads.
    This mutates session_data in-place (best-effort).

    Applies to:
      - session_data["summary"]
      - session_data["history"][].content
    """
    try:
        summary = session_data.get("summary")
        if isinstance(summary, str) and summary.strip():
            session_data["summary"] = sanitize_text_for_log(summary)
    except Exception:
        pass

    try:
        hist = session_data.get("history")
        if not isinstance(hist, list):
            return
        for m in hist:
            if not isinstance(m, dict):
                continue
            content = m.get("content")
            if isinstance(content, str) and content:
                m["content"] = sanitize_text_for_log(content)
    except Exception:
        return


def _dedupe_codes(codes: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for c in codes or []:
        s = str(c or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out
