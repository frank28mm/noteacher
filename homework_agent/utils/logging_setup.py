from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional


def _project_root() -> Path:
    # homework_agent/utils/logging_setup.py -> homework_agent/utils -> homework_agent -> repo root
    return Path(__file__).resolve().parents[2]


def setup_file_logging(
    *,
    log_file_path: str,
    level: int,
    logger_names: Optional[list[str]] = None,
) -> None:
    """
    Attach a rotating FileHandler to loggers. Idempotent across reloads.
    - `log_file_path` may be relative to project root.
    """
    if not log_file_path:
        return

    root = _project_root()
    path = Path(log_file_path)
    if not path.is_absolute():
        path = root / path

    os.makedirs(path.parent, exist_ok=True)

    handler_name = "hw_agent_file_handler"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    def _ensure(logger: logging.Logger) -> None:
        for h in logger.handlers:
            if getattr(h, "name", None) == handler_name:
                return

        h = TimedRotatingFileHandler(
            filename=str(path),
            when="midnight",
            interval=1,
            backupCount=14,
            encoding="utf-8",
            utc=False,
        )
        h.setLevel(level)
        h.setFormatter(fmt)
        h.name = handler_name
        logger.addHandler(h)

    targets = logger_names or [
        "",  # root
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "homework_agent",
    ]

    for name in targets:
        _ensure(logging.getLogger(name))

