from __future__ import annotations

from fastapi.testclient import TestClient

from homework_agent.main import create_app


def test_grade_500_does_not_leak_internal_error(monkeypatch) -> None:
    from homework_agent.api import grade as grade_api

    async def _boom(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("SECRET_INTERNAL=token123; stack=/tmp/x.py")

    monkeypatch.setattr(grade_api, "perform_grading", _boom)
    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/v1/grade",
        headers={"X-User-Id": "u1"},
        json={
            "subject": "math",
            "vision_provider": "qwen3",
            "images": [{"url": "https://example.com/a.jpg"}],
        },
    )
    assert resp.status_code == 500
    body = resp.json()
    text = resp.text
    assert "SECRET_INTERNAL" not in text
    assert "token123" not in text
    # Still has a canonical error payload and request_id for debugging.
    assert body.get("code") == "E5000"
    assert body.get("request_id")
