from __future__ import annotations

# Optional: load local `.env` on import only when explicitly enabled.
# This avoids polluting test environments while keeping a convenient opt-in for dev.
try:
    import os

    if str(os.getenv("LOAD_DOTENV_ON_IMPORT") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        from homework_agent.utils.env import load_project_dotenv

        load_project_dotenv()
except Exception:
    # Never hard-fail import for optional dev convenience.
    pass
