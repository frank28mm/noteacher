from __future__ import annotations

from homework_agent.models.tool_result import ToolResult


def test_tool_result_from_legacy_success_contract_fields_present() -> None:
    raw = {
        "status": "ok",
        "urls": {"figure_url": "https://example.com/a.png"},
        "warnings": [],
    }
    tr = ToolResult.from_legacy(
        tool_name="diagram_slice",
        stage="autonomous.tool.diagram_slice",
        raw=raw,
        request_id="req1",
        session_id="sess1",
        timing_ms=12,
    )
    d = tr.to_dict(merge_raw=True)
    for k in (
        "ok",
        "tool_name",
        "stage",
        "request_id",
        "session_id",
        "timing_ms",
        "needs_review",
        "warning_codes",
        "retryable",
        "fallback_used",
        "data",
    ):
        assert k in d
    assert d["ok"] is True
    assert d["tool_name"] == "diagram_slice"


def test_tool_result_from_legacy_error_promotes_needs_review() -> None:
    raw = {"status": "error", "message": "timeout"}
    tr = ToolResult.from_legacy(
        tool_name="qindex_fetch",
        stage="autonomous.tool.qindex_fetch",
        raw=raw,
        request_id="req1",
        session_id="sess1",
        timing_ms=12,
    )
    d = tr.to_dict(merge_raw=True)
    assert d["ok"] is False
    assert d["needs_review"] is True
    assert d.get("error_type")
