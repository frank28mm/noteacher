from __future__ import annotations

import os

from fastapi.testclient import TestClient

from homework_agent.main import create_app
from homework_agent.utils.settings import get_settings
from homework_agent.services.review_queue import enqueue_review_item


def test_review_api_disabled_by_default() -> None:
    get_settings.cache_clear()
    os.environ.pop("REVIEW_API_ENABLED", None)
    app = create_app()
    client = TestClient(app)
    r = client.get("/api/v1/review/items")
    assert r.status_code == 404


def test_review_api_auth_and_flow(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("REVIEW_API_ENABLED", "1")
    monkeypatch.setenv("REVIEW_ADMIN_TOKEN", "t")
    app = create_app()
    client = TestClient(app)

    r = client.get("/api/v1/review/items")
    assert r.status_code == 403

    # enqueue a review item into the cache fallback queue
    item_id = enqueue_review_item(
        request_id="req1",
        session_id="sess1",
        subject="math",
        warning_codes=["needs_review", "diagram_roi_not_found"],
        evidence_urls=["https://example.com/a.png?access_token=abc"],
        run_versions={"prompt_id": "autonomous", "prompt_version": "v1"},
        note="test",
    )
    assert item_id

    r2 = client.get(
        "/api/v1/review/items?status_filter=open&limit=10",
        headers={"X-Admin-Token": "t"},
    )
    assert r2.status_code == 200
    data = r2.json()
    assert any(it.get("item_id") == item_id for it in (data.get("items") or []))

    rr = client.post(
        f"/api/v1/review/items/{item_id}/resolve",
        json={"resolved_by": "tester", "note": "ok"},
        headers={"X-Admin-Token": "t"},
    )
    assert rr.status_code == 200

    r3 = client.get(
        "/api/v1/review/items?status_filter=resolved&limit=10",
        headers={"X-Admin-Token": "t"},
    )
    assert r3.status_code == 200
    data3 = r3.json()
    assert any(
        it.get("item_id") == item_id and it.get("status") == "resolved"
        for it in (data3.get("items") or [])
    )
