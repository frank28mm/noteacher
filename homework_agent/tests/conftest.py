import os
import sys

# Force test env defaults early (before any TestClient/create_app import).
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("AUTH_MODE", "dev")
os.environ.setdefault("AUTH_REQUIRED", "0")
os.environ.setdefault("REQUIRE_REDIS", "0")
os.environ.setdefault("LOAD_DOTENV_ON_IMPORT", "0")
os.environ.setdefault("AUTO_QINDEX_ON_GRADE", "1")

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


@pytest.fixture(autouse=True)
def _set_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Make test runs deterministic and decoupled from local .env.
    """
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_REQUIRED", "0")
    monkeypatch.setenv("REQUIRE_REDIS", "0")
    monkeypatch.setenv("LOAD_DOTENV_ON_IMPORT", "0")
    yield
