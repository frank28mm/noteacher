import json
import uuid

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


def test_chat_sse_sequence_contract(monkeypatch: pytest.MonkeyPatch):
    """
    Canary: chat must emit at least one `chat` event and end with a `done` event.
    We use a request that does not require LLM/network and returns quickly.
    """
    monkeypatch.setattr(
        "homework_agent.services.llm.LLMClient.socratic_tutor_stream",
        lambda *args, **kwargs: iter(["stub response"]),
    )

    session_id = f"sess_sse_contract_{uuid.uuid4().hex[:8]}"
    save_session(
        session_id,
        {"history": [], "focus_question_number": "1", "interaction_count": 0},
    )
    save_question_bank(
        session_id,
        {
            "session_id": session_id,
            "subject": "math",
            "page_image_urls": [],
            "questions": {"1": {"question_content": "1+1=?"}},
        },
    )
    payload = {
        "history": [],
        "question": "你好",
        "subject": "math",
        "session_id": session_id,
    }
    resp = client.post("/api/v1/chat", json=payload)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse_events(resp.text)
    assert any(e == "chat" for e, _ in events)
    assert any(e == "done" for e, _ in events)


def test_chat_heartbeat_payload_contains_timestamp(monkeypatch: pytest.MonkeyPatch):
    """
    Contract: heartbeat event payload must be JSON and include a timestamp so clients can
    detect liveness without parsing SSE meta.
    """
    monkeypatch.setenv("CHAT_HEARTBEAT_INTERVAL_SECONDS", "0.05")
    monkeypatch.setenv("CHAT_PRODUCER_JOIN_TIMEOUT_SECONDS", "0.2")

    def slow_stream(*args, **kwargs):
        import time

        time.sleep(0.15)
        yield "stub response"

    monkeypatch.setattr(
        "homework_agent.services.llm.LLMClient.socratic_tutor_stream",
        slow_stream,
    )

    session_id = "sess_sse_heartbeat_contract"
    save_session(
        session_id,
        {"history": [], "focus_question_number": "1", "interaction_count": 0},
    )
    save_question_bank(
        session_id,
        {
            "session_id": session_id,
            "subject": "math",
            "page_image_urls": [],
            "questions": {"1": {"question_content": "1+1=?"}},
        },
    )

    payload = {
        "history": [],
        "question": "讲讲第1题",
        "subject": "math",
        "session_id": session_id,
    }
    resp = client.post("/api/v1/chat", json=payload)
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    hb_payloads = [d for e, d in events if e == "heartbeat" and d]
    assert hb_payloads, "expected at least one heartbeat event"

    obj = json.loads(hb_payloads[0])
    assert isinstance(obj.get("timestamp"), str)
    assert obj.get("timestamp")


def test_chat_allows_response_without_slices(monkeypatch: pytest.MonkeyPatch):
    """
    Canary: when user explicitly asks to "看图" but qindex is unavailable/unconfigured,
    chat should still return a response (no fail-closed gating).
    """
    session_id = "sess_visual_fail_closed"

    # Seed session to have a stable focus question.
    save_session(
        session_id,
        {"history": [], "focus_question_number": "9", "interaction_count": 0},
    )
    save_question_bank(
        session_id,
        {
            "session_id": session_id,
            "subject": "math",
            "page_image_urls": [],
            "questions": {
                "9": {"question_content": "如图，已知∠1=150°，∠BCD=30°，试说明AD∥BC。"}
            },
        },
    )

    # Force qindex unavailable to ensure we still respond without slices.
    monkeypatch.setattr(
        # chat.py imports qindex_is_configured directly; patch the imported symbol.
        "homework_agent.api.chat.qindex_is_configured",
        lambda: (False, "ocr_disabled (OCR_PROVIDER=disabled)"),
    )
    monkeypatch.setattr(
        "homework_agent.services.llm.LLMClient.socratic_tutor_stream",
        lambda *args, **kwargs: iter(["stub response"]),
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
    content = last["messages"][-1]["content"]
    assert "stub response" in content


def test_chat_allows_response_when_visual_facts_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    """Chat should still respond even if visual facts are missing for risky questions."""
    session_id = "sess_vfe_fail_closed_first_turn"

    save_session(
        session_id,
        {"history": [], "focus_question_number": "9", "interaction_count": 0},
    )
    save_question_bank(
        session_id,
        {
            "session_id": session_id,
            "subject": "math",
            "page_image_urls": [],
            "questions": {
                "9": {
                    "question_content": "如图，已知∠1=150°，∠BCD=30°，试说明AD∥BC。",
                    "visual_risk": True,
                    "warnings": [
                        "作业中有和图像有关的题目，建议生成切片以提升定位与辅导准确性。"
                    ],
                }
            },
        },
    )

    # Pretend qindex slices are ready, but no visual_facts have been cached yet.
    monkeypatch.setattr(
        "homework_agent.api._chat_stages.get_question_index",
        lambda _sid: {
            "questions": {
                "9": {
                    "pages": [{"slice_image_urls": ["https://example.com/slice.jpg"]}]
                }
            }
        },
    )
    monkeypatch.setattr(
        "homework_agent.services.llm.LLMClient.socratic_tutor_stream",
        lambda *args, **kwargs: iter(["stub response"]),
    )

    payload = {
        "history": [],
        "question": "讲讲第9题",
        "subject": "math",
        "session_id": session_id,
    }
    resp = client.post("/api/v1/chat", json=payload)
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    chat_payloads = [d for e, d in events if e == "chat" and d]
    assert chat_payloads, "expected at least one chat event"
    last = json.loads(chat_payloads[-1])
    content = last["messages"][-1]["content"]
    assert "stub response" in content
