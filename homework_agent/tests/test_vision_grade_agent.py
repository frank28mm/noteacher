import asyncio

import pytest

from homework_agent.models.schemas import ImageRef, Subject
from homework_agent.services import vision_grade_agent as vga
from homework_agent.utils.settings import get_settings


class _DummyLLMResult:
    def __init__(self, text: str):
        self.text = text


def _clear_settings_cache():
    try:
        get_settings.cache_clear()
    except Exception:
        pass


def test_parse_unified_json_with_repair():
    raw = '{"ocr_text":"ok","results":[],"summary":"done","warnings":[]'
    parsed = vga._parse_unified_json(raw)
    assert parsed is not None
    assert parsed.summary == "done"


@pytest.mark.asyncio
async def test_unified_grade_rejects(monkeypatch):
    _clear_settings_cache()
    payload = '{"status":"rejected","reason":"not_homework"}'

    def _fake_generate_with_images(**kwargs):
        return _DummyLLMResult(payload)

    def _fake_prepare_image_inputs(**kwargs):
        return ([ImageRef(url="https://example.com/a.jpg")], [])

    monkeypatch.setattr(vga.LLMClient, "generate_with_images", _fake_generate_with_images)
    monkeypatch.setattr(vga, "_prepare_image_inputs", _fake_prepare_image_inputs)

    result = await vga.run_unified_grade_agent(
        images=[ImageRef(url="https://example.com/a.jpg")],
        subject=Subject.MATH,
        provider="silicon",
        session_id="sess_test",
        request_id="req_test",
    )
    assert result.status == "rejected"
    assert result.reason == "not_homework"


@pytest.mark.asyncio
async def test_unified_grade_fills_judgment_basis(monkeypatch):
    _clear_settings_cache()
    payload = """
    {
      "ocr_text": "题1：...",
      "results": [
        {"question_number":"1","verdict":"correct","question_content":"test","student_answer":"A","reason":"正确","judgment_basis":[],"warnings":[],"knowledge_tags":[]}
      ],
      "summary": "done",
      "warnings": []
    }
    """

    def _fake_generate_with_images(**kwargs):
        return _DummyLLMResult(payload)

    def _fake_prepare_image_inputs(**kwargs):
        return ([ImageRef(url="https://example.com/a.jpg")], [])

    monkeypatch.setattr(vga.LLMClient, "generate_with_images", _fake_generate_with_images)
    monkeypatch.setattr(vga, "_prepare_image_inputs", _fake_prepare_image_inputs)

    result = await vga.run_unified_grade_agent(
        images=[ImageRef(url="https://example.com/a.jpg")],
        subject=Subject.MATH,
        provider="silicon",
        session_id="sess_test",
        request_id="req_test",
    )
    assert result.results
    assert isinstance(result.results[0].get("judgment_basis"), list)
    assert result.results[0]["judgment_basis"]
