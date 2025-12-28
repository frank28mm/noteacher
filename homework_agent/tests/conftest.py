import os
import sys

# Ensure project root is on sys.path for test imports
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Avoid cross-test contamination: Settings are cached via lru_cache and depend on env vars.
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    from homework_agent.utils.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
