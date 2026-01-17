from __future__ import annotations

import types

import homework_agent.utils.jwt_utils as ju


def test_issue_and_verify_jwt_roundtrip(monkeypatch):
    monkeypatch.setattr(
        ju,
        "get_settings",
        lambda: types.SimpleNamespace(
            jwt_secret="secret", jwt_issuer="noteacher", jwt_access_token_ttl_seconds=3600
        ),
    )
    token = ju.issue_access_token(user_id="user_1", phone="+8613800138000")
    decoded = ju.verify_access_token(token)
    assert decoded["sub"] == "user_1"
    assert decoded["phone"] == "+8613800138000"
    assert decoded["iss"] == "noteacher"
