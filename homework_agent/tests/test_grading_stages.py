from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

import homework_agent.api._grading_stages as stages

from homework_agent.api._grading_stages import _run_grading_llm_stage, _run_grading_vision_stage
from homework_agent.api.grade import _GradingAbort
from homework_agent.models.schemas import GradeRequest, ImageRef, Subject, VisionProvider
from homework_agent.services.llm import EnglishGradingResult, MathGradingResult


def _run(coro):
    return asyncio.run(coro)


async def _call_blocking_direct(fn, *args, timeout_seconds: float, semaphore: Any, **kwargs):  # noqa: ARG001
    return fn(*args, **kwargs)


def _noop(*args, **kwargs):  # noqa: ARG001
    return None


def test_vision_stage_aborts_when_budget_exhausted(monkeypatch):
    monkeypatch.setattr(stages, "_remaining_seconds", lambda _d: 0.0)

    calls: Dict[str, Any] = {}

    def persist_question_bank(*, session_id: str, bank: Dict[str, Any], grade_status: str, grade_summary: str, grade_warnings: List[str], timings_ms: Dict[str, int]):  # noqa: E501
        calls["persist"] = {
            "session_id": session_id,
            "bank": bank,
            "grade_status": grade_status,
            "grade_summary": grade_summary,
            "grade_warnings": grade_warnings,
            "timings_ms": timings_ms,
        }

    req = GradeRequest(subject=Subject.MATH, images=[ImageRef(url="https://example.com/a.jpg")], vision_provider=VisionProvider.QWEN3)

    with pytest.raises(_GradingAbort) as ei:
        _run(
            _run_grading_vision_stage(
                req=req,
                session_id="s_budget_0",
                request_id="r1",
                settings=SimpleNamespace(grade_vision_timeout_seconds=10),
                started_m=0.0,
                deadline_m=0.0,
                vision_prompt="p",
                vision_client=SimpleNamespace(analyze=lambda **_: None),
                page_image_urls=["https://example.com/a.jpg"],
                page_image_urls_original=["https://example.com/a.jpg"],
                meta_base={},
                timings_ms={},
                call_blocking_in_thread=_call_blocking_direct,
                vision_semaphore=asyncio.Semaphore(1),
                persist_question_bank=persist_question_bank,
                merge_bank_meta=lambda b, m: {**b, "_meta": m},
                save_grade_progress=_noop,
                log_event=_noop,
            )
        )
    abort = ei.value
    assert abort.response.summary == "Vision analysis not available"
    assert any("grade SLA exceeded" in w for w in abort.response.warnings or [])
    assert calls["persist"]["grade_status"] == "failed"


def test_vision_stage_aborts_for_non_doubao_failure(monkeypatch):
    monkeypatch.setattr(stages, "_remaining_seconds", lambda _d: 10.0)

    def analyze(*, images, prompt, provider):  # noqa: ARG001
        raise RuntimeError("boom")

    req = GradeRequest(subject=Subject.MATH, images=[ImageRef(url="https://example.com/a.jpg")], vision_provider=VisionProvider.QWEN3)

    with pytest.raises(_GradingAbort) as ei:
        _run(
            _run_grading_vision_stage(
                req=req,
                session_id="s_non_doubao_fail",
                request_id="r1",
                settings=SimpleNamespace(grade_vision_timeout_seconds=10),
                started_m=0.0,
                deadline_m=999.0,
                vision_prompt="p",
                vision_client=SimpleNamespace(analyze=analyze),
                page_image_urls=["https://example.com/a.jpg"],
                page_image_urls_original=["https://example.com/a.jpg"],
                meta_base={},
                timings_ms={},
                call_blocking_in_thread=_call_blocking_direct,
                vision_semaphore=asyncio.Semaphore(1),
                persist_question_bank=_noop,
                merge_bank_meta=lambda b, m: b,
                save_grade_progress=_noop,
                log_event=_noop,
            )
        )
    assert "Vision analysis failed" in (ei.value.response.warnings or [""])[0]


