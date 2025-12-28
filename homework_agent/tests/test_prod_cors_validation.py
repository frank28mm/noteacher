from __future__ import annotations


import pytest

from homework_agent.main import create_app
from homework_agent.utils.settings import get_settings


def test_prod_env_rejects_star_cors(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ALLOW_ORIGINS", '["*"]')
    with pytest.raises(RuntimeError):
        create_app()


def test_prod_env_accepts_explicit_allowlist(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ALLOW_ORIGINS", '["https://example.com"]')
    app = create_app()
    assert app is not None
