from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from homework_agent.api import routes
from homework_agent.utils.settings import get_settings
from homework_agent.utils.logging_setup import setup_file_logging
from contextlib import asynccontextmanager


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ARG001
        # Always record backend logs to a file by default (disable with LOG_TO_FILE=0).
        if getattr(settings, "log_to_file", True):
            import logging

            level = getattr(logging, str(settings.log_level).upper(), logging.INFO)
            setup_file_logging(log_file_path=str(settings.log_file_path), level=level)
        yield

    app = FastAPI(title="Homework Agent", version="1.0.0", lifespan=lifespan)
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
