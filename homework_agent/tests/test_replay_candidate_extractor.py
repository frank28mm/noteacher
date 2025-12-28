from __future__ import annotations

import json

from homework_agent.evals.replay_candidate_extractor import extract_replay_candidates


def test_extract_replay_candidates_groups_by_request_id_and_filters_needs_review() -> (
    None
):
    lines = [
        json.dumps(
            {
                "event": "autonomous_grade_start",
                "request_id": "req_1",
                "session_id": "sess_1",
                "subject": "math",
            }
        ),
        json.dumps(
            {
                "event": "run_versions",
                "request_id": "req_1",
                "session_id": "sess_1",
                "prompt_id": "autonomous",
                "prompt_version": "autonomous_v1",
                "provider": "ark",
                "model": "doubao",
            }
        ),
        json.dumps(
            {
                "event": "agent_finalize_done",
                "request_id": "req_1",
                "session_id": "sess_1",
                "needs_review": True,
                "warning_codes": [
                    "diagram_roi_not_found",
                    "pii_detected",
                    "diagram_roi_not_found",
                ],
                "image_url": "https://example.com/a.png?access_token=abc",
            }
        ),
        json.dumps(
            {
                "event": "agent_finalize_done",
                "request_id": "req_2",
                "session_id": "sess_2",
                "needs_review": False,
            }
        ),
    ]

    cands = extract_replay_candidates(lines)
    assert len(cands) == 1
    c = cands[0]
    assert c.request_id == "req_1"
    assert c.session_id == "sess_1"
    assert c.subject == "math"
    assert c.needs_review is True
    assert "diagram_roi_not_found" in c.warning_codes
    assert "pii_detected" in c.warning_codes
    assert c.prompt_id == "autonomous"
    assert c.prompt_version == "autonomous_v1"


def test_extract_replay_candidates_accepts_warning_codes_without_needs_review_flag() -> (
    None
):
    lines = [
        json.dumps(
            {
                "event": "agent_tool_done",
                "request_id": "req_x",
                "session_id": "sess_x",
                "warning_codes": ["tool_error:diagram_slice"],
            }
        )
    ]
    cands = extract_replay_candidates(lines)
    assert len(cands) == 1
    assert cands[0].request_id == "req_x"
