import json

import pytest
from fastapi.testclient import TestClient

from homework_agent.api.session import save_question_bank, save_session
from homework_agent.main import create_app


client = TestClient(create_app())


def _parse_sse_events(body: str) -> list[tuple[str, str]]:
    """
    Parse minimal SSE payload as emitted by our StreamingResponse.
    Returns a list of (event, data_str).
    """
    events: list[tuple[str, str]] = []
    cur_event: str | None = None
    cur_data: list[str] = []
    for line in body.splitlines():
        if line.startswith("event:"):
            # Flush previous
            if cur_event is not None:
                events.append((cur_event, "\n".join(cur_data).strip()))
                cur_data = []
            cur_event = line.split(":", 1)[1].strip()
            continue
        if line.startswith("data:"):
            cur_data.append(line.split(":", 1)[1].lstrip())
            continue
        if not line.strip():
            # blank line = delimiter; flush
            if cur_event is not None:
                events.append((cur_event, "\n".join(cur_data).strip()))
                cur_event = None
                cur_data = []
    if cur_event is not None:
        events.append((cur_event, "\n".join(cur_data).strip()))
    return events


def test_chat_sse_sequence_contract():
    """
    Canary: chat must emit at least one `chat` event and end with a `done` event.
    We use a request that does not require LLM/network and returns quickly.
    """
    payload = {
        "history": [],
        "question": "你好",
        "subject": "math",
        "session_id": "sess_sse_contract",
    }
    resp = client.post("/api/v1/chat", json=payload)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse_events(resp.text)
    assert any(e == "chat" for e, _ in events)
    assert any(e == "done" for e, _ in events)


def test_chat_fail_closed_when_visual_required(monkeypatch: pytest.MonkeyPatch):
    """
    Canary: when user explicitly asks to "看图" but qindex is unavailable/unconfigured,
    chat must fail-closed (say it cannot see) and must not hallucinate diagram relations.
    """
    session_id = "sess_visual_fail_closed"

    # Seed session to have a stable focus question.
    save_session(session_id, {"history": [], "focus_question_number": "9", "interaction_count": 0})
    save_question_bank(
        session_id,
        {
            "session_id": session_id,
            "subject": "math",
            "page_image_urls": [],
            "questions": {"9": {"question_content": "如图，已知∠1=150°，∠BCD=30°，试说明AD∥BC。"}},
        },
    )

    # Force qindex unavailable to ensure deterministic fail-closed behavior.
    monkeypatch.setattr(
        # chat.py imports qindex_is_configured directly; patch the imported symbol.
        "homework_agent.api.chat.qindex_is_configured",
        lambda: (False, "ocr_disabled (OCR_PROVIDER=disabled)"),
    )

    payload = {
        "history": [],
        "question": "看图，别乱说",
        "subject": "math",
        "session_id": session_id,
    }
    resp = client.post("/api/v1/chat", json=payload)
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    chat_payloads = [d for e, d in events if e == "chat" and d]
    assert chat_payloads, "expected at least one chat event"

    # Our server packs ChatResponse as JSON; parse the last chat event.
    last = json.loads(chat_payloads[-1])
    content = last["messages"][0]["content"]

    assert "看不到图" in content or "无法" in content
    assert "结合图形" not in content
    assert "从图形来看" not in content
