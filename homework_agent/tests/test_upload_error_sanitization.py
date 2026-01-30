from __future__ import annotations

from fastapi.testclient import TestClient

from homework_agent.main import create_app
from homework_agent.utils.settings import get_settings


def test_upload_500_does_not_leak_internal_error(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ALLOW_ORIGINS", '["https://example.com"]')
    monkeypatch.setenv("AUTH_REQUIRED", "1")
    monkeypatch.setenv("AUTH_MODE", "local")

    from homework_agent.api import upload as upload_api
    from homework_agent.utils import jwt_utils

    class _FakeStorage:
        def upload_files(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            raise RuntimeError("SECRET_INTERNAL=token123; stack=/tmp/x.py")

    monkeypatch.setattr(jwt_utils, "verify_access_token", lambda token: {"sub": "u1"})
    monkeypatch.setattr(upload_api, "get_storage_client", lambda: _FakeStorage())

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/v1/uploads",
        headers={"Authorization": "Bearer testtoken"},
        files={"file": ("test.jpg", b"abc", "image/jpeg")},
    )
    assert resp.status_code == 500
    body = resp.json()
    text = resp.text
    assert "SECRET_INTERNAL" not in text
    assert "token123" not in text
    assert body.get("code") == "E5000"
    assert body.get("detail") == "Internal server error"
    assert body.get("request_id")