def test_vision_stage_doubao_proxy_retry_success_returns_proxy_urls(monkeypatch):
    monkeypatch.setattr(stages, "_remaining_seconds", lambda _d: 10.0)
    monkeypatch.setattr(stages, "_probe_url_head", lambda _u: None)
    monkeypatch.setattr(
        stages,
        "_create_proxy_image_urls",
        lambda urls, session_id, prefix="proxy/": ["https://proxy/a.jpg"],
    )

    def analyze(*, images, prompt, provider):  # noqa: ARG001
        urls = [getattr(i, "url", None) for i in images]
        if any(u and "proxy" in str(u) for u in urls):
            return SimpleNamespace(text="ok")
        raise RuntimeError("Timeout while fetching image_url")

    req = GradeRequest(subject=Subject.MATH, images=[ImageRef(url="https://example.com/a.jpg")], vision_provider=VisionProvider.DOUBAO)
    meta: Dict[str, Any] = {}

    vision_result, page_urls, warn = _run(
        _run_grading_vision_stage(
            req=req,
            session_id="s_proxy_ok",
            request_id="r1",
            settings=SimpleNamespace(grade_vision_timeout_seconds=10),
            started_m=0.0,
            deadline_m=999.0,
            vision_prompt="p",
            vision_client=SimpleNamespace(analyze=analyze),
            page_image_urls=["https://example.com/a.jpg"],
            page_image_urls_original=["https://example.com/a.jpg"],
            meta_base=meta,
            timings_ms={},
            call_blocking_in_thread=_call_blocking_direct,
            vision_semaphore=asyncio.Semaphore(1),
            persist_question_bank=_noop,
            merge_bank_meta=lambda b, m: b,
            save_grade_progress=_noop,
            log_event=_noop,
        )
    )
    assert vision_result.text == "ok"
    assert page_urls == ["https://proxy/a.jpg"]
    assert "轻量副本" in (warn or "")
    assert meta.get("vision_used_proxy_url") is True


def test_vision_stage_doubao_base64_retry_sets_flag_and_warning(monkeypatch):
    monkeypatch.setattr(stages, "_remaining_seconds", lambda _d: 10.0)
    monkeypatch.setattr(stages, "_probe_url_head", lambda _u: None)
    monkeypatch.setattr(stages, "_is_provider_image_fetch_issue", lambda _e: False)
    monkeypatch.setattr(stages, "_download_as_data_uri", lambda _u: "data:image/jpeg;base64,AA==")

    def analyze(*, images, prompt, provider):  # noqa: ARG001
        if any(getattr(i, "base64", None) for i in images):
            return SimpleNamespace(text="ok")
        raise RuntimeError("boom")

    req = GradeRequest(subject=Subject.MATH, images=[ImageRef(url="https://example.com/a.jpg")], vision_provider=VisionProvider.DOUBAO)
    meta: Dict[str, Any] = {}

    vision_result, _page_urls, warn = _run(
        _run_grading_vision_stage(
            req=req,
            session_id="s_b64_ok",
            request_id="r1",
            settings=SimpleNamespace(grade_vision_timeout_seconds=10),
            started_m=0.0,
            deadline_m=999.0,
            vision_prompt="p",
            vision_client=SimpleNamespace(analyze=analyze),
            page_image_urls=["https://example.com/a.jpg"],
            page_image_urls_original=["https://example.com/a.jpg"],
            meta_base=meta,
            timings_ms={},
            call_blocking_in_thread=_call_blocking_direct,
            vision_semaphore=asyncio.Semaphore(1),
            persist_question_bank=_noop,
            merge_bank_meta=lambda b, m: b,
            save_grade_progress=_noop,
            log_event=_noop,
        )
    )
    assert vision_result.text == "ok"
    assert meta.get("vision_used_base64_fallback") is True
    assert "base64" in (warn or "")


