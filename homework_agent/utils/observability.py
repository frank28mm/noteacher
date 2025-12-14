from __future__ import annotations

import json
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

