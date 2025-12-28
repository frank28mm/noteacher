import asyncio
import json
import time
from types import SimpleNamespace


from homework_agent.services.session_state import SessionState
from homework_agent.services.autonomous_agent import (
    PlannerAgent,
    ReflectorAgent,
    ExecutorAgent,
    AggregatorAgent,
)
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
        slice_failed_cache={"hash1": True},
        attempted_tools={
            "diagram_slice": {"status": "error", "reason": "roi_not_found"}
        },
        preprocess_meta={"figure_too_small": True},
    )
    data = state.to_dict()
    restored = SessionState.from_dict(data)
    assert restored.session_id == "s1"
    assert restored.slice_urls["figure"] == ["f1"]
    assert restored.ocr_text == "ocr"
    assert restored.slice_failed_cache == {"hash1": True}
    assert restored.attempted_tools["diagram_slice"]["status"] == "error"
    assert restored.preprocess_meta["figure_too_small"] is True


def test_math_verify_allows_simple_expression():
    result = math_verify(expression="2+3")
    assert result["status"] == "ok"
    assert result["result"] in {"5", "5.0"}


def test_math_verify_rejects_forbidden():
    result = math_verify(expression="__import__('os')")
    assert result["status"] == "error"


def test_planner_parses_json(monkeypatch):
    payload = {
        "thoughts": "t",
        "plan": [{"step": "ocr_fallback", "args": {"image": "u"}}],
        "action": "execute_tools",
    }

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
    planner = PlannerAgent(
        llm=LLMClient(), provider="ark", max_tokens=200, timeout_s=0.01
    )
    state = SessionState(session_id="s", image_urls=["u"])
    result = _run(planner.run(state))
    assert result.action == "execute_tools"
    assert result.thoughts in {"planner_llm_failed", "budget_exhausted_before_planner"}


def test_reflector_parse_failure(monkeypatch):
    def _fake_generate(*args, **kwargs):
        return SimpleNamespace(text="not-json")

    monkeypatch.setattr(LLMClient, "generate", _fake_generate)
    reflector = ReflectorAgent(
        llm=LLMClient(), provider="ark", max_tokens=200, timeout_s=5
    )
    state = SessionState(session_id="s", image_urls=["u"])
    result = _run(reflector.run(state, plan=[]))
    assert result.pass_ is False


def test_executor_updates_slice_urls(monkeypatch):
    from homework_agent.services import autonomous_agent as aa

    def _fake_diagram_slice(*, image: str, prefix: str):
        return {
            "status": "ok",
            "urls": {"figure_url": "f", "question_url": "q"},
            "warnings": [],
        }

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
    agg = AggregatorAgent(
        llm=LLMClient(),
        provider="ark",
        subject=Subject.MATH,
        max_tokens=200,
        timeout_s=5,
    )
    result = _run(agg.run(state))
    assert result.status == "failed"
    assert result.reason == "parse_failed"


def test_planner_forced_strategy_on_diagram_roi_not_found(monkeypatch):

    payload = {
        "thoughts": "t",
        "plan": [{"step": "diagram_slice", "args": {"image": "u"}}],
        "action": "execute_tools",
    }

    def _fake_generate(*args, **kwargs):
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(LLMClient, "generate", _fake_generate)
    planner = PlannerAgent(llm=LLMClient(), provider="ark", max_tokens=200, timeout_s=5)
    state = SessionState(
        session_id="s",
        image_urls=["u"],
        partial_results={
            "reflection": {
                "issues": ["diagram_roi_not_found"],
                "pass": False,
                "confidence": 0.6,
            }
        },
    )
    result = _run(planner.run(state))
    steps = [step.get("step") for step in result.plan]
    assert "diagram_slice" not in steps
    assert steps[:2] == ["qindex_fetch", "vision_roi_detect"]
    assert "ocr_fallback" in steps


def test_planner_respects_slice_failed_cache(monkeypatch):
    payload = {
        "thoughts": "t",
        "plan": [{"step": "diagram_slice", "args": {"image": "u"}}],
        "action": "execute_tools",
    }

    def _fake_generate(*args, **kwargs):
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(LLMClient, "generate", _fake_generate)
    monkeypatch.setattr(
        "homework_agent.services.autonomous_agent._compute_image_hash",
        lambda *_: "hash",
    )
    planner = PlannerAgent(llm=LLMClient(), provider="ark", max_tokens=200, timeout_s=5)
    state = SessionState(
        session_id="s",
        image_urls=["u"],
        slice_failed_cache={"hash": True},
    )
    result = _run(planner.run(state))
    steps = [step.get("step") for step in result.plan]
    assert "diagram_slice" not in steps
    assert "qindex_fetch" in steps


def test_executor_records_attempted_tools(monkeypatch):
    from homework_agent.services import autonomous_agent as aa

    def _fake_diagram_slice(*, image: str, prefix: str):
        return {"status": "ok", "urls": {"figure_url": "f"}, "warnings": []}

    monkeypatch.setattr(aa, "diagram_slice", _fake_diagram_slice)
    state = SessionState(session_id="s", image_urls=["u"])
    executor = ExecutorAgent(provider="ark", session_id="s")
    _run(executor.run(state, plan=[{"step": "diagram_slice", "args": {"image": "u"}}]))
    assert state.attempted_tools["diagram_slice"]["status"] == "ok"