def test_vision_stage_doubao_base64_retry_without_conversion_sets_flag_false(monkeypatch):
    monkeypatch.setattr(stages, "_remaining_seconds", lambda _d: 10.0)
    monkeypatch.setattr(stages, "_probe_url_head", lambda _u: None)
    monkeypatch.setattr(stages, "_is_provider_image_fetch_issue", lambda _e: False)
    monkeypatch.setattr(stages, "_download_as_data_uri", lambda _u: None)

    calls = {"n": 0}

    def analyze(*, images, prompt, provider):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return SimpleNamespace(text="ok")

    req = GradeRequest(subject=Subject.MATH, images=[ImageRef(url="https://example.com/a.jpg")], vision_provider=VisionProvider.DOUBAO)
    meta: Dict[str, Any] = {}

    vision_result, _page_urls, warn = _run(
        _run_grading_vision_stage(
            req=req,
            session_id="s_b64_no_conv",
            request_id="r1",
            settings=SimpleNamespace(grade_vision_timeout_seconds=10),
            started_m=0.0,
            deadline_m=999.0,
            vision_prompt="p",
            vision_client=SimpleNamespace(analyze=analyze),
            page_image_urls=["https://example.com/a.jpg"],
            page_image_urls_original=["https://example.com/a.jpg"],
            meta_base=meta,
            timings_ms={},
            call_blocking_in_thread=_call_blocking_direct,
            vision_semaphore=asyncio.Semaphore(1),
            persist_question_bank=_noop,
            merge_bank_meta=lambda b, m: b,
            save_grade_progress=_noop,
            log_event=_noop,
        )
    )
    assert vision_result.text == "ok"
    assert meta.get("vision_used_base64_fallback") is False
    assert warn is None


def test_vision_stage_doubao_proxy_none_falls_back_to_base64(monkeypatch):
    monkeypatch.setattr(stages, "_remaining_seconds", lambda _d: 10.0)
    monkeypatch.setattr(stages, "_probe_url_head", lambda _u: None)
    monkeypatch.setattr(stages, "_create_proxy_image_urls", lambda *a, **k: None)
    monkeypatch.setattr(stages, "_download_as_data_uri", lambda _u: "data:image/jpeg;base64,AA==")

    def analyze(*, images, prompt, provider):  # noqa: ARG001
        if any(getattr(i, "base64", None) for i in images):
            return SimpleNamespace(text="ok")
        raise RuntimeError("Timeout while fetching image_url")

    req = GradeRequest(subject=Subject.MATH, images=[ImageRef(url="https://example.com/a.jpg")], vision_provider=VisionProvider.DOUBAO)
    meta: Dict[str, Any] = {}

    vision_result, _page_urls, _warn = _run(
        _run_grading_vision_stage(
            req=req,
            session_id="s_proxy_none",
            request_id="r1",
            settings=SimpleNamespace(grade_vision_timeout_seconds=10),
            started_m=0.0,
            deadline_m=999.0,
            vision_prompt="p",
            vision_client=SimpleNamespace(analyze=analyze),
            page_image_urls=["https://example.com/a.jpg"],
            page_image_urls_original=["https://example.com/a.jpg"],
            meta_base=meta,
            timings_ms={},
            call_blocking_in_thread=_call_blocking_direct,
            vision_semaphore=asyncio.Semaphore(1),
            persist_question_bank=_noop,
            merge_bank_meta=lambda b, m: b,
            save_grade_progress=_noop,
            log_event=_noop,
        )
    )
    assert vision_result.text == "ok"
    assert meta.get("vision_used_base64_fallback") is True


def test_llm_stage_math_success_assigns_item_id(monkeypatch):
    monkeypatch.setattr(stages, "_remaining_seconds", lambda _d: 10.0)

    def grade_math(*, text_content: str, provider: str):  # noqa: ARG001
        return MathGradingResult(summary="ok", wrong_items=[{"question_number": "1", "reason": "x"}], questions=[])

    req = GradeRequest(subject=Subject.MATH, images=[ImageRef(url="https://example.com/a.jpg")], vision_provider=VisionProvider.QWEN3)
    meta: Dict[str, Any] = {}
    timings: Dict[str, int] = {}

    result = _run(
        _run_grading_llm_stage(
            req=req,
            provider_str="silicon",
            llm_client=SimpleNamespace(grade_math=grade_math),
            vision_text="vision",
            settings=SimpleNamespace(grade_llm_timeout_seconds=10),
            started_m=0.0,
            deadline_m=999.0,
            session_id="s",
            request_id="r",
            meta_base=meta,
            timings_ms=timings,
            call_blocking_in_thread=_call_blocking_direct,
            llm_semaphore=asyncio.Semaphore(1),
            save_grade_progress=_noop,
            log_event=_noop,
        )
    )
    assert isinstance(result, MathGradingResult)
    assert result.wrong_items[0]["item_id"] == "q:1"
    assert meta.get("llm_provider_used") == "silicon"


