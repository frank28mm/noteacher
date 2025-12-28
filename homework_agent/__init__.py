from __future__ import annotations

# Ensure local `.env` is loaded early for components that rely on `os.getenv`
# (Redis queue/cache). This keeps `python -m homework_agent.workers.qindex_worker`
# working without requiring manual `export` in dev.
try:
    from homework_agent.utils.env import load_project_dotenv

    load_project_dotenv()
except Exception:
    # Never hard-fail import for optional dev convenience.
    pass
