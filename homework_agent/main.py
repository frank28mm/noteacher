import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse
from fastapi import Header

from homework_agent.api import routes
from homework_agent.api.middleware.request_context import (
    request_context_middleware,
    get_session_id_from_request,
)
from homework_agent.utils.settings import get_settings
from homework_agent.utils.logging_setup import setup_file_logging, silence_noisy_loggers
from contextlib import asynccontextmanager

from homework_agent.utils.errors import (
    build_error_payload,
    error_code_for_http_status,
    ErrorCode,
)
from homework_agent.utils.observability import get_request_id_from_headers
from homework_agent.utils.metrics import render_prometheus

logger = logging.getLogger(__name__)


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


def _validate_prod_security(settings) -> None:
    env = str(getattr(settings, "app_env", "dev") or "dev").strip().lower()
    if env not in {"prod", "production"}:
        return
    if not bool(getattr(settings, "auth_required", False)):
        raise RuntimeError(
            "AUTH_REQUIRED must be enabled for production (set AUTH_REQUIRED=1)."
        )


def _is_test_env(settings) -> bool:
    env = str(getattr(settings, "app_env", "dev") or "dev").strip().lower()
    if env in {"test", "testing"}:
        return True
    # pytest sets this for each test; treat as test env for safety
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return False


def _validate_env_fail_fast(settings) -> None:
    """Check critical environment variables on startup (skip in test env)."""
    if _is_test_env(settings):
        return
    missing = []

    # Critical for everyone
    if not str(getattr(settings, "supabase_url", "") or "").strip():
        missing.append("SUPABASE_URL")
    if not str(getattr(settings, "supabase_key", "") or "").strip():
        missing.append("SUPABASE_KEY")
    if not str(getattr(settings, "redis_url", "") or "").strip():
        missing.append("REDIS_URL")

    # Critical for LLM/Vision
    if not str(getattr(settings, "ark_api_key", "") or "").strip():
        missing.append("ARK_API_KEY")
    if not str(getattr(settings, "silicon_api_key", "") or "").strip():
        missing.append("SILICON_API_KEY")

    if missing:
        raise RuntimeError(
            f"Missing critical environment variables: {', '.join(missing)}"
        )


def create_app() -> FastAPI:
    settings = get_settings()
    _validate_env_fail_fast(settings)
    _validate_cors(settings)
    _validate_prod_security(settings)

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
    async def _request_context_middleware(request: Request, call_next):
        return await request_context_middleware(request, call_next)

    @app.get("/healthz")
    async def healthz():
        """Liveness probe: returns 200 if the process is running."""
        return PlainTextResponse("ok")

    @app.get("/readyz")
    async def readyz():
        """
        Readiness probe: returns 200 if critical dependencies are healthy.
        Checks:
        - Redis connection
        - Supabase (optional? maybe just connectivity)
        """
        settings = get_settings()

        # 1. Check Redis (critical for workers)
        try:
            import redis.asyncio as redis

            r = redis.from_url(str(settings.redis_url), socket_timeout=1.0)
            await r.ping()
            await r.close()
        except Exception as e:
            logger.error(f"Readiness check failed (Redis): {e}")
            return PlainTextResponse("not ready (redis)", status_code=503)

        return PlainTextResponse("ready")

    @app.get("/metrics")
    async def metrics(
        x_metrics_token: str | None = Header(default=None, alias="X-Metrics-Token"),
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
        settings = get_settings()
        env = str(getattr(settings, "app_env", "dev") or "dev").strip().lower()
        detail = exc.detail
        # Keep FastAPI's default `detail` for compatibility, but also add our canonical payload.
        if isinstance(detail, dict):
            message = str(detail.get("error") or detail.get("message") or detail)
            details = detail
        else:
            message = str(detail)
            details = None
        if int(exc.status_code) >= 500 and env in {"prod", "production"}:
            # Do not leak internal error details in production.
            detail = "Internal server error"
            message = "Internal server error"
            details = None
        request_id = getattr(
            getattr(request, "state", None), "request_id", None
        ) or get_request_id_from_headers(request.headers)
        session_id = get_session_id_from_request(request)
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
        session_id = get_session_id_from_request(request)
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
        session_id = get_session_id_from_request(request)
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

    # Mount Admin Dashboard
    import os
    from fastapi.staticfiles import StaticFiles

    # root/homework_agent/main.py -> root/homework_agent/static/admin
    static_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "homework_agent", "static", "admin"
    )

    if os.path.isdir(static_dir):
        app.mount("/admin", StaticFiles(directory=static_dir, html=True), name="admin")

    return app


app = create_app()
