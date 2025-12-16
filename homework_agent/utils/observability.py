from __future__ import annotations

import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any, Dict, Optional


def _safe_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe_value(v) for k, v in value.items()}
    try:
        return str(value)
    except Exception:
        return repr(value)


def redact_url(
    url: str,
    *,
    redact_params: tuple[str, ...] = (
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
    """
    Redact sensitive query params from a URL for logging.
    Never raises; returns a best-effort sanitized URL.
    """
    try:
        s = str(url or "").strip()
        if not s:
            return s
        parts = urlsplit(s)
        if not parts.query:
            return s
        redact_set = {p.lower() for p in redact_params}
        q = []
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            if str(k).lower() in redact_set:
                q.append((k, "***"))
            else:
                q.append((k, v))
        new_query = urlencode(q, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
    except Exception:
        try:
            return str(url)
        except Exception:
            return ""


def log_event(logger, event: str, *, level: str = "info", **fields: Any) -> None:
    """
    Emit a single-line JSON log with a stable `event` key.
    This is best-effort and must never raise.
    """
    try:
        payload: Dict[str, Any] = {"event": event}
        for k, v in fields.items():
            if v is None:
                continue
            payload[str(k)] = _safe_value(v)
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        fn = getattr(logger, level, None) or getattr(logger, "info", None)
        if fn:
            fn(line)
    except Exception:
        return


def get_request_id_from_headers(headers: Any) -> Optional[str]:
    """
    Extract a correlation id from common headers.
    - X-Request-Id / X-Request-ID
    - X-Correlation-Id
    Returns stripped string or None.
    """
    try:
        for key in ("x-request-id", "x-request-id".upper(), "x-correlation-id", "x-correlation-id".upper()):
            v = headers.get(key) if hasattr(headers, "get") else None
            if not v:
                continue
            s = str(v).strip()
            if s:
                return s
    except Exception:
        return None
    return None
