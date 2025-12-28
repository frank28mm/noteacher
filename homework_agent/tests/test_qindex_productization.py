from __future__ import annotations

from fastapi.testclient import TestClient

from homework_agent.main import create_app
from homework_agent.api import grade as grade_api
from homework_agent.api import chat as chat_api
from homework_agent.api import session as session_api
from homework_agent.models.schemas import GradeResponse, Subject


def _seed_qbank(session_id: str, *, subject: str, visual_risk: bool) -> None:
    bank = {
        "session_id": session_id,
        "subject": subject,
        "vision_raw_text": "mock vision",
        "page_image_urls": ["https://example.com/image.jpg"],
        "questions": {
            "1": {
                "question_number": "1",
                "question_content": "如图，回答问题" if visual_risk else "普通题目",
                "warnings": [],
                "visual_risk": bool(visual_risk),
            }
        },
    }
    session_api.save_question_bank(session_id, bank)


def test_grade_records_qindex_skipped_when_redis_unavailable(monkeypatch):
    app = create_app()
    client = TestClient(app)
    session_id = "sess_qindex_skip_redis"

    async def fake_perform_grading(
        req, provider_str, *, experiment_key=None
    ):  # noqa: ARG001
        _seed_qbank(session_id, subject=req.subject.value, visual_risk=True)
        return GradeResponse(
            wrong_items=[],
            summary="ok",
            subject=req.subject,
            job_id=None,
            session_id=session_id,
            status="done",
            total_items=1,
            wrong_count=0,
            cross_subject_flag=None,
            warnings=[],
            vision_raw_text="mock vision",
        )

    monkeypatch.setattr(grade_api, "perform_grading", fake_perform_grading)
    monkeypatch.setattr(grade_api, "enqueue_qindex_job", lambda *a, **k: False)
    monkeypatch.setattr(
        grade_api,
        "qindex_is_configured",
        lambda: (True, "ok (OCR_PROVIDER=siliconflow_qwen3_vl)"),
    )

    resp = client.post(
        "/api/v1/grade",
        json={
            "subject": "math",
            "images": [{"url": "https://example.com/image.jpg"}],
            "session_id": session_id,
            "vision_provider": "qwen3",
        },
    )
    assert resp.status_code == 200
    qindex = session_api.get_question_index(session_id)
    assert isinstance(qindex, dict)
    assert any("redis_unavailable" in str(w) for w in (qindex.get("warnings") or []))


def test_grade_records_qindex_skipped_when_ocr_disabled(monkeypatch):
    app = create_app()
    client = TestClient(app)
    session_id = "sess_qindex_skip_ocr"

    async def fake_perform_grading(
        req, provider_str, *, experiment_key=None
    ):  # noqa: ARG001
        _seed_qbank(session_id, subject=req.subject.value, visual_risk=True)
        return GradeResponse(
            wrong_items=[],
            summary="ok",
            subject=req.subject,
            job_id=None,
            session_id=session_id,
            status="done",
            total_items=1,
            wrong_count=0,
            cross_subject_flag=None,
            warnings=[],
            vision_raw_text="mock vision",
        )

    monkeypatch.setattr(grade_api, "perform_grading", fake_perform_grading)
    monkeypatch.setattr(
        grade_api,
        "qindex_is_configured",
        lambda: (False, "ocr_disabled (OCR_PROVIDER=disabled)"),
    )

    resp = client.post(
        "/api/v1/grade",
        json={
            "subject": "english",
            "images": [{"url": "https://example.com/image.jpg"}],
            "session_id": session_id,
            "vision_provider": "qwen3",
        },
    )
    assert resp.status_code == 200
    qindex = session_api.get_question_index(session_id)
    assert isinstance(qindex, dict)
    assert any("ocr_disabled" in str(w) for w in (qindex.get("warnings") or []))


def test_chat_records_qindex_skipped_when_redis_unavailable(monkeypatch):
    app = create_app()
    client = TestClient(app)
    session_id = "sess_chat_qindex_skip"

    _seed_qbank(session_id, subject=Subject.MATH.value, visual_risk=True)

    # Avoid real provider calls during tests.
    monkeypatch.setattr(chat_api, "enqueue_qindex_job", lambda *a, **k: False)
    monkeypatch.setattr(
        chat_api,
        "qindex_is_configured",
        lambda: (True, "ok (OCR_PROVIDER=siliconflow_qwen3_vl)"),
    )

    def fake_stream(self, **kwargs):  # noqa: ARG001
        yield "你好"

    monkeypatch.setattr(chat_api.LLMClient, "socratic_tutor_stream", fake_stream)

    resp = client.post(
        "/api/v1/chat",
        json={
            "history": [],
            "question": "讲讲第1题",
            "subject": "math",
            "session_id": session_id,
            "mode": "normal",
            "context_item_ids": [],
        },
    )
    assert resp.status_code == 200
    qindex = session_api.get_question_index(session_id)
    assert isinstance(qindex, dict)
    assert any("redis_unavailable" in str(w) for w in (qindex.get("warnings") or []))
