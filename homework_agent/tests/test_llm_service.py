import json

import pytest

from homework_agent.services.llm import LLMClient


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]
        self.usage = None


class _FakeChatCompletions:
    def __init__(self, content: str):
        self._content = content

    def create(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, content: str):
        self.completions = _FakeChatCompletions(content)


class _FakeClient:
    def __init__(self, content: str):
        self.chat = _FakeChat(content)


def test_llm_grade_math_contract_hardening(monkeypatch: pytest.MonkeyPatch):
    """
    grade_math should:
    - parse JSON
    - drop `standard_answer`
    - drop steps for `correct`, and keep non-correct steps (up to K) for others
    """
    payload = {
        "summary": "ok",
        "questions": [
            {
                "question_number": "1",
                "verdict": "correct",
                "standard_answer": "secret",
                "math_steps": [
                    {"index": 1, "verdict": "correct"},
                    {"index": 2, "verdict": "incorrect"},
                ],
            },
            {
                "question_number": "2",
                "verdict": "incorrect",
                "standard_answer": "secret2",
                "math_steps": [
                    {"index": 1, "verdict": "correct"},
                    {"index": 2, "verdict": "incorrect", "severity": "BOGUS"},
                    {"index": 3, "verdict": "incorrect", "severity": "calculation"},
                ],
            },
        ],
        "wrong_items": [
            {
                "reason": "r",
                "standard_answer": "secret3",
                "math_steps": [
                    {"index": 1, "verdict": "incorrect", "severity": "bogus"}
                ],
            }
        ],
    }
    content = json.dumps(payload, ensure_ascii=False)

    c = LLMClient()
    monkeypatch.setattr(
        c, "_get_client", lambda provider="silicon": _FakeClient(content)
    )

    out = c.grade_math("text", provider="silicon")
    assert out.summary == "ok"
    assert len(out.questions) == 2

    # Q1 correct: no standard_answer and no steps
    q1 = out.questions[0]
    assert "standard_answer" not in q1
    assert not q1.get("math_steps")

    # Q2 incorrect: only keep first non-correct step, and normalize severity
    q2 = out.questions[1]
    assert "standard_answer" not in q2
    assert isinstance(q2.get("math_steps"), list) and len(q2["math_steps"]) == 2
    assert all((s.get("verdict") or "").lower() != "correct" for s in q2["math_steps"])
    assert q2["math_steps"][0].get("severity") == "unknown"
    assert q2["math_steps"][1].get("severity") == "calculation"

    # wrong_items standard_answer stripped
    assert out.wrong_items and "standard_answer" not in out.wrong_items[0]
    assert out.wrong_items[0].get("math_steps")[0].get("severity") == "unknown"


def test_llm_grade_math_parse_failed_returns_fallback(monkeypatch: pytest.MonkeyPatch):
    c = LLMClient()
    monkeypatch.setattr(
        c, "_get_client", lambda provider="silicon": _FakeClient("not-json")
    )
    out = c.grade_math("text", provider="silicon")
    assert out.summary == "批改结果解析失败"
    assert out.wrong_items == []
