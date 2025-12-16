from fastapi.testclient import TestClient
from homework_agent.main import create_app
from homework_agent.models.schemas import VisionProvider
from homework_agent.api import routes
from homework_agent.api.routes import resolve_context_items, normalize_context_ids, assistant_tail


client = TestClient(create_app())


def test_grade_stub():
    payload = {
        "images": [{"url": "https://example.com/image.jpg"}],
        "subject": "math",
        "vision_provider": VisionProvider.QWEN3.value,
    }
    resp = client.post("/api/v1/grade", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ["processing", "failed", "done", None]
    assert "warnings" in data


def test_chat_stub_sse():
    payload = {
        "history": [],
        "question": "why?",
        "subject": "math",
        "session_id": "sess-1",
    }
    resp = client.post("/api/v1/chat", json=payload)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")


def test_job_stub():
    resp = client.get("/api/v1/jobs/test123")
    assert resp.status_code in (200, 404)


def test_job_status_with_cache():
    job_id = "job_test"
    routes.cache_store.set(
        f"job:{job_id}",
        {"status": "done", "result": {"summary": "ok"}},
        ttl_seconds=60,
    )
    resp = client.get(f"/api/v1/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


def test_resolve_context_items_supports_item_id_and_index():
    session_id = "sess_ctx"
    wrong_items = [
        {"item_id": "w1", "reason": "r1"},
        {"item_id": "w2", "reason": "r2"},
    ]
    routes.save_mistakes(session_id, wrong_items)
    cached = routes.get_mistakes(session_id)

    ctx_ids = normalize_context_ids(["w1", 1, "missing"])
    selected, missing = resolve_context_items(ctx_ids, cached)
    assert len(selected) == 2
    assert any(item.get("item_id") == "w1" for item in selected)
    assert any(item.get("id") == 1 for item in selected)
    assert "missing" in missing


def test_assistant_tail_replays_last_messages_in_order():
    history = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "assistant", "content": "a2"},
        {"role": "assistant", "content": "a3"},
        {"role": "assistant", "content": "a4"},
    ]
    tail = assistant_tail(history, max_messages=3)
    assert [m["content"] for m in tail] == ["a2", "a3", "a4"]


def test_upload_route_exists_validation_error_without_file():
    resp = client.post("/api/v1/uploads")
    assert resp.status_code == 422
