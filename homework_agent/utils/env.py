from __future__ import annotations

from pathlib import Path


def load_project_dotenv() -> bool:
    """
    Load `.env` from the project root into `os.environ`.

    Why:
    - Some components (Redis cache/queue) rely on `os.getenv`.
    - `pydantic-settings` can read `.env` into Settings, but it does NOT populate `os.environ`.

    This is a no-op in production where env vars are already injected by the runtime.
    """
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return False

    here = Path(__file__).resolve()
    project_root = here.parents[2]

    candidates = [
        project_root / ".env",
        project_root / "homework_agent" / ".env",
    ]

    loaded = False
    for p in candidates:
        if p.exists():
            loaded = bool(load_dotenv(p, override=False)) or loaded
    return loaded