def test_llm_stage_math_ark_error_falls_back_to_silicon_sets_meta(monkeypatch):
    monkeypatch.setattr(stages, "_remaining_seconds", lambda _d: 10.0)

    def grade_math(*, text_content: str, provider: str):  # noqa: ARG001
        if provider == "ark":
            raise RuntimeError("ark down")
        return MathGradingResult(summary="ok", wrong_items=[{"question_number": "1", "reason": "x"}], questions=[])

    req = GradeRequest(subject=Subject.MATH, images=[ImageRef(url="https://example.com/a.jpg")], vision_provider=VisionProvider.QWEN3)
    meta: Dict[str, Any] = {}

    result = _run(
        _run_grading_llm_stage(
            req=req,
            provider_str="ark",
            llm_client=SimpleNamespace(grade_math=grade_math),
            vision_text="vision",
            settings=SimpleNamespace(grade_llm_timeout_seconds=10),
            started_m=0.0,
            deadline_m=999.0,
            session_id="s",
            request_id="r",
            meta_base=meta,
            timings_ms={},
            call_blocking_in_thread=_call_blocking_direct,
            llm_semaphore=asyncio.Semaphore(1),
            save_grade_progress=_noop,
            log_event=_noop,
        )
    )
    assert meta.get("llm_provider_used") == "silicon"
    assert meta.get("llm_used_fallback") is True
    assert any("fell back to qwen3" in w for w in (result.warnings or []))


def test_llm_stage_english_ark_error_falls_back_to_silicon_sets_meta(monkeypatch):
    monkeypatch.setattr(stages, "_remaining_seconds", lambda _d: 10.0)

    def grade_english(*, text_content: str, mode, provider: str):  # noqa: ARG001
        if provider == "ark":
            raise RuntimeError("ark down")
        return EnglishGradingResult(summary="ok", wrong_items=[{"question_number": "1", "reason": "x"}], questions=[])

    req = GradeRequest(subject=Subject.ENGLISH, images=[ImageRef(url="https://example.com/a.jpg")], vision_provider=VisionProvider.QWEN3)
    meta: Dict[str, Any] = {}

    result = _run(
        _run_grading_llm_stage(
            req=req,
            provider_str="ark",
            llm_client=SimpleNamespace(grade_english=grade_english),
            vision_text="vision",
            settings=SimpleNamespace(grade_llm_timeout_seconds=10),
            started_m=0.0,
            deadline_m=999.0,
            session_id="s",
            request_id="r",
            meta_base=meta,
            timings_ms={},
            call_blocking_in_thread=_call_blocking_direct,
            llm_semaphore=asyncio.Semaphore(1),
            save_grade_progress=_noop,
            log_event=_noop,
        )
    )
    assert isinstance(result, EnglishGradingResult)
    assert meta.get("llm_provider_used") == "silicon"
    assert meta.get("llm_used_fallback") is True


def test_llm_stage_non_ark_error_propagates(monkeypatch):
    monkeypatch.setattr(stages, "_remaining_seconds", lambda _d: 10.0)

    def grade_math(*, text_content: str, provider: str):  # noqa: ARG001
        raise RuntimeError("boom")

    req = GradeRequest(subject=Subject.MATH, images=[ImageRef(url="https://example.com/a.jpg")], vision_provider=VisionProvider.QWEN3)

    with pytest.raises(RuntimeError, match="boom"):
        _run(
            _run_grading_llm_stage(
                req=req,
                provider_str="silicon",
                llm_client=SimpleNamespace(grade_math=grade_math),
                vision_text="vision",
                settings=SimpleNamespace(grade_llm_timeout_seconds=10),
                started_m=0.0,
                deadline_m=999.0,
                session_id="s",
                request_id="r",
                meta_base={},
                timings_ms={},
                call_blocking_in_thread=_call_blocking_direct,
                llm_semaphore=asyncio.Semaphore(1),
                save_grade_progress=_noop,
                log_event=_noop,
            )
        )
