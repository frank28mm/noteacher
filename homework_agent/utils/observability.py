from __future__ import annotations

import json
import time
import logging
import inspect
from functools import wraps
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
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)
        )
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
        # Import lazily to avoid coupling/security overhead in hot paths.
        from homework_agent.security.safety import sanitize_value_for_log

        # Rule alignment: ensure non-loop events still carry an explicit `iteration`
        # when a session_id exists (use 0 as the stable default).
        if "session_id" in fields and "iteration" not in fields:
            fields = dict(fields)
            fields["iteration"] = 0

        payload: Dict[str, Any] = {"event": event}
        for k, v in fields.items():
            if v is None:
                continue
            payload[str(k)] = sanitize_value_for_log(_safe_value(v))
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        fn = getattr(logger, level, None) or getattr(logger, "info", None)
        if fn:
            fn(line)
    except Exception:
        return


def log_llm_usage(
    logger,
    *,
    request_id: str,
    session_id: str,
    model: str,
    provider: str,
    usage: Any,
    stage: str,
    level: str = "info",
) -> None:
    """
    Convenience helper to emit a stable, structured LLM usage event for cost/tokens tracing.
    Best-effort and must never raise.

    Expected `usage` shape (best-effort):
      {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
    """
    try:
        u = _safe_value(usage) if usage is not None else {}
        if not isinstance(u, dict):
            u = {"usage": u}
        # Best-effort metrics export (Prometheus-style endpoint).
        try:
            from homework_agent.utils.metrics import inc_counter

            total = u.get("total_tokens")
            if total is not None:
                inc_counter(
                    "llm_tokens_total",
                    labels={
                        "provider": str(provider or ""),
                        "model": str(model or ""),
                        "stage": str(stage or ""),
                    },
                    value=float(total),
                )
        except Exception:
            pass
        log_event(
            logger,
            "llm_usage",
            level=level,
            request_id=str(request_id or ""),
            session_id=str(session_id or ""),
            provider=str(provider or ""),
            model=str(model or ""),
            stage=str(stage or ""),
            prompt_tokens=u.get("prompt_tokens"),
            completion_tokens=u.get("completion_tokens"),
            total_tokens=u.get("total_tokens"),
        )
    except Exception:
        return


def _truncate(value: Any, *, limit: int = 500) -> Any:
    try:
        s = json.dumps(_safe_value(value), ensure_ascii=False)
    except Exception:
        try:
            s = str(value)
        except Exception:
            s = repr(value)
    if len(s) <= limit:
        return s
    return s[:limit] + "…"


def trace_span(
    name: str,
    *,
    include_args: bool = False,
    include_result: bool = False,
) -> Any:
    """
    Lightweight tracing decorator.
    Emits trace_start/trace_end events via log_event.
    """

    def decorator(fn):
        logger = logging.getLogger(fn.__module__)

        if inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def async_wrapper(*args, **kwargs):
                start = time.monotonic()
                payload: Dict[str, Any] = {"span": name}
                if include_args:
                    safe_args = (
                        args[1:] if args and hasattr(args[0], "__class__") else args
                    )
                    payload["args"] = _truncate(safe_args)
                    payload["kwargs"] = _truncate(kwargs)
                log_event(logger, "trace_start", **payload)
                try:
                    result = await fn(*args, **kwargs)
                except Exception as e:
                    log_event(
                        logger,
                        "trace_end",
                        level="warning",
                        span=name,
                        elapsed_ms=int((time.monotonic() - start) * 1000),
                        error_type=e.__class__.__name__,
                        error=str(e),
                    )
                    raise
                if include_result:
                    payload["result"] = _truncate(result)
                log_event(
                    logger,
                    "trace_end",
                    span=name,
                    elapsed_ms=int((time.monotonic() - start) * 1000),
                )
                return result

            return async_wrapper

        @wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            payload: Dict[str, Any] = {"span": name}
            if include_args:
                safe_args = args[1:] if args and hasattr(args[0], "__class__") else args
                payload["args"] = _truncate(safe_args)
                payload["kwargs"] = _truncate(kwargs)
            log_event(logger, "trace_start", **payload)
            try:
                result = fn(*args, **kwargs)
            except Exception as e:
                log_event(
                    logger,
                    "trace_end",
                    level="warning",
                    span=name,
                    elapsed_ms=int((time.monotonic() - start) * 1000),
                    error_type=e.__class__.__name__,
                    error=str(e),
                )
                raise
            if include_result:
                payload["result"] = _truncate(result)
            log_event(
                logger,
                "trace_end",
                span=name,
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
            return result

        return wrapper

    return decorator


def get_request_id_from_headers(headers: Any) -> Optional[str]:
    """
    Extract a correlation id from common headers.
    - X-Request-Id / X-Request-ID
    - X-Correlation-Id
    Returns stripped string or None.
    """
    try:
        for key in (
            "x-request-id",
            "x-request-id".upper(),
            "x-correlation-id",
            "x-correlation-id".upper(),
        ):
            v = headers.get(key) if hasattr(headers, "get") else None
            if not v:
                continue
            s = str(v).strip()
            if s:
                return s
    except Exception:
        return None
    return None
