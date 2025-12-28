from __future__ import annotations

import os

from fastapi.testclient import TestClient

from homework_agent.main import create_app
from homework_agent.utils.settings import get_settings


def test_metrics_endpoint_disabled_by_default() -> None:
    get_settings.cache_clear()
    os.environ.pop("METRICS_ENABLED", None)
    app = create_app()
    client = TestClient(app)
    r = client.get("/metrics")
    assert r.status_code == 404


def test_metrics_endpoint_requires_token_when_configured() -> None:
    get_settings.cache_clear()
    os.environ["METRICS_ENABLED"] = "1"
    os.environ["METRICS_TOKEN"] = "t"
    app = create_app()
    client = TestClient(app)
    r = client.get("/metrics")
    assert r.status_code == 403
    r2 = client.get("/metrics", headers={"X-Metrics-Token": "t"})
    assert r2.status_code == 200
    assert "http_requests_total" in r2.text
