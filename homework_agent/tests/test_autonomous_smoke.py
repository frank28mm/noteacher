"""
Smoke test for Autonomous Agent with relaxed timeout validation.

This test verifies the core Loop flow can complete successfully with
relaxed timeout settings (>=300s) as specified in implementation_plan.md.
"""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from homework_agent.models.schemas import ImageRef, Subject
from homework_agent.services import autonomous_agent as aa
from homework_agent.services.session_state import SessionState


def _run(coro):
    return asyncio.run(coro)


def test_autonomous_agent_smoke_full_loop(monkeypatch):
    """
    Smoke test: Verify full Loop (Plan → Execute → Reflect → Aggregate) completes.

    Settings: max_iterations=1, timeout=5s, max_tokens=200
    This is a minimal "happy path" test to ensure the pipeline runs end-to-end.
    """
    class _Settings:
        autonomous_agent_max_tokens = 200
        autonomous_agent_max_iterations = 1
        autonomous_agent_confidence_threshold = 0.9
        autonomous_agent_timeout_seconds = 5
        judgment_basis_min_length = 2

    monkeypatch.setattr(aa, "get_settings", lambda: _Settings)
    monkeypatch.setattr(aa, "run_opencv_pipeline", lambda ref: None)
    monkeypatch.setattr(aa, "upload_slices", lambda slices, prefix: {})

    # Track LLM calls for verification
    calls = {"planner": 0, "reflector": 0, "aggregator": 0}

    def _fake_generate(self, prompt=None, system_prompt=None, provider=None, max_tokens=None, temperature=None):
        if system_prompt and "Planning Agent" in system_prompt:
            calls["planner"] += 1
            payload = {"thoughts": "Simple problem, no tools needed", "plan": [], "action": "execute_tools"}
        elif system_prompt and "Reflector Agent" in system_prompt:
            calls["reflector"] += 1
            payload = {"pass": True, "issues": [], "confidence": 0.95, "suggestion": ""}
        else:
            payload = {"pass": True, "issues": [], "confidence": 0.95, "suggestion": ""}
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    def _fake_generate_with_images(
        self,
        system_prompt=None,
        user_prompt=None,
        images=None,
        provider=None,
        max_tokens=None,
        temperature=None,
        use_tools=False,
    ):
        calls["aggregator"] += 1
        payload = {
            "ocr_text": "1+1=2",
            "results": [
                {
                    "question_number": "1",
                    "verdict": "correct",
                    "question_content": "1+1",
                    "student_answer": "2",
                    "reason": "正确",
                    "judgment_basis": [
                        "依据来源：题干",
                        "观察：题目为1+1，学生答2",
                        "规则：1+1=2",
                        "结论：答案正确",
                    ],
                    "warnings": [],
                }
            ],
            "summary": "第1题：正确",
            "warnings": [],
        }
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(aa.LLMClient, "generate", _fake_generate, raising=False)
    monkeypatch.setattr(aa.LLMClient, "generate_with_images", _fake_generate_with_images, raising=False)

    start = time.monotonic()
    result = _run(
        aa.run_autonomous_grade_agent(
            images=[ImageRef(url="http://example.com/image.jpg")],
            subject=Subject.MATH,
            provider="ark",
            session_id="smoke_test",
            request_id="smoke_req",
        )
    )
    elapsed = time.monotonic() - start

    # Verify outcome
    assert result.status == "done"
    assert result.results
    assert len(result.results) == 1
    assert result.results[0]["verdict"] == "correct"
    assert result.iterations == 1

    # Verify each agent was called exactly once
    assert calls["planner"] == 1, f"Planner called {calls['planner']} times, expected 1"
    assert calls["reflector"] == 1, f"Reflector called {calls['reflector']} times, expected 1"
    assert calls["aggregator"] == 1, f"Aggregator called {calls['aggregator']} times, expected 1"

    # Smoke test should complete quickly
    assert elapsed < 2.0, f"Smoke test took {elapsed:.2f}s, expected < 2s"


