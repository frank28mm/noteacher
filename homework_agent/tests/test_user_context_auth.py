from __future__ import annotations

import types

import pytest
from fastapi import HTTPException

import homework_agent.utils.user_context as uc


def test_require_user_id_prefers_bearer_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(uc, "_verify_supabase_jwt", lambda token: "user_123" if token == "t" else None)
    monkeypatch.setattr(uc, "get_settings", lambda: types.SimpleNamespace(auth_required=False))
    assert uc.require_user_id(authorization="Bearer t", x_user_id="dev_x") == "user_123"


def test_require_user_id_invalid_token_raises_401(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(uc, "_verify_supabase_jwt", lambda _token: None)
    monkeypatch.setattr(uc, "get_settings", lambda: types.SimpleNamespace(auth_required=False))
    with pytest.raises(HTTPException) as ei:
        uc.require_user_id(authorization="Bearer bad", x_user_id="dev_x")
    assert ei.value.status_code == 401


def test_require_user_id_auth_required_raises_401_when_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(uc, "get_settings", lambda: types.SimpleNamespace(auth_required=True))
    with pytest.raises(HTTPException) as ei:
        uc.require_user_id(authorization=None, x_user_id=None)
    assert ei.value.status_code == 401


def test_require_user_id_falls_back_to_dev_when_not_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(uc, "get_settings", lambda: types.SimpleNamespace(auth_required=False))
    assert uc.require_user_id(authorization=None, x_user_id="u") == "u"

