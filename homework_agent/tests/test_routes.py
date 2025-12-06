from fastapi.testclient import TestClient
from homework_agent.main import create_app
from homework_agent.models.schemas import VisionProvider


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
    assert data["status"] in ["processing", None]
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
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "test123"