def test_autonomous_agent_loop_exit_by_confidence(monkeypatch):
    """
    Test Loop exits when reflection.pass=true AND confidence >= 0.90.

    Verifies the normal exit condition without hitting max_iterations.
    """
    class _Settings:
        autonomous_agent_max_tokens = 200
        autonomous_agent_max_iterations = 3
        autonomous_agent_confidence_threshold = 0.90
        autonomous_agent_timeout_seconds = 5
        judgment_basis_min_length = 2

    monkeypatch.setattr(aa, "get_settings", lambda: _Settings)
    monkeypatch.setattr(aa, "run_opencv_pipeline", lambda ref: None)
    monkeypatch.setattr(aa, "upload_slices", lambda slices, prefix: {})

    iteration_count = {"n": 0}

    def _fake_generate(self, prompt=None, system_prompt=None, provider=None, max_tokens=None, temperature=None):
        if system_prompt and "Planning Agent" in system_prompt:
            payload = {"thoughts": "ok", "plan": [], "action": "execute_tools"}
        elif system_prompt and "Reflector Agent" in system_prompt:
            iteration_count["n"] += 1
            # First iteration: high confidence, should exit
            payload = {"pass": True, "issues": [], "confidence": 0.92, "suggestion": ""}
        else:
            payload = {"pass": True, "issues": [], "confidence": 0.95, "suggestion": ""}
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    def _fake_generate_with_images(self, **kwargs):
        payload = {
            "ocr_text": "test",
            "results": [{"question_number": "1", "verdict": "correct", "question_content": "t", "student_answer": "t", "reason": "ok", "judgment_basis": ["依据来源：题干", "观察：...", "规则：...", "结论：..."], "warnings": []}],
            "summary": "done",
            "warnings": [],
        }
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(aa.LLMClient, "generate", _fake_generate, raising=False)
    monkeypatch.setattr(aa.LLMClient, "generate_with_images", _fake_generate_with_images, raising=False)

    result = _run(
        aa.run_autonomous_grade_agent(
            images=[ImageRef(url="http://example.com/image.jpg")],
            subject=Subject.MATH,
            provider="ark",
            session_id="exit_test",
            request_id="exit_req",
        )
    )

    assert result.status == "done"
    assert result.iterations == 1, f"Expected 1 iteration, got {result.iterations}"
    assert iteration_count["n"] == 1


def test_autonomous_agent_loop_exit_by_max_iterations(monkeypatch):
    """
    Test Loop exits when max_iterations is reached (forced exit + warning).

    Verifies the safety exit condition when confidence never reaches threshold.
    """
    class _Settings:
        autonomous_agent_max_tokens = 200
        autonomous_agent_max_iterations = 2
        autonomous_agent_confidence_threshold = 0.90
        autonomous_agent_timeout_seconds = 5
        judgment_basis_min_length = 2

    monkeypatch.setattr(aa, "get_settings", lambda: _Settings)
    monkeypatch.setattr(aa, "run_opencv_pipeline", lambda ref: None)
    monkeypatch.setattr(aa, "upload_slices", lambda slices, prefix: {})

    iteration_count = {"n": 0}

    def _fake_generate(self, prompt=None, system_prompt=None, provider=None, max_tokens=None, temperature=None):
        if system_prompt and "Planning Agent" in system_prompt:
            payload = {"thoughts": "ok", "plan": [], "action": "execute_tools"}
        elif system_prompt and "Reflector Agent" in system_prompt:
            iteration_count["n"] += 1
            # Always return low confidence, forcing max_iterations exit
            payload = {"pass": False, "issues": ["Insufficient evidence"], "confidence": 0.70, "suggestion": "retry"}
        else:
            payload = {"pass": True, "issues": [], "confidence": 0.95, "suggestion": ""}
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    def _fake_generate_with_images(self, **kwargs):
        payload = {
            "ocr_text": "test",
            "results": [{"question_number": "1", "verdict": "correct", "question_content": "t", "student_answer": "t", "reason": "ok", "judgment_basis": ["依据来源：题干", "观察：...", "规则：...", "结论：..."], "warnings": []}],
            "summary": "done",
            "warnings": [],
        }
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(aa.LLMClient, "generate", _fake_generate, raising=False)
    monkeypatch.setattr(aa.LLMClient, "generate_with_images", _fake_generate_with_images, raising=False)

    result = _run(
        aa.run_autonomous_grade_agent(
            images=[ImageRef(url="http://example.com/image.jpg")],
            subject=Subject.MATH,
            provider="ark",
            session_id="max_iter_test",
            request_id="max_iter_req",
        )
    )

    assert result.status == "done"
    assert result.iterations == 2, f"Expected 2 iterations (max), got {result.iterations}"
    assert iteration_count["n"] == 2
    # Should have warning about hitting max iterations
    assert any("max iterations" in str(w).lower() for w in result.warnings or []), \
        f"Expected max iterations warning, got: {result.warnings}"


