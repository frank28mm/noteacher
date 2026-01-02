"""Unified preprocessing pipeline for Autonomous Agent.

This module provides a single entry point for image preprocessing with a 3-tier strategy:
1. A: Reuse qindex slices (if available in Redis cache) - zero cost
2. B: Call SiliconFlowQIndexLocator for VLM-based bbox detection - reliable
3. C: Fall back to OpenCV pipeline - fast but limited
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from homework_agent.models.schemas import ImageRef
from homework_agent.services.opencv_pipeline import run_opencv_pipeline, upload_slices
from homework_agent.services.qindex_locator_siliconflow import SiliconFlowQIndexLocator
from homework_agent.services.autonomous_tools import qindex_fetch
from homework_agent.core.layout_index import crop_and_upload_slices, QuestionLayout
from homework_agent.utils.cache import get_cache_store
from homework_agent.utils.settings import get_settings
from homework_agent.utils.observability import log_event

logger = logging.getLogger(__name__)

# Cache keys
PREPROCESS_CACHE_PREFIX = "preprocess:"
PREPROCESS_CACHE_TTL = 3600  # 1 hour


def _is_too_small_size(
    width: int, height: int, *, min_area_px: int = 5000, min_short_side: int = 70
) -> bool:
    if width <= 0 or height <= 0:
        return True
    area = int(width) * int(height)
    short_side = min(int(width), int(height))
    return area < min_area_px or short_side < min_short_side


@dataclass
class PreprocessResult:
    """Result from preprocessing pipeline."""

    page_url: Optional[str] = None
    figure_url: Optional[str] = None
    question_url: Optional[str] = None
    figure_urls: List[str] = field(default_factory=list)
    question_urls: List[str] = field(default_factory=list)
    diagram_bbox: Optional[tuple] = None
    source: str = "unknown"  # "qindex", "vlm", "opencv", "fallback"
    warnings: List[str] = field(default_factory=list)
    cached: bool = False
    figure_too_small: bool = False
    timings_ms: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_url": self.page_url,
            "figure_url": self.figure_url,
            "question_url": self.question_url,
            "figure_urls": self.figure_urls,
            "question_urls": self.question_urls,
            "diagram_bbox": self.diagram_bbox,
            "source": self.source,
            "warnings": self.warnings,
            "cached": self.cached,
            "figure_too_small": self.figure_too_small,
            "timings_ms": dict(self.timings_ms or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PreprocessResult":
        return cls(
            page_url=data.get("page_url"),
            figure_url=data.get("figure_url"),
            question_url=data.get("question_url"),
            figure_urls=data.get("figure_urls") or [],
            question_urls=data.get("question_urls") or [],
            diagram_bbox=(
                tuple(data["diagram_bbox"]) if data.get("diagram_bbox") else None
            ),
            source=data.get("source", "unknown"),
            warnings=data.get("warnings") or [],
            cached=data.get("cached", False),
            figure_too_small=bool(data.get("figure_too_small", False)),
            timings_ms=(
                data.get("timings_ms")
                if isinstance(data.get("timings_ms"), dict)
                else {}
            ),
        )


class PreprocessingPipeline:
    """Unified preprocessing pipeline for images.

    3-tier strategy:
    1. A: Check qindex cache (Redis) for pre-computed slices
    2. B: Call VLM locator (SiliconFlowQIndexLocator) for bbox detection
    3. C: Fall back to OpenCV pipeline

    Example:
        pipeline = PreprocessingPipeline(session_id="test_session")
        result = await pipeline.process_image(image_ref)
    """

    def __init__(
        self,
        session_id: str,
        *,
        request_id: Optional[str] = None,
        enable_qindex_cache: bool = True,
        enable_vlm: bool = True,
        enable_opencv: bool = True,
    ):
        self.session_id = session_id
        self.request_id = request_id
        self._cache: Dict[str, PreprocessResult] = {}
        self._cache_store = get_cache_store()
        self._vlm_locator = SiliconFlowQIndexLocator()
        self._enable_qindex_cache = bool(enable_qindex_cache)
        self._enable_vlm = bool(enable_vlm)
        self._enable_opencv = bool(enable_opencv)

    def _get_cache_key(self, image_hash: str) -> str:
        return f"{PREPROCESS_CACHE_PREFIX}{image_hash}"

    async def _try_qindex_cache(self) -> Optional[PreprocessResult]:
        """Strategy A: Try to reuse qindex slices from Redis cache."""
        t0 = time.monotonic()
        try:
            qindex_result = await asyncio.to_thread(
                qindex_fetch, session_id=self.session_id
            )
            if qindex_result.get("status") != "ok":
                return None

            questions = qindex_result.get("questions", {})
            if not questions:
                return None

            figure_urls: List[str] = []
            question_urls: List[str] = []

            for qn, data in questions.items():
                for page in data.get("pages", []):
                    for region in page.get("regions", []):
                        slice_url = region.get("slice_image_url")
                        if not slice_url:
                            continue
                        kind = region.get("kind", "question")
                        if kind == "figure":
                            figure_urls.append(slice_url)
                        else:
                            question_urls.append(slice_url)

            if not figure_urls and not question_urls:
                return None

            log_event(
                logger,
                "preprocess_qindex_hit",
                request_id=self.request_id,
                session_id=self.session_id,
                figures=len(figure_urls),
                questions=len(question_urls),
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )

            return PreprocessResult(
                figure_url=figure_urls[0] if figure_urls else None,
                question_url=question_urls[0] if question_urls else None,
                figure_urls=figure_urls,
                question_urls=question_urls,
                source="qindex",
                cached=True,
                figure_too_small=False,
                timings_ms={"qindex_fetch_ms": int((time.monotonic() - t0) * 1000)},
            )
        except Exception as e:
            log_event(
                logger,
                "preprocess_qindex_error",
                level="warning",
                request_id=self.request_id,
                session_id=self.session_id,
                error_type=e.__class__.__name__,
                error=str(e),
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )
            return None

    async def _try_vlm_locator(
        self,
        image_ref: ImageRef,
        prefix: str,
    ) -> Optional[PreprocessResult]:
        """Strategy B: Call VLM locator for bbox detection and crop slices."""
        if not self._vlm_locator.is_configured():
            log_event(
                logger,
                "preprocess_vlm_not_configured",
                request_id=self.request_id,
                session_id=self.session_id,
            )
            return None

        try:
            image_url = str(image_ref.url or image_ref.base64 or "")
            if not image_url:
                return None

            log_event(
                logger,
                "preprocess_vlm_start",
                request_id=self.request_id,
                session_id=self.session_id,
            )

            # Call VLM locator
            t_loc = time.monotonic()
            loc = await asyncio.to_thread(
                self._vlm_locator.locate,
                image_url=image_url,
                only_question_numbers=None,
            )
            locate_ms = int((time.monotonic() - t_loc) * 1000)

            if not loc.questions:
                log_event(
                    logger,
                    "preprocess_vlm_no_questions",
                    request_id=self.request_id,
                    session_id=self.session_id,
                )
                return None

            # Build layouts from VLM results
            settings = get_settings()
            layouts: Dict[str, QuestionLayout] = {}
            region_kinds: Dict[str, List[str]] = {}

            for q in loc.questions:
                qn = q.get("question_number")
                regions = q.get("regions")
                if not isinstance(qn, str) or not qn.strip():
                    continue
                qn_s = qn.strip()
                if not isinstance(regions, list) or not regions:
                    continue

                bboxes_yxyx: List[List[float]] = []
                kinds: List[str] = []

                for r in regions:
                    if not isinstance(r, dict):
                        continue
                    kind = str(r.get("kind") or "question").strip().lower()
                    if kind not in ("question", "figure"):
                        kind = "question"

                    bbox = r.get("bbox_norm_xyxy")
                    if not (
                        isinstance(bbox, (list, tuple))
                        and len(bbox) == 4
                        and all(isinstance(v, (int, float)) for v in bbox)
                    ):
                        continue

                    xmin, ymin, xmax, ymax = [float(v) for v in bbox]
                    # Clamp to [0, 1]
                    xmin = max(0.0, min(1.0, xmin))
                    ymin = max(0.0, min(1.0, ymin))
                    xmax = max(0.0, min(1.0, xmax))
                    ymax = max(0.0, min(1.0, ymax))

                    # Convert to yxyx for downstream cropper
                    b_yxyx = [ymin, xmin, ymax, xmax]

                    # Apply padding
                    pad = float(settings.slice_padding_ratio or 0.05)
                    if kind == "figure":
                        pad = min(0.25, pad * 2.0)

                    ymin2, xmin2, ymax2, xmax2 = b_yxyx
                    h2 = max(0.0, ymax2 - ymin2)
                    w2 = max(0.0, xmax2 - xmin2)
                    pad_y = h2 * pad
                    pad_x = w2 * pad
                    b_yxyx = [
                        max(0.0, ymin2 - pad_y),
                        max(0.0, xmin2 - pad_x),
                        min(1.0, ymax2 + pad_y),
                        min(1.0, xmax2 + pad_x),
                    ]
                    bboxes_yxyx.append(b_yxyx)
                    kinds.append(kind)

                if not bboxes_yxyx:
                    continue

                layouts[qn_s] = QuestionLayout(
                    question_number=qn_s,
                    bboxes_norm=bboxes_yxyx,
                    slice_image_urls=[],
                    warnings=[],
                )
                region_kinds[qn_s] = kinds

            if not layouts:
                return None

            # Crop and upload slices
            t_crop = time.monotonic()
            layouts = await asyncio.to_thread(
                crop_and_upload_slices,
                page_image_url=image_url,
                layouts=layouts,
                only_question_numbers=None,
                prefix=prefix,
            )
            crop_upload_ms = int((time.monotonic() - t_crop) * 1000)

            # Collect slice URLs
            figure_urls: List[str] = []
            question_urls: List[str] = []
            figure_too_small = False
            warnings: List[str] = []

            for qn, layout in layouts.items():
                kinds = region_kinds.get(qn, [])
                for i, url in enumerate(layout.slice_image_urls or []):
                    if not url:
                        continue
                    kind = kinds[i] if i < len(kinds) else "question"
                    size = None
                    if i < len(layout.slice_sizes_px or []):
                        size = layout.slice_sizes_px[i]
                    if kind == "figure":
                        figure_urls.append(url)
                        if size and _is_too_small_size(
                            size.get("width", 0), size.get("height", 0)
                        ):
                            figure_too_small = True
                    else:
                        question_urls.append(url)

            log_event(
                logger,
                "preprocess_vlm_done",
                request_id=self.request_id,
                session_id=self.session_id,
                layouts=len(layouts),
                figures=len(figure_urls),
                questions=len(question_urls),
                locate_ms=locate_ms,
                crop_upload_ms=crop_upload_ms,
            )

            return PreprocessResult(
                figure_url=figure_urls[0] if figure_urls else None,
                question_url=question_urls[0] if question_urls else None,
                figure_urls=figure_urls,
                question_urls=question_urls,
                source="vlm",
                cached=False,
                warnings=(
                    warnings + (["figure_slice_too_small"] if figure_too_small else [])
                ),
                figure_too_small=figure_too_small,
                timings_ms={
                    "vlm_locate_ms": locate_ms,
                    "vlm_crop_upload_ms": crop_upload_ms,
                    "vlm_total_ms": int(locate_ms + crop_upload_ms),
                },
            )

        except Exception as e:
            log_event(
                logger,
                "preprocess_vlm_error",
                level="warning",
                request_id=self.request_id,
                session_id=self.session_id,
                error_type=e.__class__.__name__,
                error=str(e),
            )
            return None

    async def _try_opencv(
        self,
        image_ref: ImageRef,
        prefix: str,
    ) -> PreprocessResult:
        """Strategy C: Fall back to OpenCV pipeline."""
        t0 = time.monotonic()
        t_run = time.monotonic()
        slices = await asyncio.to_thread(run_opencv_pipeline, image_ref)
        run_ms = int((time.monotonic() - t_run) * 1000)
        if not slices:
            return PreprocessResult(
                warnings=["opencv_pipeline_failed"],
                source="fallback",
                timings_ms={"opencv_run_ms": run_ms, "opencv_total_ms": run_ms},
            )

        t_up = time.monotonic()
        urls = await asyncio.to_thread(upload_slices, slices=slices, prefix=prefix)
        upload_ms = int((time.monotonic() - t_up) * 1000)
        total_ms = int((time.monotonic() - t0) * 1000)

        figure_too_small = bool(
            slices.figure_size
            and _is_too_small_size(slices.figure_size[0], slices.figure_size[1])
        )
        warnings = list(slices.warnings or [])
        if figure_too_small:
            warnings.append("figure_slice_too_small")
        return PreprocessResult(
            page_url=urls.get("page_url"),
            figure_url=urls.get("figure_url"),
            question_url=urls.get("question_url"),
            figure_urls=[urls.get("figure_url")] if urls.get("figure_url") else [],
            question_urls=(
                [urls.get("question_url")] if urls.get("question_url") else []
            ),
            diagram_bbox=slices.diagram_bbox,
            source="opencv",
            warnings=warnings,
            cached=False,
            figure_too_small=figure_too_small,
            timings_ms={
                "opencv_run_ms": run_ms,
                "opencv_upload_ms": upload_ms,
                "opencv_total_ms": total_ms,
            },
        )

    async def process_image(
        self,
        image_ref: ImageRef,
        *,
        prefix: Optional[str] = None,
        use_cache: bool = True,
    ) -> PreprocessResult:
        """Process a single image through the 3-tier preprocessing pipeline.

        Strategy:
        1. A: Check qindex cache - zero cost, best quality
        2. B: Call VLM locator - reliable for geometry
        3. C: Fall back to OpenCV - fast but limited

        Args:
            image_ref: Image reference (URL or base64)
            prefix: Storage prefix for uploaded slices
            use_cache: Whether to use cached results

        Returns:
            PreprocessResult containing slice URLs and metadata
        """
        if prefix is None:
            prefix = f"autonomous/prep/{self.session_id}/"

        # Strategy A: Try qindex cache first
        if use_cache and self._enable_qindex_cache:
            result = await self._try_qindex_cache()
            if result and (result.figure_urls or result.question_urls):
                return result

        # Strategy B: Try VLM locator
        if self._enable_vlm:
            result = await self._try_vlm_locator(image_ref, prefix)
            if result and (result.figure_urls or result.question_urls):
                return result

        # Strategy C: Fall back to OpenCV
        if self._enable_opencv:
            return await self._try_opencv(image_ref, prefix)

        # No preprocessing strategies enabled
        return PreprocessResult(
            source="disabled",
            warnings=["preprocess_disabled"],
            cached=False,
            figure_too_small=False,
            timings_ms={},
        )

    async def process_batch(
        self,
        image_refs: List[ImageRef],
        *,
        prefix: Optional[str] = None,
        use_cache: bool = True,
    ) -> List[PreprocessResult]:
        """Process multiple images through the preprocessing pipeline."""
        results = []
        for ref in image_refs:
            result = await self.process_image(ref, prefix=prefix, use_cache=use_cache)
            results.append(result)
        return results

    def clear_cache(self) -> None:
        """Clear in-memory cache."""
        self._cache.clear()

    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            "in_memory_size": len(self._cache),
        }
