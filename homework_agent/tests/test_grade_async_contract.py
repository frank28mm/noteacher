from fastapi.testclient import TestClient

from homework_agent.main import create_app

client = TestClient(create_app())


def test_grade_large_batch_returns_202(monkeypatch):
    async def _noop_background_grade(job_id, req, provider_str):  # noqa: ARG001
        return None

    monkeypatch.setattr(
        "homework_agent.api.grade.background_grade",
        _noop_background_grade,
    )

    payload = {
        "images": [{"url": f"https://example.com/img_{i}.jpg"} for i in range(4)],
        "subject": "math",
        "session_id": "sess_large_batch_001",
        "vision_provider": "qwen3",
    }
    resp = client.post("/api/v1/grade", json=payload, headers={"X-User-Id": "u1"})
    assert resp.status_code == 202
    data = resp.json()
    assert data.get("status") == "processing"
    assert data.get("job_id")
