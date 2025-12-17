import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi import HTTPException

from homework_agent.api import routes
from homework_agent.utils.settings import get_settings
from homework_agent.utils.logging_setup import setup_file_logging, silence_noisy_loggers
from contextlib import asynccontextmanager

from homework_agent.utils.errors import build_error_payload, error_code_for_http_status, ErrorCode

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

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
        payload = {"detail": detail}
        payload.update(
            build_error_payload(
                code=code,
                message=message,
                details=details,
                request_id=request.headers.get("X-Request-Id"),
            )
        )
        return JSONResponse(status_code=int(exc.status_code), content=payload)

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(request: Request, exc: RequestValidationError):
        payload = {"detail": exc.errors()}
        payload.update(
            build_error_payload(
                code=ErrorCode.VALIDATION_ERROR,
                message="Validation error",
                details={"errors": exc.errors()},
                request_id=request.headers.get("X-Request-Id"),
            )
        )
        return JSONResponse(status_code=422, content=payload)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        payload = build_error_payload(
            code=ErrorCode.SERVICE_ERROR,
            message="Internal server error",
            request_id=request.headers.get("X-Request-Id"),
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
