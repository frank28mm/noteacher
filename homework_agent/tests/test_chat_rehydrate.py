from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from homework_agent.main import create_app


client = TestClient(create_app())


def _parse_sse_events(body: str) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    cur_event: str | None = None
    cur_data: list[str] = []
    for line in body.splitlines():
        if line.startswith("event:"):
            if cur_event is not None:
                events.append((cur_event, "\n".join(cur_data).strip()))
                cur_data = []
            cur_event = line.split(":", 1)[1].strip()
            continue
        if line.startswith("data:"):
            cur_data.append(line.split(":", 1)[1].lstrip())
            continue
        if not line.strip():
            if cur_event is not None:
                events.append((cur_event, "\n".join(cur_data).strip()))
                cur_event = None
                cur_data = []
    if cur_event is not None:
        events.append((cur_event, "\n".join(cur_data).strip()))
    return events


def test_chat_rehydrate_from_submission_id_emits_session_id(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "homework_agent.services.llm.LLMClient.socratic_tutor_stream",
        lambda *args, **kwargs: iter(["stub response"]),
    )

    monkeypatch.setattr(
        "homework_agent.api.chat._load_submission_snapshot_for_chat",
        lambda **kwargs: {
            "submission_id": "sub1",
            "user_id": "u1",
            "subject": "math",
            "page_image_urls": ["https://example.com/p1.jpg"],
            "vision_raw_text": "Q1: 1+1=?",
            "grade_result": {
                "questions": [
                    {
                        "question_number": "1",
                        "question_content": "1+1=?",
                        "verdict": "incorrect",
                        "answer_state": "has_answer",
                    }
                ],
                "wrong_items": [
                    {"question_number": "1", "item_id": "it1", "reason": "x"}
                ],
                "warnings": [],
                "summary": "ok",
            },
            "warnings": [],
        },
    )

    payload = {
        "history": [],
        "question": "讲讲第1题",
        "subject": "math",
        "submission_id": "sub1",
        "context_item_ids": ["it1"],
    }
    resp = client.post("/api/v1/chat", json=payload, headers={"X-User-Id": "u1"})
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    hb_payloads = [d for e, d in events if e == "heartbeat" and d]
    assert hb_payloads, "expected at least one heartbeat event"
    hb = json.loads(hb_payloads[0])
    assert isinstance(hb.get("timestamp"), str)
    assert isinstance(hb.get("session_id"), str)
    assert hb["session_id"].startswith("session_")
    assert any(e == "chat" for e, _ in events)
    assert any(e == "done" for e, _ in events)


def test_chat_rehydrate_subject_mismatch_yields_error_event(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "homework_agent.api.chat._load_submission_snapshot_for_chat",
        lambda **kwargs: {
            "submission_id": "sub1",
            "user_id": "u1",
            "subject": "english",
            "page_image_urls": [],
            "vision_raw_text": "",
            "grade_result": {"questions": [{"question_number": "1"}]},
        },
    )
    payload = {
        "history": [],
        "question": "hi",
        "subject": "math",
        "submission_id": "sub1",
    }
    resp = client.post("/api/v1/chat", json=payload, headers={"X-User-Id": "u1"})
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    err_payloads = [d for e, d in events if e == "error" and d]
    assert err_payloads, "expected error event"
    err = json.loads(err_payloads[0])
    assert err.get("code") == "SUBJECT_MISMATCH"

