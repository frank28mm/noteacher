from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List

from homework_agent.services.ocr_baidu import BaiduPaddleOCRVLClient
from homework_agent.services.ocr_siliconflow import SiliconFlowDeepSeekOCRClient
from homework_agent.services.qindex_locator_siliconflow import SiliconFlowQIndexLocator
from homework_agent.core.layout_index import (
    QuestionLayout,
    build_question_layouts_from_blocks,
    crop_and_upload_slices,
)
from homework_agent.utils.settings import get_settings
from homework_agent.utils.observability import log_event, redact_url

logger = logging.getLogger(__name__)

def qindex_is_configured() -> tuple[bool, str]:
    """
    Best-effort check whether qindex can run in the current environment.

    Returns:
      (ok, reason)
        ok=True  -> qindex is configured
        ok=False -> reason describes why it will be skipped (for client-facing warnings)
    """
    settings = get_settings()
    provider = (settings.ocr_provider or "").strip().lower()

    if provider in ("disabled", "off", "none"):
        return False, f"ocr_disabled (OCR_PROVIDER={provider or 'disabled'})"

    ocr_baidu = BaiduPaddleOCRVLClient()
    ocr_deepseek = SiliconFlowDeepSeekOCRClient()
    qwen_locator = SiliconFlowQIndexLocator()

    if provider in ("baidu", "baidu_paddleocr_vl"):
        if not ocr_baidu.is_configured():
            return False, f"baidu_ocr_unconfigured (OCR_PROVIDER={provider})"
        return True, f"ok (OCR_PROVIDER={provider})"
    if provider in ("siliconflow_qwen3_vl", "siliconflow_qindex", "siliconflow_vl"):
        if not qwen_locator.is_configured():
            return False, f"silicon_qindex_unconfigured (OCR_PROVIDER={provider})"
        return True, f"ok (OCR_PROVIDER={provider})"

    # legacy: deepseek ocr (text-only; bbox best-effort)
    if not ocr_deepseek.is_configured():
        return False, f"silicon_ocr_unconfigured (OCR_PROVIDER={provider or 'siliconflow_deepseek'})"
    return True, f"ok (OCR_PROVIDER={provider or 'siliconflow_deepseek'})"


