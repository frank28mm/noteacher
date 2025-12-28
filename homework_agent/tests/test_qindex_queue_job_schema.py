from homework_agent.services.qindex_queue import QIndexJob


def test_qindex_job_serializes_request_id_roundtrip():
    job = QIndexJob(
        session_id="sess_1",
        request_id="req_123",
        page_urls=["https://example.com/a.jpg"],
        question_numbers=["1", "2"],
        enqueued_at=123.0,
    )
    raw = job.to_json()
    parsed = QIndexJob.from_json(raw)
    assert parsed.session_id == "sess_1"
    assert parsed.request_id == "req_123"
    assert parsed.page_urls == ["https://example.com/a.jpg"]
    assert parsed.question_numbers == ["1", "2"]


def test_qindex_job_parses_missing_request_id_as_none():
    raw = QIndexJob(
        session_id="sess_1",
        request_id=None,
        page_urls=["https://example.com/a.jpg"],
        question_numbers=[],
        enqueued_at=123.0,
    ).to_json()
    parsed = QIndexJob.from_json(raw)
    assert parsed.request_id is None