def test_autonomous_agent_reflection_replan(monkeypatch):
    """
    Test Reflector triggers re-planning when pass=false.

    Verifies Planner receives reflection_result for next iteration.
    """
    class _Settings:
        autonomous_agent_max_tokens = 200
        autonomous_agent_max_iterations = 2
        autonomous_agent_confidence_threshold = 0.90
        autonomous_agent_timeout_seconds = 5
        judgment_basis_min_length = 2

    monkeypatch.setattr(aa, "get_settings", lambda: _Settings)
    monkeypatch.setattr(aa, "run_opencv_pipeline", lambda ref: None)
    monkeypatch.setattr(aa, "upload_slices", lambda slices, prefix: {})

    planner_inputs = []

    def _fake_generate(self, prompt=None, system_prompt=None, provider=None, max_tokens=None, temperature=None):
        if system_prompt and "Planning Agent" in system_prompt:
            # Capture prompt to verify reflection_result is included
            planner_inputs.append(prompt)
            payload = {"thoughts": "ok", "plan": [], "action": "execute_tools"}
        elif system_prompt and "Reflector Agent" in system_prompt:
            # First iteration: fail to trigger re-plan
            if len(planner_inputs) == 1:
                payload = {"pass": False, "issues": ["Need more evidence"], "confidence": 0.70, "suggestion": "Run ocr_fallback"}
            else:
                # Second iteration: pass
                payload = {"pass": True, "issues": [], "confidence": 0.95, "suggestion": ""}
        else:
            payload = {"pass": True, "issues": [], "confidence": 0.95, "suggestion": ""}
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    def _fake_generate_with_images(self, **kwargs):
        payload = {
            "ocr_text": "test",
            "results": [{"question_number": "1", "verdict": "correct", "question_content": "t", "student_answer": "t", "reason": "ok", "judgment_basis": ["依据来源：题干", "观察：...", "规则：...", "结论：..."], "warnings": []}],
            "summary": "done",
            "warnings": [],
        }
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(aa.LLMClient, "generate", _fake_generate, raising=False)
    monkeypatch.setattr(aa.LLMClient, "generate_with_images", _fake_generate_with_images, raising=False)

    result = _run(
        aa.run_autonomous_grade_agent(
            images=[ImageRef(url="http://example.com/image.jpg")],
            subject=Subject.MATH,
            provider="ark",
            session_id="replan_test",
            request_id="replan_req",
        )
    )

    assert result.status == "done"
    assert result.iterations == 2, f"Expected 2 iterations for re-plan, got {result.iterations}"

    # Verify second planner input includes reflection_result
    assert len(planner_inputs) == 2
    second_prompt = planner_inputs[1]
    assert "reflection_result" in second_prompt or "issues" in second_prompt, \
        "Second Planner call should include reflection_result"
