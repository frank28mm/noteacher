import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse
from fastapi import Header

from homework_agent.api import routes
from homework_agent.utils.settings import get_settings
from homework_agent.utils.logging_setup import setup_file_logging, silence_noisy_loggers
from contextlib import asynccontextmanager

from homework_agent.utils.errors import (
    build_error_payload,
    error_code_for_http_status,
    ErrorCode,
)
from homework_agent.utils.observability import get_request_id_from_headers
from homework_agent.utils.metrics import (
    Timer,
    inc_counter,
    observe_histogram,
    render_prometheus,
)

logger = logging.getLogger(__name__)


def _get_session_id_from_request(request: Request) -> str | None:
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


def _validate_cors(settings) -> None:
    env = str(getattr(settings, "app_env", "dev") or "dev").strip().lower()
    origins = getattr(settings, "allow_origins", None) or []
    if not isinstance(origins, list):
        origins = [str(origins)]
    origins_norm = [str(o or "").strip() for o in origins if str(o or "").strip()]
    if env in {"prod", "production"}:
        if not origins_norm or any(o == "*" for o in origins_norm):
            raise RuntimeError(
                "CORS is not explicitly configured for production. "
                "Set ALLOW_ORIGINS to an explicit allowlist (no '*')."
            )


def create_app() -> FastAPI:
    settings = get_settings()
    _validate_cors(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ARG001
        # Always record backend logs to a file by default (disable with LOG_TO_FILE=0).
        if getattr(settings, "log_to_file", True):
            import logging

            level = getattr(logging, str(settings.log_level).upper(), logging.INFO)
            silence_noisy_loggers()
            setup_file_logging(log_file_path=str(settings.log_file_path), level=level)
        yield

    app = FastAPI(title="Homework Agent", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def _request_id_middleware(request: Request, call_next):
        t = Timer()
        request_id = getattr(
            getattr(request, "state", None), "request_id", None
        ) or get_request_id_from_headers(request.headers)
        if not request_id:
            import uuid

            request_id = f"req_{uuid.uuid4().hex[:12]}"
        try:
            request.state.request_id = str(request_id)
        except Exception:
            pass

        session_id = _get_session_id_from_request(request)
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

        # Best-effort request metrics (do not raise).
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

    @app.get("/metrics")
    async def metrics(
        x_metrics_token: str | None = Header(default=None, alias="X-Metrics-Token")
    ):
        settings = get_settings()
        if not getattr(settings, "metrics_enabled", False):
            return PlainTextResponse("metrics disabled\n", status_code=404)
        expected = str(getattr(settings, "metrics_token", "") or "").strip()
        if expected and str(x_metrics_token or "").strip() != expected:
            return PlainTextResponse("forbidden\n", status_code=403)
        return PlainTextResponse(
            render_prometheus(), media_type="text/plain; version=0.0.4"
        )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException):
        code = error_code_for_http_status(int(exc.status_code))
        detail = exc.detail
        # Keep FastAPI's default `detail` for compatibility, but also add our canonical payload.
        if isinstance(detail, dict):
            message = str(detail.get("error") or detail.get("message") or detail)
            details = detail
        else:
            message = str(detail)
            details = None
        request_id = getattr(
            getattr(request, "state", None), "request_id", None
        ) or get_request_id_from_headers(request.headers)
        session_id = _get_session_id_from_request(request)
        payload = {"detail": detail}
        payload.update(
            build_error_payload(
                code=code,
                message=message,
                details=details,
                request_id=request_id,
                session_id=session_id,
            )
        )
        return JSONResponse(status_code=int(exc.status_code), content=payload)

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        request_id = getattr(
            getattr(request, "state", None), "request_id", None
        ) or get_request_id_from_headers(request.headers)
        session_id = _get_session_id_from_request(request)
        payload = {"detail": exc.errors()}
        payload.update(
            build_error_payload(
                code=ErrorCode.VALIDATION_ERROR,
                message="Validation error",
                details={"errors": exc.errors()},
                request_id=request_id,
                session_id=session_id,
            )
        )
        return JSONResponse(status_code=422, content=payload)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        request_id = getattr(
            getattr(request, "state", None), "request_id", None
        ) or get_request_id_from_headers(request.headers)
        session_id = _get_session_id_from_request(request)
        payload = build_error_payload(
            code=ErrorCode.SERVICE_ERROR,
            message="Internal server error",
            request_id=request_id,
            session_id=session_id,
        )
        return JSONResponse(status_code=500, content=payload)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes.router, prefix="/api/v1")
    return app


app = create_app()