def test_executor_vision_roi_detect_success(monkeypatch):
    from homework_agent.services import autonomous_agent as aa

    def _fake_vision_roi_detect(*, image: str, prefix: str):
        return {
            "status": "ok",
            "regions": [
                {
                    "kind": "figure",
                    "bbox_norm_xyxy": [0.1, 0.1, 0.2, 0.2],
                    "slice_url": "fig",
                },
                {
                    "kind": "question",
                    "bbox_norm_xyxy": [0.2, 0.2, 0.3, 0.3],
                    "slice_url": "q",
                },
            ],
            "warning": None,
        }

    monkeypatch.setattr(aa, "vision_roi_detect", _fake_vision_roi_detect)
    state = SessionState(session_id="s", image_urls=["u"])
    executor = ExecutorAgent(provider="ark", session_id="s")
    _run(
        executor.run(
            state,
            plan=[{"step": "vision_roi_detect", "args": {"image": "u", "prefix": "p"}}],
        )
    )
    assert "fig" in state.slice_urls["figure"]
    assert "q" in state.slice_urls["question"]
    assert state.attempted_tools["vision_roi_detect"]["status"] == "ok"


def test_reflector_assessment_only_no_boost(monkeypatch):
    def _fake_generate(*args, **kwargs):
        payload = {"pass": False, "issues": [], "confidence": 0.65, "suggestion": ""}
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(LLMClient, "generate", _fake_generate)
    reflector = ReflectorAgent(
        llm=LLMClient(), provider="ark", max_tokens=200, timeout_s=5
    )
    state = SessionState(
        session_id="s",
        image_urls=["u"],
        tool_results={
            "diagram_slice": {"status": "error", "message": "diagram_roi_not_found"}
        },
    )
    result = _run(reflector.run(state, plan=[]))
    assert result.pass_ is False
    assert result.confidence == 0.65
    assert "diagram_roi_not_found" in result.issues


def test_aggregator_fallback_to_original_when_no_figure(monkeypatch):
    from homework_agent.services import autonomous_agent as aa

    captured = {}

    def _fake_generate_with_images(self, **kwargs):
        captured["images"] = kwargs.get("images") or []
        payload = {
            "ocr_text": "ocr",
            "results": [
                {
                    "question_number": "1",
                    "verdict": "correct",
                    "question_content": "1+1",
                    "student_answer": "2",
                    "reason": "正确",
                    "judgment_basis": [
                        "依据来源：题干",
                        "观察：...",
                        "规则：...",
                        "结论：...",
                    ],
                    "warnings": [],
                }
            ],
            "summary": "done",
            "warnings": [],
        }
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(
        aa, "_compress_image_if_needed", lambda url, max_side=1280: f"compressed:{url}"
    )
    monkeypatch.setattr(
        LLMClient, "generate_with_images", _fake_generate_with_images, raising=False
    )
    state = SessionState(
        session_id="s",
        image_urls=["http://example.com/original.jpg"],
        slice_urls={"figure": [], "question": []},
    )
    agg = AggregatorAgent(
        llm=LLMClient(),
        provider="ark",
        subject=Subject.MATH,
        max_tokens=200,
        timeout_s=5,
    )
    result = _run(agg.run(state))
    assert result.results
    assert len(captured["images"]) == 1
    assert (
        str(captured["images"][0].url) == "compressed:http://example.com/original.jpg"
    )


def test_aggregator_fallback_to_original_when_figure_too_small(monkeypatch):
    from homework_agent.services import autonomous_agent as aa

    captured = {}

    def _fake_generate_with_images(self, **kwargs):
        captured["images"] = kwargs.get("images") or []
        payload = {
            "ocr_text": "ocr",
            "results": [
                {
                    "question_number": "1",
                    "verdict": "correct",
                    "question_content": "1+1",
                    "student_answer": "2",
                    "reason": "正确",
                    "judgment_basis": [
                        "依据来源：题干",
                        "观察：...",
                        "规则：...",
                        "结论：...",
                    ],
                    "warnings": [],
                }
            ],
            "summary": "done",
            "warnings": [],
        }
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(
        aa, "_compress_image_if_needed", lambda url, max_side=1280: f"compressed:{url}"
    )
    monkeypatch.setattr(
        LLMClient, "generate_with_images", _fake_generate_with_images, raising=False
    )
    state = SessionState(
        session_id="s",
        image_urls=["http://example.com/original.jpg"],
        slice_urls={"figure": ["fig"], "question": ["q"]},
        preprocess_meta={"figure_too_small": True},
    )
    agg = AggregatorAgent(
        llm=LLMClient(),
        provider="ark",
        subject=Subject.MATH,
        max_tokens=200,
        timeout_s=5,
    )
    result = _run(agg.run(state))
    assert result.results
    assert len(captured["images"]) == 1
    assert (
        str(captured["images"][0].url) == "compressed:http://example.com/original.jpg"
    )
