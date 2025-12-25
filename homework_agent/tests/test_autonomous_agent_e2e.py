import asyncio
import json
from types import SimpleNamespace

import pytest

from homework_agent.models.schemas import ImageRef, Subject
from homework_agent.services import autonomous_agent as aa


def _run(coro):
    return asyncio.run(coro)


def test_autonomous_agent_e2e_happy_path(monkeypatch):
    class _Settings:
        autonomous_agent_max_tokens = 200
        autonomous_agent_max_iterations = 1
        autonomous_agent_confidence_threshold = 0.9
        autonomous_agent_timeout_seconds = 5
        judgment_basis_min_length = 2

    monkeypatch.setattr(aa, "get_settings", lambda: _Settings)
    monkeypatch.setattr(aa, "run_opencv_pipeline", lambda ref: None)
    monkeypatch.setattr(aa, "upload_slices", lambda slices, prefix: {})

    def _fake_generate(self, prompt=None, system_prompt=None, provider=None, max_tokens=None, temperature=None):
        if system_prompt and "Planning Agent" in system_prompt:
            payload = {"thoughts": "ok", "plan": [], "action": "execute_tools"}
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
        payload = {
            "ocr_text": "Q1",
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
            session_id="s1",
            request_id="r1",
        )
    )

    assert result.status == "done"
    assert result.results
    assert result.results[0]["verdict"] == "correct"
