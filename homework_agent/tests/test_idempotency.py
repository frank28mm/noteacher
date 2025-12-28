from __future__ import annotations

from fastapi.testclient import TestClient

from homework_agent.main import create_app
from homework_agent.api.session import cache_store


def _payload(subject: str) -> dict:
    return {
        "subject": subject,
        "vision_provider": "doubao",
        "images": [{"url": "https://example.com/a.jpg"}],
        "session_id": "s1",
    }


def test_grade_idempotency_conflict_returns_409(monkeypatch) -> None:
    # Avoid calling real providers: stub perform_grading to a constant response.
    from homework_agent.api import grade as grade_api
    from homework_agent.models.schemas import GradeResponse

    async def _fake_perform_grading(
        req, provider_str, *, experiment_key=None
    ):  # noqa: ARG001
        return GradeResponse(
            wrong_items=[],
            summary="ok",
            subject=req.subject,
            job_id=None,
            session_id=req.session_id or "s1",
            status="done",
            total_items=0,
            wrong_count=0,
            cross_subject_flag=False,
            warnings=[],
            vision_raw_text="",
            questions=[],
        )

    monkeypatch.setattr(grade_api, "perform_grading", _fake_perform_grading)

    # Clear idp cache
    cache_store.delete("idp:k1")
    app = create_app()
    client = TestClient(app)

    h = {"X-User-Id": "u1", "X-Idempotency-Key": "k1"}
    r1 = client.post("/api/v1/grade", json=_payload("math"), headers=h)
    assert r1.status_code == 200
    r2 = client.post("/api/v1/grade", json=_payload("english"), headers=h)
    assert r2.status_code == 409