def build_question_index_for_pages(
    page_urls: List[str],
    *,
    question_numbers: List[str] | None = None,
    session_id: str | None = None,
) -> Dict[str, Any]:
    """
    Build per-question bbox/slice index using OCR + simple layout heuristics.

    Returns:
      {
        "questions": { "<question_number>": { "question_number": ..., "pages": [...] }, ... },
        "warnings": [...],
      }
    """
    settings = get_settings()
    provider = (settings.ocr_provider or "").strip().lower()

    ocr_baidu = BaiduPaddleOCRVLClient()
    ocr_deepseek = SiliconFlowDeepSeekOCRClient()
    qwen_locator = SiliconFlowQIndexLocator()

    ok, reason = qindex_is_configured()
    if not ok:
        return {"questions": {}, "warnings": [f"qindex skipped: {reason}"]}

    t_all = time.monotonic()
    questions: Dict[str, Any] = {}
    warnings: List[str] = []
    only_qnums = {str(q).strip() for q in (question_numbers or []) if str(q).strip()} if question_numbers else None
    # For storage hygiene and later cleanup, prefer a stable session-scoped prefix.
    # Chat should NOT rely on path conventions; it must always rely on URLs stored in Redis qindex.
    base_prefix = f"slices/{session_id}/" if session_id else f"slices/{datetime.now().strftime('%Y%m%d')}/"

    for page_idx, page_url in enumerate(page_urls or []):
        if not page_url:
            continue
        t_page = time.monotonic()
        try:
            log_event(
                logger,
                "qindex_page_start",
                page_index=page_idx,
                page_image_url=redact_url(page_url),
            )
            # Download image once to get size (also needed for slice cropping)
            from homework_agent.core.layout_index import download_image

            img = download_image(page_url, timeout=30.0)
            w, h = img.size

            task_id = None
            task_status = None
            ocr_provider_name = "unknown"
            if provider in ("baidu", "baidu_paddleocr_vl"):
                task_id = ocr_baidu.submit(image_url=page_url)
                task = ocr_baidu.wait(task_id)
                task_status = task.status
                blocks = ocr_baidu.extract_text_blocks(task.raw)
                ocr_provider_name = "baidu_paddleocr_vl"
            elif provider in ("siliconflow_qwen3_vl", "siliconflow_qindex", "siliconflow_vl"):
                allow_list = sorted(list(only_qnums)) if only_qnums is not None else None
                loc = qwen_locator.locate(image_url=page_url, only_question_numbers=allow_list)
                task_status = "done" if loc.questions else "failed"

                # Build layouts directly from locator results so we can support multi-bbox per question
                # (e.g. shared figure area + question work area).
                layouts: Dict[str, QuestionLayout] = {}
                region_kinds: Dict[str, List[str]] = {}
                for q in loc.questions:
                    qn = q.get("question_number")
                    regions = q.get("regions")
                    if not isinstance(qn, str) or not qn.strip():
                        continue
                    qn_s = qn.strip()
                    if only_qnums is not None and qn_s not in only_qnums:
                        continue
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
                        # Clamp
                        xmin = 0.0 if xmin < 0.0 else 1.0 if xmin > 1.0 else xmin
                        ymin = 0.0 if ymin < 0.0 else 1.0 if ymin > 1.0 else ymin
                        xmax = 0.0 if xmax < 0.0 else 1.0 if xmax > 1.0 else xmax
                        ymax = 0.0 if ymax < 0.0 else 1.0 if ymax > 1.0 else ymax
                        # Convert to yxyx for downstream cropper
                        b_yxyx = [ymin, xmin, ymax, xmax]
                        # Apply kind-specific padding: figures usually need more margin to avoid cut-off.
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
                    warnings.append(f"page[{page_idx}]: OCR 未返回可用 blocks，改用整页")
                    log_event(
                        logger,
                        "qindex_page_done",
                        page_index=page_idx,
                        status="no_blocks",
                        task_id=task_id,
                        elapsed_ms=int((time.monotonic() - t_page) * 1000),
                    )
                    continue

                layouts = crop_and_upload_slices(
                    page_image_url=page_url,
                    layouts=layouts,
                    only_question_numbers=only_qnums,
                    prefix=f"{base_prefix}p{page_idx}/",
                )
                slices_total = sum(len(v.slice_image_urls or []) for v in layouts.values())
                log_event(
                    logger,
                    "qindex_page_layouts_built",
                    page_index=page_idx,
                    task_id=task_id,
                    task_status=task_status,
                    blocks=None,
                    layouts=len(layouts),
                    slices=slices_total,
                )

                for qn, layout in layouts.items():
                    # Add region metadata (kind + bbox + slice url) while keeping old fields.
                    kinds = region_kinds.get(qn) or ["question"] * len(layout.bboxes_norm or [])
                    regions_out: List[Dict[str, Any]] = []
                    for i, bbox_yxyx in enumerate(layout.bboxes_norm or []):
                        u = (layout.slice_image_urls or [None] * len(layout.bboxes_norm))[i] if i < len(layout.slice_image_urls or []) else None
                        regions_out.append({"kind": kinds[i] if i < len(kinds) else "question", "bbox": bbox_yxyx, "slice_image_url": u})

                    entry = questions.get(qn) or {"question_number": qn, "pages": []}
                    entry["pages"].append(
                        {
                            "page_index": page_idx,
                            "page_image_url": page_url,
                            "question_bboxes": [{"coords": b, "kind": regions_out[i]["kind"]} for i, b in enumerate(layout.bboxes_norm or [])],
                            "slice_image_urls": layout.slice_image_urls,
                            "regions": regions_out,
                            "warnings": layout.warnings,
                            "ocr": {
                                "provider": "siliconflow_qwen3_vl_locator",
                                "task_id": task_id,
                                "status": task_status,
                            },
                        }
                    )
                    questions[qn] = entry

                log_event(
                    logger,
                    "qindex_page_done",
                    page_index=page_idx,
                    status="ok",
                    task_id=task_id,
                    questions=len(layouts),
                    slices=slices_total,
                    elapsed_ms=int((time.monotonic() - t_page) * 1000),
                )
                continue
            else:
                res = ocr_deepseek.analyze(image_url=page_url)
                task_id = None
                task_status = "done" if res.blocks else "failed"
                # Convert bbox_norm -> px location for layout_index
                blocks = []
                for b in res.blocks:
                    bbox = b.get("bbox_norm")
                    if not (
                        isinstance(bbox, (list, tuple))
                        and len(bbox) == 4
                        and all(isinstance(v, (int, float)) for v in bbox)
                    ):
                        continue
                    xmin, ymin, xmax, ymax = [float(v) for v in bbox]
                    xmin = 0.0 if xmin < 0.0 else 1.0 if xmin > 1.0 else xmin
                    ymin = 0.0 if ymin < 0.0 else 1.0 if ymin > 1.0 else ymin
                    xmax = 0.0 if xmax < 0.0 else 1.0 if xmax > 1.0 else xmax
                    ymax = 0.0 if ymax < 0.0 else 1.0 if ymax > 1.0 else ymax
                    left = xmin * w
                    top = ymin * h
                    width = max(1.0, (xmax - xmin) * w)
                    height = max(1.0, (ymax - ymin) * h)
                    blocks.append(
                        {
                            "text": b.get("text"),
                            "location": {"left": left, "top": top, "width": width, "height": height},
                        }
                    )
                ocr_provider_name = "siliconflow_deepseek_ocr"

                # DeepSeek-OCR frequently returns no reliable bbox blocks; fall back to a
                # multimodal locator (Qwen3-VL) to get per-question bboxes for slicing.
                if not blocks and qwen_locator.is_configured():
                    log_event(
                        logger,
                        "qindex_fallback_locator",
                        from_provider="siliconflow_deepseek_ocr",
                        to_provider="siliconflow_qwen3_vl_locator",
                        page_index=page_idx,
                        page_image_url=redact_url(page_url),
                        allowlist=len(only_qnums or []),
                    )
                    allow_list = sorted(list(only_qnums)) if only_qnums is not None else None
                    loc = qwen_locator.locate(image_url=page_url, only_question_numbers=allow_list)
                    task_status = "done" if loc.questions else "failed"

                    layouts: Dict[str, QuestionLayout] = {}
                    region_kinds: Dict[str, List[str]] = {}
                    for q in loc.questions:
                        qn = q.get("question_number")
                        regions = q.get("regions")
                        if not isinstance(qn, str) or not qn.strip():
                            continue
                        qn_s = qn.strip()
                        if only_qnums is not None and qn_s not in only_qnums:
                            continue
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
                            xmin = 0.0 if xmin < 0.0 else 1.0 if xmin > 1.0 else xmin
                            ymin = 0.0 if ymin < 0.0 else 1.0 if ymin > 1.0 else ymin
                            xmax = 0.0 if xmax < 0.0 else 1.0 if xmax > 1.0 else xmax
                            ymax = 0.0 if ymax < 0.0 else 1.0 if ymax > 1.0 else ymax
                            b_yxyx = [ymin, xmin, ymax, xmax]
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

                    if layouts:
                        ocr_provider_name = "siliconflow_qwen3_vl_locator_fallback"
                        layouts = crop_and_upload_slices(
                            page_image_url=page_url,
                            layouts=layouts,
                            only_question_numbers=only_qnums,
                            prefix=f"{base_prefix}p{page_idx}/",
                        )
                        for qn, layout in layouts.items():
                            kinds = region_kinds.get(qn) or ["question"] * len(layout.bboxes_norm or [])
                            regions_out: List[Dict[str, Any]] = []
                            for i, bbox_yxyx in enumerate(layout.bboxes_norm or []):
                                u = (layout.slice_image_urls or [None] * len(layout.bboxes_norm))[i] if i < len(layout.slice_image_urls or []) else None
                                regions_out.append({"kind": kinds[i] if i < len(kinds) else "question", "bbox": bbox_yxyx, "slice_image_url": u})
                            entry = questions.get(qn) or {"question_number": qn, "pages": []}
                            entry["pages"].append(
                                {
                                    "page_index": page_idx,
                                    "page_image_url": page_url,
                                    "question_bboxes": [{"coords": b, "kind": regions_out[i]["kind"]} for i, b in enumerate(layout.bboxes_norm or [])],
                                    "slice_image_urls": layout.slice_image_urls,
                                    "regions": regions_out,
                                    "warnings": layout.warnings,
                                    "ocr": {
                                        "provider": ocr_provider_name,
                                        "task_id": task_id,
                                        "status": task_status,
                                    },
                                }
                            )
                            questions[qn] = entry
                        log_event(
                            logger,
                            "qindex_page_done",
                            page_index=page_idx,
                            status="ok",
                            task_id=task_id,
                            questions=len(layouts),
                            slices=sum(len(v.slice_image_urls or []) for v in layouts.values()),
                            elapsed_ms=int((time.monotonic() - t_page) * 1000),
                        )
                        continue
            if not blocks:
                warnings.append(f"page[{page_idx}]: OCR 未返回可用 blocks，改用整页")
                log_event(
                    logger,
                    "qindex_page_done",
                    page_index=page_idx,
                    status="no_blocks",
                    task_id=task_id,
                    elapsed_ms=int((time.monotonic() - t_page) * 1000),
                )
                continue

            layouts = build_question_layouts_from_blocks(
                blocks=blocks,
                page_width=w,
                page_height=h,
                padding_ratio=settings.slice_padding_ratio,
            )
            # Upload slices (best-effort)
            layouts = crop_and_upload_slices(
                page_image_url=page_url,
                layouts=layouts,
                only_question_numbers=only_qnums,
                prefix=f"{base_prefix}p{page_idx}/",
            )
            slices_total = sum(len(v.slice_image_urls or []) for v in layouts.values())
            log_event(
                logger,
                "qindex_page_layouts_built",
                page_index=page_idx,
                task_id=task_id,
                task_status=task_status,
                blocks=len(blocks),
                layouts=len(layouts),
                slices=slices_total,
            )

            for qn, layout in layouts.items():
                entry = questions.get(qn) or {"question_number": qn, "pages": []}
                entry["pages"].append(
                    {
                        "page_index": page_idx,
                        "page_image_url": page_url,
                        "question_bboxes": [{"coords": b} for b in layout.bboxes_norm] if layout.bboxes_norm else [],
                        "slice_image_urls": layout.slice_image_urls,
                        "warnings": layout.warnings,
                        "ocr": {
                            "provider": ocr_provider_name,
                            "task_id": task_id,
                            "status": task_status,
                        },
                    }
                )
                questions[qn] = entry
            log_event(
                logger,
                "qindex_page_done",
                page_index=page_idx,
                status="ok",
                task_id=task_id,
                questions=len(layouts),
                slices=slices_total,
                elapsed_ms=int((time.monotonic() - t_page) * 1000),
            )
        except Exception as e:
            warnings.append(f"page[{page_idx}]: OCR/切片失败，改用整页：{str(e)}")
            log_event(
                logger,
                "qindex_page_done",
                level="warning",
                page_index=page_idx,
                status="error",
                page_image_url=redact_url(page_url),
                error_type=e.__class__.__name__,
                error=str(e),
                elapsed_ms=int((time.monotonic() - t_page) * 1000),
            )
            continue

    slices_total = 0
    try:
        for q in (questions or {}).values():
            for p in (q.get("pages") if isinstance(q, dict) else []) or []:
                if isinstance(p, dict):
                    slices_total += len(p.get("slice_image_urls") or [])
    except Exception:
        slices_total = None  # type: ignore[assignment]
    log_event(
        logger,
        "qindex_build_done",
        pages=len(page_urls or []),
        questions=len(questions),
        slices=slices_total,
        warnings=len(warnings),
        elapsed_ms=int((time.monotonic() - t_all) * 1000),
    )
    return {"questions": questions, "warnings": warnings}
