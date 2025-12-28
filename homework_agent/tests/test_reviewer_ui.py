from __future__ import annotations

import os

from fastapi.testclient import TestClient

from homework_agent.main import create_app
from homework_agent.utils.settings import get_settings


def test_reviewer_ui_disabled_by_default() -> None:
    get_settings.cache_clear()
    os.environ.pop("REVIEW_UI_ENABLED", None)
    app = create_app()
    client = TestClient(app)
    r = client.get("/api/v1/reviewer")
    assert r.status_code == 404


def test_reviewer_ui_enabled_serves_html() -> None:
    get_settings.cache_clear()
    os.environ["REVIEW_UI_ENABLED"] = "1"
    app = create_app()
    client = TestClient(app)
    r = client.get("/api/v1/reviewer")
    assert r.status_code == 200
    assert "Reviewer Workbench" in r.text
