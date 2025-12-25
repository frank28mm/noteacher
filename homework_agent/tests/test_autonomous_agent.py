import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from homework_agent.services.session_state import SessionState
from homework_agent.services.autonomous_agent import PlannerAgent, ReflectorAgent, ExecutorAgent, AggregatorAgent
from homework_agent.models.schemas import Subject
from homework_agent.services.autonomous_tools import math_verify
from homework_agent.services.llm import LLMClient


def _run(coro):
    return asyncio.run(coro)


def test_session_state_roundtrip():
    state = SessionState(
        session_id="s1",
        image_urls=["u1"],
        slice_urls={"figure": ["f1"], "question": ["q1"]},
        ocr_text="ocr",
        plan_history=[{"plan": []}],
        tool_results={"x": 1},
        reflection_count=1,
        partial_results={"r": "ok"},
        warnings=["w"],
    )
    data = state.to_dict()
    restored = SessionState.from_dict(data)
    assert restored.session_id == "s1"
    assert restored.slice_urls["figure"] == ["f1"]
    assert restored.ocr_text == "ocr"


def test_math_verify_allows_simple_expression():
    result = math_verify(expression="2+3")
    assert result["status"] == "ok"
    assert result["result"] in {"5", "5.0"}


def test_math_verify_rejects_forbidden():
    result = math_verify(expression="__import__('os')")
    assert result["status"] == "error"


def test_planner_parses_json(monkeypatch):
    payload = {"thoughts": "t", "plan": [{"step": "ocr_fallback", "args": {"image": "u"}}], "action": "execute_tools"}

    def _fake_generate(*args, **kwargs):
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(LLMClient, "generate", _fake_generate)
    planner = PlannerAgent(llm=LLMClient(), provider="ark", max_tokens=200, timeout_s=5)
    state = SessionState(session_id="s", image_urls=["u"])
    result = _run(planner.run(state))
    assert result.plan
    assert result.plan[0]["step"] == "ocr_fallback"


def test_planner_rate_limit_backoff(monkeypatch):
    payload = {"thoughts": "t", "plan": [], "action": "execute_tools"}
    calls = {"n": 0}

    def _fake_generate(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("429 rate limit")
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(LLMClient, "generate", _fake_generate)
    planner = PlannerAgent(llm=LLMClient(), provider="ark", max_tokens=200, timeout_s=5)
    state = SessionState(session_id="s", image_urls=["u"])
    result = _run(planner.run(state))
    assert result.action == "execute_tools"
    assert calls["n"] == 2


def test_planner_timeout(monkeypatch):
    payload = {"thoughts": "t", "plan": [], "action": "execute_tools"}

    def _fake_generate(*args, **kwargs):
        time.sleep(0.2)
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(LLMClient, "generate", _fake_generate)
    planner = PlannerAgent(llm=LLMClient(), provider="ark", max_tokens=200, timeout_s=0.01)
    state = SessionState(session_id="s", image_urls=["u"])
    with pytest.raises(asyncio.TimeoutError):
        _run(planner.run(state))


def test_reflector_parse_failure(monkeypatch):
    def _fake_generate(*args, **kwargs):
        return SimpleNamespace(text="not-json")

    monkeypatch.setattr(LLMClient, "generate", _fake_generate)
    reflector = ReflectorAgent(llm=LLMClient(), provider="ark", max_tokens=200, timeout_s=5)
    state = SessionState(session_id="s", image_urls=["u"])
    result = _run(reflector.run(state, plan=[]))
    assert result.pass_ is False


def test_executor_updates_slice_urls(monkeypatch):
    from homework_agent.services import autonomous_agent as aa

    def _fake_diagram_slice(*, image: str, prefix: str):
        return {"status": "ok", "urls": {"figure_url": "f", "question_url": "q"}, "warnings": []}

    monkeypatch.setattr(aa, "diagram_slice", _fake_diagram_slice)
    state = SessionState(session_id="s", image_urls=["u"])
    executor = ExecutorAgent(provider="ark", session_id="s")
    _run(executor.run(state, plan=[{"step": "diagram_slice", "args": {"image": "u"}}]))
    assert state.slice_urls["figure"] == ["f"]
    assert state.slice_urls["question"] == ["q"]


def test_executor_fallbacks_to_ocr(monkeypatch):
    from homework_agent.services import autonomous_agent as aa

    def _fake_diagram_slice(*, image: str, prefix: str):
        return {"status": "error", "message": "slice_failed"}

    def _fake_ocr_fallback(*, image: str, provider: str):
        return {"status": "ok", "text": "ocr"}

    monkeypatch.setattr(aa, "diagram_slice", _fake_diagram_slice)
    monkeypatch.setattr(aa, "ocr_fallback", _fake_ocr_fallback)
    state = SessionState(session_id="s", image_urls=["u"])
    executor = ExecutorAgent(provider="ark", session_id="s")
    _run(executor.run(state, plan=[{"step": "diagram_slice", "args": {"image": "u"}}]))
    assert "diagram_slice_failed_fallback_ocr" in state.warnings
    assert state.ocr_text == "ocr"


def test_aggregator_parse_failure(monkeypatch):
    def _fake_generate_with_images(*args, **kwargs):
        return SimpleNamespace(text="not-json")

    monkeypatch.setattr(LLMClient, "generate_with_images", _fake_generate_with_images)
    state = SessionState(
        session_id="s",
        image_urls=["http://example.com/image.jpg"],
        slice_urls={"figure": [], "question": []},
    )
    agg = AggregatorAgent(llm=LLMClient(), provider="ark", subject=Subject.MATH, max_tokens=200, timeout_s=5)
    result = _run(agg.run(state))
    assert result.status == "failed"
    assert result.reason == "parse_failed"
