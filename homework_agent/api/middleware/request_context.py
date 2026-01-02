from __future__ import annotations

import uuid
from contextvars import ContextVar

from fastapi import Request

from homework_agent.utils.metrics import Timer, inc_counter, observe_histogram
from homework_agent.utils.observability import get_request_id_from_headers

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
session_id_var: ContextVar[str] = ContextVar("session_id", default="")


def get_request_id() -> str:
    return request_id_var.get() or ""


def get_session_id() -> str:
    return session_id_var.get() or ""


def get_session_id_from_request(request: Request) -> str | None:
    """
    Best-effort session_id extraction for early failures (401/422/middleware errors).
    We intentionally avoid reading request body in middleware.
    """
    try:
        sid = getattr(getattr(request, "state", None), "session_id", None)
        if sid:
            return str(sid).strip() or None
    except Exception:
        sid = None

    try:
        sid = request.headers.get("X-Session-Id")
        if sid and str(sid).strip():
            return str(sid).strip()
    except Exception:
        pass

    try:
        sid = request.query_params.get("session_id") or request.query_params.get(
            "sessionId"
        )
        if sid and str(sid).strip():
            return str(sid).strip()
    except Exception:
        pass

    return None


async def request_context_middleware(request: Request, call_next):
    """
    Request context middleware:
    - Ensure request_id exists and is echoed via X-Request-Id.
    - Best-effort session_id extraction and echo via X-Session-Id.
    - Provide contextvars for downstream logs (optional).
    - Emit basic request metrics (best-effort).
    """
    t = Timer()
    request_id = getattr(getattr(request, "state", None), "request_id", None) or (
        get_request_id_from_headers(request.headers)
    )
    if not request_id:
        request_id = f"req_{uuid.uuid4().hex[:12]}"

    session_id = get_session_id_from_request(request)

    token_rid = request_id_var.set(str(request_id))
    token_sid = session_id_var.set(str(session_id or ""))
    try:
        try:
            request.state.request_id = str(request_id)
        except Exception:
            pass
        if session_id:
            try:
                request.state.session_id = str(session_id)
            except Exception:
                pass

        response = await call_next(request)

        try:
            response.headers["X-Request-Id"] = str(request_id)
        except Exception:
            pass
        if session_id:
            try:
                response.headers["X-Session-Id"] = str(session_id)
            except Exception:
                pass

        try:
            path = str(request.url.path or "")
            method = str(request.method or "")
            status_code = str(getattr(response, "status_code", 0))
            inc_counter(
                "http_requests_total",
                labels={"path": path, "method": method, "status": status_code},
            )
            observe_histogram(
                "http_request_duration_seconds",
                value=t.elapsed_seconds(),
                buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
                labels={"path": path, "method": method},
            )
        except Exception:
            pass
        return response
    finally:
        request_id_var.reset(token_rid)
        session_id_var.reset(token_sid)
