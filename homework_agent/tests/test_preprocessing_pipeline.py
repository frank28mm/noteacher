import asyncio


from homework_agent.models.schemas import ImageRef
from homework_agent.services.preprocessing import (
    _is_too_small_size,
    PreprocessResult,
    PreprocessingPipeline,
)
from homework_agent.services import preprocessing as prep_mod


def _run(coro):
    return asyncio.run(coro)


def test_is_too_small_size_thresholds():
    assert _is_too_small_size(10, 10) is True
    assert _is_too_small_size(70, 70) is True  # area 4900 < 5000
    assert _is_too_small_size(80, 80) is False
    assert _is_too_small_size(70, 100) is False


def test_preprocess_result_roundtrip_figure_too_small():
    result = PreprocessResult(
        figure_url="fig",
        question_url="q",
        figure_urls=["fig"],
        question_urls=["q"],
        source="opencv",
        warnings=["figure_slice_too_small"],
        cached=False,
        figure_too_small=True,
    )
    data = result.to_dict()
    restored = PreprocessResult.from_dict(data)
    assert restored.figure_too_small is True
    assert restored.figure_urls == ["fig"]


def test_preprocess_pipeline_uses_qindex_cache_first(monkeypatch):
    async def _fake_qindex_cache(self):
        return PreprocessResult(figure_urls=["f"], question_urls=["q"], source="qindex")

    async def _fake_vlm(*args, **kwargs):
        raise AssertionError("VLM locator should not run when qindex cache hits")

    async def _fake_opencv(*args, **kwargs):
        raise AssertionError("OpenCV should not run when qindex cache hits")

    monkeypatch.setattr(PreprocessingPipeline, "_try_qindex_cache", _fake_qindex_cache)
    monkeypatch.setattr(PreprocessingPipeline, "_try_vlm_locator", _fake_vlm)
    monkeypatch.setattr(PreprocessingPipeline, "_try_opencv", _fake_opencv)

    pipeline = PreprocessingPipeline(session_id="s")
    result = _run(
        pipeline.process_image(ImageRef(url="http://example.com/u.jpg"), use_cache=True)
    )
    assert result.source == "qindex"
    assert result.figure_urls == ["f"]


def test_preprocess_pipeline_falls_back_to_opencv(monkeypatch):
    async def _fake_qindex_cache(self):
        return None

    async def _fake_vlm(*args, **kwargs):
        return None

    async def _fake_opencv(self, image_ref, prefix):
        return PreprocessResult(figure_urls=["f"], question_urls=[], source="opencv")

    monkeypatch.setattr(PreprocessingPipeline, "_try_qindex_cache", _fake_qindex_cache)
    monkeypatch.setattr(PreprocessingPipeline, "_try_vlm_locator", _fake_vlm)
    monkeypatch.setattr(PreprocessingPipeline, "_try_opencv", _fake_opencv)

    pipeline = PreprocessingPipeline(session_id="s")
    result = _run(
        pipeline.process_image(ImageRef(url="http://example.com/u.jpg"), use_cache=True)
    )
    assert result.source == "opencv"
    assert result.figure_urls == ["f"]


def test_try_opencv_sets_figure_too_small(monkeypatch):
    class _Slices:
        figure_size = (60, 60)
        diagram_bbox = None
        warnings = []

    def _fake_run_opencv_pipeline(image_ref):
        return _Slices()

    def _fake_upload_slices(*, slices, prefix):
        return {"figure_url": "fig", "question_url": None, "page_url": None}

    monkeypatch.setattr(prep_mod, "run_opencv_pipeline", _fake_run_opencv_pipeline)
    monkeypatch.setattr(prep_mod, "upload_slices", _fake_upload_slices)

    pipeline = PreprocessingPipeline(session_id="s")
    result = _run(pipeline._try_opencv(ImageRef(url="http://example.com/u.jpg"), "p/"))
    assert result.figure_too_small is True
