from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from homework_agent.api import routes
from homework_agent.utils.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Homework Agent", version="1.0.0")
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
