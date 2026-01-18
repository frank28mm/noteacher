from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Request,
    Header,
    BackgroundTasks,
    Response,
)

from homework_agent.models.schemas import (
    GradeRequest,
    GradeResponse,
    VisionProvider,
    Subject,
    ImageRef,
)
from homework_agent.services.vision_grade_agent import UnifiedGradeResult
from homework_agent.services.llm import MathGradingResult, EnglishGradingResult
from homework_agent.services.autonomous_agent import run_autonomous_grade_agent
from homework_agent.services.qindex_queue import enqueue_qindex_job
from homework_agent.services.grade_queue import enqueue_grade_job
from homework_agent.services.facts_queue import enqueue_facts_job
from homework_agent.utils.settings import get_settings
from homework_agent.core.qindex import qindex_is_configured
from homework_agent.core.qbank import (
    assign_stable_item_ids,
    build_question_bank,
    dedupe_wrong_items,
    normalize_questions,
    sanitize_wrong_items,
)
from homework_agent.core.slice_policy import should_create_slices_for_bank
from homework_agent.core.slice_policy import pick_question_numbers_for_slices
from homework_agent.api.session import (
    cache_store,
    save_mistakes,
    get_question_bank,
    save_question_index,
    save_grade_progress,
    persist_question_bank,
    save_qindex_placeholder,
    _merge_bank_meta,
    _ensure_session_id,
    IDP_TTL_HOURS,
)
from homework_agent.utils.observability import (
    get_request_id_from_headers,
    log_event,
    trace_span,
)
from homework_agent.utils.user_context import require_user_id
from homework_agent.utils.profile_context import require_profile_id
from homework_agent.utils.feature_flags import decide as decide_feature_flag
from homework_agent.utils.versioning import stable_json_hash, stable_text_hash
from homework_agent.utils.submission_store import (
    resolve_page_image_urls,
    touch_submission,
    update_submission_after_grade,
    link_session_to_submission,
)
from homework_agent.utils.url_image_helpers import (
    _is_public_url,
    _normalize_public_url,
    _strip_base64_prefix,
)
from homework_agent.services.high_risk import enforce_conservative_grading
from homework_agent.services.quota_service import (
    bt_from_usage,
    charge_bt_spendable,
    load_wallet,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 并发保护：防止线程池堆积导致“越跑越慢/无响应”
_settings_for_limits = get_settings()
VISION_SEMAPHORE = asyncio.Semaphore(
    max(1, int(_settings_for_limits.max_concurrent_vision))
)
LLM_SEMAPHORE = asyncio.Semaphore(max(1, int(_settings_for_limits.max_concurrent_llm)))
UNIFIED_AGENT_SEMAPHORE = asyncio.Semaphore(
    max(1, int(getattr(_settings_for_limits, "unified_agent_max_concurrency", 2)))
)
AUTONOMOUS_AGENT_SEMAPHORE = asyncio.Semaphore(
    max(1, int(getattr(_settings_for_limits, "autonomous_agent_max_concurrency", 2)))
)


async def _call_blocking_in_thread(
    fn,
    *args,
    timeout_seconds: float,
    semaphore: asyncio.Semaphore,
    **kwargs,
):
    """Run a blocking function in a thread with a timeout + concurrency guard."""
    async with semaphore:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs),
            timeout=timeout_seconds,
        )


# 常量
# 取消硬性 5 轮上限；仅保留计数用于提示递进


def _bank_has_visual_risk(bank: Any) -> bool:
    try:
        if not isinstance(bank, dict):
            return False
        qs = bank.get("questions")
        if not isinstance(qs, dict):
            return False
        return any(
            isinstance(q, dict) and q.get("visual_risk") is True for q in qs.values()
        )
    except Exception as e:
        logger.debug(f"_bank_has_visual_risk check failed: {e}")
        return False


def _visual_risk_warning_text() -> str:
    # Short, client-friendly.
    return "作业中有和图像有关的题目，建议生成切片以提升定位与辅导准确性。"


def _decide_autonomous_variant(
    *,
    settings: Any,
    experiment_key: str,
    request_id: Optional[str],
    session_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Decide P2 "canary/AB" for /grade and return:
      - experiments meta (persistable; for qbank/run_versions)
      - autonomous agent overrides (max_iterations/token_budget/timeout/confidence_threshold)
    """
    flags_json = str(getattr(settings, "feature_flags_json", "{}") or "{}")
    salt = str(getattr(settings, "feature_flags_salt", "ff_v1") or "ff_v1")
    key = (
        str(experiment_key or session_id or "").strip() or str(session_id or "").strip()
    )

    decision = decide_feature_flag(
        flags_json=flags_json, name="grade.autonomous_loop", key=key, salt=salt
    )
    exp: dict[str, Any] = {
        "grade.autonomous_loop": {
            "enabled": bool(decision.enabled),
            "variant": str(decision.variant or "") if decision.enabled else "",
            "reason": str(decision.reason or ""),
            "key": str(key),
        }
    }

    overrides: dict[str, Any] = {}
    if decision.enabled:
        variant = str(decision.variant or "").strip().lower()
        if variant in {"iter2", "iterations_2"}:
            overrides["max_iterations_override"] = 2
        elif variant in {"iter3", "iterations_3"}:
            overrides["max_iterations_override"] = 3
        elif variant in {"low_budget"}:
            overrides["token_budget_total_override"] = 8000
        elif variant in {"short_timeout"}:
            overrides["timeout_seconds_override"] = 300

    log_event(
        logger,
        "experiment_decision",
        request_id=request_id,
        session_id=session_id,
        experiments=exp,
    )
    return exp, overrides


@dataclass(frozen=True)
class _GradingAbort(Exception):
    """Internal control-flow: return a deterministic GradeResponse early."""

    response: GradeResponse


def _remaining_seconds(deadline_m: float) -> float:
    return max(0.0, float(deadline_m) - time.monotonic())


def _needs_fallback(result: Any) -> bool:
    """Detect Ark grading failure that should fall back to Qwen3."""
    summary = (getattr(result, "summary", "") or "").strip()
    if summary.startswith("批改失败") or summary.startswith("批改结果解析失败"):
        return True
    warnings = getattr(result, "warnings", None) or []
    for w in warnings:
        w_str = str(w)
        if any(
            key in w_str
            # Note: don't treat "Parse error" as fatal here because we may have already fallen back to Qwen3,
            # and we still want to return a successful grading result if the fallback succeeded.
            for key in ("InvalidEndpointOrModel", "NotFound", "Error code")
        ):
            return True
    return False


def validate_vision_provider(provider: VisionProvider) -> VisionProvider:
    """验证vision_provider是否在白名单中"""
    allowed_providers = [VisionProvider.QWEN3, VisionProvider.DOUBAO]
    if provider not in allowed_providers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid vision_provider. Allowed values: {[p.value for p in allowed_providers]}",
        )
    return provider


def validate_images_payload(
    images: List[Dict[str, Any]], vision_provider: VisionProvider
) -> None:
    """Early validation for /grade to reduce invalid calls."""
    if not images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Images cannot be empty"
        )
    for img in images:
        url = img.get("url")
        b64 = img.get("base64")
        if url:
            if not _is_public_url(url):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Image URL must be public HTTP/HTTPS (no localhost/127)",
                )
        elif b64:
            cleaned = _strip_base64_prefix(b64)
            est_bytes = int(len(cleaned) * 0.75)
            if est_bytes > 20 * 1024 * 1024:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Image size exceeds 20MB; use URL",
                )
            if vision_provider == VisionProvider.DOUBAO:
                # Ark/Doubao is URL-preferred but can accept data-url fallback (avoids provider-side URL fetch).
                if not str(b64).lstrip().lower().startswith("data:image/"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Doubao base64 must be a data URL (data:image/...;base64,...)",
                    )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Each image must provide url or base64",
            )


def generate_job_id() -> str:
    """生成任务ID"""
    return f"job_{uuid.uuid4().hex[:16]}"


def get_idempotency_key(
    request: Request, x_idempotency_key: Optional[str] = None
) -> Optional[str]:
    """获取幂等性键，只接受 Header。"""
    if x_idempotency_key:
        return x_idempotency_key.strip()
    return None


def check_idempotency(idempotency_key: str) -> Optional[GradeResponse]:
    """检查幂等性，如果存在则返回缓存结果"""
    cached = cache_store.get(f"idp:{idempotency_key}")
    if not cached:
        return None
    try:
        return GradeResponse(**cached["response"])
    except Exception as e:
        logger.debug(f"check_idempotency parse failed: {e}")
        return None


def _check_idempotency_or_raise(
    *, idempotency_key: str, fingerprint: str
) -> Optional[GradeResponse]:
    cached = cache_store.get(f"idp:{idempotency_key}")
    if not cached:
        return None
    try:
        cached_fp = str(
            (cached.get("fingerprint") if isinstance(cached, dict) else "") or ""
        )
        if cached_fp and cached_fp != str(fingerprint or ""):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Idempotency key conflict"
            )
        resp = cached.get("response") if isinstance(cached, dict) else None
        if not isinstance(resp, dict):
            return None
        return GradeResponse(**resp)
    except HTTPException:
        raise
    except Exception as e:
        logger.debug(f"_check_idempotency_or_raise parse failed: {e}")
        return None


def _idempotency_fingerprint(req: GradeRequest) -> str:
    """
    Stable fingerprint for idempotency key collision detection.
    Contract: same key + different params => 409.
    Keep it cheap: do not persist full base64 blobs.
    """
    try:
        imgs: List[Dict[str, Any]] = []
        for img in (req.images or [])[:10]:
            url = getattr(img, "url", None)
            b64 = getattr(img, "base64", None)
            if url:
                imgs.append({"url": str(url).strip()})
            elif b64:
                b64s = str(b64)
                imgs.append(
                    {
                        "base64_hash": stable_text_hash(b64s)[:16],
                        "base64_len": len(b64s),
                    }
                )
        payload = {
            "subject": getattr(req.subject, "value", str(req.subject)),
            "vision_provider": getattr(
                req.vision_provider, "value", str(req.vision_provider)
            ),
            "llm_provider": str(getattr(req, "llm_provider", None) or ""),
            "mode": str(getattr(req, "mode", None) or ""),
            "session_id": str(getattr(req, "session_id", None) or ""),
            "images": imgs,
        }
        return stable_json_hash(payload)
    except Exception:
        return stable_text_hash(repr(req))


def cache_response(
    idempotency_key: str, response: GradeResponse, *, fingerprint: str
) -> None:
    """缓存响应结果"""
    cache_store.set(
        f"idp:{idempotency_key}",
        {
            "response": response.model_dump(),
            "ts": datetime.now().isoformat(),
            "fingerprint": str(fingerprint or ""),
        },
        ttl_seconds=IDP_TTL_HOURS * 3600,
    )


VISION_OCR_START = "<<<OCR_TEXT>>>"
VISION_OCR_END = "<<<END_OCR_TEXT>>>"
VISION_FACTS_START = "<<<VISUAL_FACTS_JSON>>>"
VISION_FACTS_END = "<<<END_VISUAL_FACTS_JSON>>>"

GRADE_VISION_PROMPT = (
    "请同时输出【OCR识别原文】与【图形视觉事实】两部分，格式必须严格遵守（不要输出其它文本/Markdown）：\n"
    f"{VISION_OCR_START}\n"
    "请识别并提取作业内容，包括题目、答案和解题步骤。逐题输出“学生作答状态”：若看到答案/勾选则写明，若未看到答案/空白/未勾选，明确标注“未作答”或“可能未作答”。\n"
    "选择题必须完整列出选项（A/B/C/D 每一项的原文），并明确学生选择了哪个选项；若未勾选，标注未作答。\n"
    "对含幂/分式/下标的公式请双写：先按原式抄写（含上下标、分式），再给出纯文本展开形式（如 10^(n+1)、(a-b)^2/(c+d)）。\n"
    "特别自检指数/分母的 +1、±、平方/立方等细节，如有疑似误读，直接在结果中标注“可能误读公式：…”。\n"
    "对“规律/序列/图示题”（含箭头/示例/表格/图形），必须先原样抄写题目给出的示例（例如 A→B→C→D→C→B 或对应数字位置），不要凭空推断；若示例在图中，请描述图中出现的字母/顺序/位置关系。\n"
    "注意：你只负责识别与抄录，不要进行解题/判定/推理；不要写出你推断的正确答案或规律（例如“应为6n+3”这类）。如果示例/图中信息没识别出来，请明确写“示例未识别到/看不清”，并在 warnings 中标注风险。\n"
    f"{VISION_OCR_END}\n\n"
    f"{VISION_FACTS_START}\n"
    "输出严格 JSON（不要 extra 文本/Markdown），结构如下：\n"
    "{\n"
    '  "questions": {\n'
    '    "9": {\n'
    '      "scene_type": "math.geometry_2d|math.function_graph|...|unknown",\n'
    '      "figure_present": "true|false|unknown",\n'
    '      "confidence": 0.0,\n'
    '      "facts": {\n'
    '        "lines": [{"name":"AD","direction":"horizontal","relative":"above BC"}],\n'
    '        "points": [{"name":"A","relative":"left_of D; above B"}],\n'
    '        "angles": [{"name":"∠2","at":"D","between":["AD","DC"],"transversal_side":"left|right|unknown","between_lines":"true|false|unknown"}],\n'
    '        "labels": ["30° at C"],\n'
    '        "spatial": ["AD above BC"]\n'
    "      },\n"
    '      "hypotheses": [{"statement":"...","confidence":0.0,"evidence":["..."]}],\n'
    '      "unknowns": ["diagram_missing"],\n'
    '      "warnings": []\n'
    "    }\n"
    "  }\n"
    "}\n"
    "规则：\n"
    "- facts 只能客观描述（上/下/左/右/在XX之间/线段方向），不得输出“同位角/内错角/平行/垂直”等关系判定词。\n"
    "- 必须输出 figure_present（true/false/unknown），仅基于视觉识别，不做推断。\n"
    "- 如果看不清/不确定，写 UNKNOWN，并放入 unknowns。\n"
    "- 每道题都给一个对象；无图则 unknowns 包含 diagram_missing。\n"
    f"{VISION_FACTS_END}"
)


@dataclass
class _GradingCtx:
    session_id: str
    provider_str: str
    settings: Any
    started_m: float
    deadline_m: float
    timings_ms: Dict[str, int]
    request_id: Optional[str]
    meta_base: Dict[str, Any]
    page_image_urls: List[str]
    page_image_urls_original: List[str]


def _init_grading_ctx(req: GradeRequest, provider_str: str) -> _GradingCtx:
    """Initialize shared context for /grade execution (perform_grading + background_grade)."""
    session_id = _ensure_session_id(req.session_id or req.batch_id)
    try:
        # Best-effort: keep request/session aligned for downstream job records.
        req.session_id = session_id
    except Exception as e:
        logger.debug(f"Setting session_id on request failed: {e}")

    settings = get_settings()
    started_m = time.monotonic()
    deadline_m = started_m + float(settings.grade_completion_sla_seconds)
    timings_ms: Dict[str, int] = {}
    request_id = getattr(req, "_request_id", None)
    save_grade_progress(
        session_id, "grade_start", "已接收请求，准备识别…", {"request_id": request_id}
    )

    meta_base: Dict[str, Any] = {
        "vision_provider_requested": getattr(
            req.vision_provider, "value", str(req.vision_provider)
        ),
        "vision_provider_used": None,
        "vision_used_base64_fallback": False,
        "vision_used_proxy_url": False,
        "llm_provider_requested": provider_str,
        "llm_provider_used": None,
        "llm_used_fallback": False,
    }

    page_image_urls: List[str] = [
        v
        for img in (req.images or [])
        for v in [_normalize_public_url(getattr(img, "url", None))]
        if v
    ]
    return _GradingCtx(
        session_id=session_id,
        provider_str=provider_str,
        settings=settings,
        started_m=started_m,
        deadline_m=deadline_m,
        timings_ms=timings_ms,
        request_id=request_id,
        meta_base=meta_base,
        page_image_urls=page_image_urls,
        page_image_urls_original=list(page_image_urls),
    )


def _persist_done_qbank_snapshot(
    *,
    ctx: _GradingCtx,
    req: GradeRequest,
    grading_result: Any,
    vision_raw_text: str,
    visual_facts_map: Optional[Dict[str, Any]],
    page_image_urls: List[str],
    vision_fallback_warning: Optional[str],
) -> Optional[str]:
    """Persist question bank snapshot for chat routing; return optional extra warning."""
    if not ctx.session_id:
        return None

    questions_raw = getattr(grading_result, "questions", None)
    questions_list: List[Dict[str, Any]] = (
        questions_raw if isinstance(questions_raw, list) else []
    )
    bank = build_question_bank(
        session_id=ctx.session_id,
        subject=req.subject,
        questions=questions_list,
        vision_raw_text=vision_raw_text,
        page_image_urls=page_image_urls,
        visual_facts_map=visual_facts_map,
    )
    extra_warn = _visual_risk_warning_text() if _bank_has_visual_risk(bank) else None
    persist_question_bank(
        session_id=ctx.session_id,
        bank=_merge_bank_meta(bank, ctx.meta_base),
        grade_status="done",
        grade_summary=(getattr(grading_result, "summary", "") or "").strip(),
        grade_warnings=(getattr(grading_result, "warnings", None) or [])
        + ([vision_fallback_warning] if vision_fallback_warning else [])
        + ([extra_warn] if extra_warn else []),
        request_id=ctx.request_id,
        timings_ms=ctx.timings_ms,
    )
    return extra_warn


def _ensure_grading_counts(grading_result: Any) -> None:
    """Defensive: if LLM didn't output counts, compute from normalized results."""
    if getattr(grading_result, "wrong_count", None) is None:
        try:
            grading_result.wrong_count = len(
                getattr(grading_result, "wrong_items", []) or []
            )
        except Exception as e:
            logger.debug(f"Setting wrong_count failed: {e}")
            grading_result.wrong_count = None
    if getattr(grading_result, "total_items", None) is None:
        try:
            qs = getattr(grading_result, "questions", None) or []
            grading_result.total_items = (
                len(qs) if isinstance(qs, list) and qs else None
            )
        except Exception as e:
            logger.debug(f"Setting total_items failed: {e}")
            grading_result.total_items = None


def _build_grading_result_from_unified(
    *,
    unified: UnifiedGradeResult,
    subject: Subject,
) -> Any:
    """Convert unified agent output into Math/English grading result objects."""
    results = unified.results or []
    wrong_items: List[Dict[str, Any]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        verdict = (r.get("verdict") or "").strip().lower()
        if verdict != "correct":
            wrong_items.append(
                {
                    "question_number": r.get("question_number"),
                    "question_content": r.get("question_content"),
                    "student_answer": r.get("student_answer"),
                    "reason": r.get("reason"),
                    "judgment_basis": r.get("judgment_basis"),
                    "warnings": r.get("warnings") or [],
                    "knowledge_tags": r.get("knowledge_tags") or [],
                    "math_steps": r.get("math_steps") or r.get("steps"),
                    "geometry_check": r.get("geometry_check"),
                    "cross_subject_flag": r.get("cross_subject_flag"),
                }
            )

    wrong_items = sanitize_wrong_items(wrong_items)
    wrong_items = dedupe_wrong_items(wrong_items)
    wrong_items = assign_stable_item_ids(wrong_items)

    total_items = len(results) if isinstance(results, list) else None
    wrong_count = len(wrong_items)
    summary = unified.summary or "批改完成"

    if subject == Subject.ENGLISH:
        return EnglishGradingResult(
            wrong_items=wrong_items,
            questions=results,
            summary=summary,
            total_items=total_items,
            wrong_count=wrong_count,
            cross_subject_flag=None,
            warnings=unified.warnings or [],
        )

    return MathGradingResult(
        wrong_items=wrong_items,
        questions=results,
        summary=summary,
        total_items=total_items,
        wrong_count=wrong_count,
        cross_subject_flag=None,
        warnings=unified.warnings or [],
    )


def _build_grading_result_from_autonomous(
    *,
    autonomous: Any,
    subject: Subject,
) -> Any:
    results = normalize_questions(autonomous.results or [])
    wrong_items: List[Dict[str, Any]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        verdict = (r.get("verdict") or "").strip().lower()
        if verdict != "incorrect":
            continue
        wrong_items.append(
            {
                "question_number": r.get("question_number"),
                "question_content": r.get("question_content"),
                "student_answer": r.get("student_answer"),
                "reason": r.get("reason"),
                "judgment_basis": r.get("judgment_basis"),
                "warnings": r.get("warnings") or [],
                "knowledge_tags": r.get("knowledge_tags") or [],
                "math_steps": r.get("math_steps") or r.get("steps"),
                "geometry_check": r.get("geometry_check"),
                "cross_subject_flag": r.get("cross_subject_flag"),
            }
        )

    wrong_items = sanitize_wrong_items(wrong_items)
    wrong_items = dedupe_wrong_items(wrong_items)
    wrong_items = assign_stable_item_ids(wrong_items)

    total_items = len(results) if isinstance(results, list) else None
    wrong_count = len(wrong_items)
    summary = autonomous.summary or "批改完成"

    if subject == Subject.ENGLISH:
        return EnglishGradingResult(
            wrong_items=wrong_items,
            questions=results,
            summary=summary,
            total_items=total_items,
            wrong_count=wrong_count,
            cross_subject_flag=None,
            warnings=autonomous.warnings or [],
        )
    return MathGradingResult(
        wrong_items=wrong_items,
        questions=results,
        summary=summary,
        total_items=total_items,
        wrong_count=wrong_count,
        cross_subject_flag=None,
        warnings=autonomous.warnings or [],
    )


def _log_grade_done(*, ctx: _GradingCtx, grading_result: Any) -> None:
    log_event(
        logger,
        "grade_done",
        request_id=ctx.request_id,
        session_id=ctx.session_id,
        status="done",
        vision_provider=ctx.meta_base.get("vision_provider_used"),
        llm_provider=ctx.meta_base.get("llm_provider_used"),
        llm_used_fallback=ctx.meta_base.get("llm_used_fallback"),
        timings_ms=ctx.timings_ms,
        wrong_count=getattr(grading_result, "wrong_count", None),
        total_items=getattr(grading_result, "total_items", None),
    )


def _build_done_grade_response(
    *,
    ctx: _GradingCtx,
    req: GradeRequest,
    grading_result: Any,
    vision_raw_text: str,
    visual_facts_map: Optional[Dict[str, Any]],
    figure_present_map: Optional[Dict[str, str]],
    vision_fallback_warning: Optional[str],
    extra_warn: Optional[str],
    visual_facts_warn: Optional[str],
) -> GradeResponse:
    return GradeResponse(
        wrong_items=grading_result.wrong_items,
        summary=grading_result.summary,
        subject=req.subject,
        job_id=None,
        session_id=ctx.session_id,
        status="done",
        total_items=grading_result.total_items,
        wrong_count=grading_result.wrong_count,
        cross_subject_flag=grading_result.cross_subject_flag,
        warnings=(
            (grading_result.warnings or [])
            + ([vision_fallback_warning] if vision_fallback_warning else [])
            + ([visual_facts_warn] if visual_facts_warn else [])
            + ([extra_warn] if ctx.session_id and extra_warn else [])
        ),
        vision_raw_text=vision_raw_text,
        visual_facts=visual_facts_map or None,
        figure_present=figure_present_map,
        questions=getattr(grading_result, "questions", None),
    )


async def _perform_autonomous_grading(
    req: GradeRequest,
    provider_str: str,
    *,
    experiment_key: Optional[str] = None,
) -> GradeResponse:
    """Run the autonomous agent loop and map to GradeResponse."""
    ctx = _init_grading_ctx(req, provider_str)
    experiments_meta, overrides = _decide_autonomous_variant(
        settings=ctx.settings,
        experiment_key=str(experiment_key or ctx.session_id),
        request_id=ctx.request_id,
        session_id=ctx.session_id,
    )
    ctx.meta_base["experiments"] = experiments_meta
    grade_variant = getattr(req, "_grade_image_input_variant", None)
    if isinstance(grade_variant, str) and grade_variant.strip():
        ctx.meta_base["grade_image_input_variant"] = grade_variant.strip()
    save_grade_progress(
        ctx.session_id, "vision_start", "自主阅卷中（规划→工具→反思）…", None
    )
    log_event(
        logger,
        "autonomous_grade_start",
        request_id=ctx.request_id,
        session_id=ctx.session_id,
        provider=provider_str,
        subject=getattr(req.subject, "value", str(req.subject)),
        images=len(req.images or []),
    )

    async with AUTONOMOUS_AGENT_SEMAPHORE:
        try:
            autonomous = await run_autonomous_grade_agent(
                images=req.images,
                subject=req.subject,
                provider=provider_str,
                session_id=ctx.session_id,
                request_id=ctx.request_id,
                experiments=experiments_meta,
                grade_image_input_variant=(
                    grade_variant.strip()
                    if isinstance(grade_variant, str) and grade_variant.strip()
                    else None
                ),
                **overrides,
            )
            tms = getattr(autonomous, "timings_ms", None)
            if isinstance(tms, dict):
                ctx.timings_ms.update({k: v for k, v in tms.items() if v is not None})
            llm_trace = getattr(autonomous, "llm_trace", None)
            if isinstance(llm_trace, dict):
                ark_response_id = llm_trace.get("ark_response_id")
                if isinstance(ark_response_id, str) and ark_response_id.strip():
                    rid = ark_response_id.strip()
                    ctx.meta_base["ark_response_id"] = rid
                    log_event(
                        logger,
                        "grade_ark_response_id",
                        request_id=ctx.request_id,
                        session_id=ctx.session_id,
                        response_id=rid,
                    )
                llm_usage = llm_trace.get("llm_usage")
                if isinstance(llm_usage, dict):
                    ctx.meta_base["llm_usage"] = {
                        "prompt_tokens": int(llm_usage.get("prompt_tokens") or 0),
                        "completion_tokens": int(llm_usage.get("completion_tokens") or 0),
                        "total_tokens": int(llm_usage.get("total_tokens") or 0),
                    }
                llm_model = llm_trace.get("llm_model")
                if isinstance(llm_model, str) and llm_model.strip():
                    ctx.meta_base["llm_model"] = llm_model.strip()
                llm_provider = llm_trace.get("llm_provider")
                if isinstance(llm_provider, str) and llm_provider.strip():
                    ctx.meta_base["llm_provider"] = llm_provider.strip()
                if "ark_image_process_requested" in llm_trace:
                    ctx.meta_base["ark_image_process_requested"] = bool(
                        llm_trace.get("ark_image_process_requested")
                    )
                ctx.meta_base["ark_image_process_enabled"] = bool(
                    getattr(ctx.settings, "ark_image_process_enabled", False)
                )
        except Exception as e:
            log_event(
                logger,
                "autonomous_grade_failed",
                level="warning",
                request_id=ctx.request_id,
                session_id=ctx.session_id,
                error_type=e.__class__.__name__,
                error=str(e),
            )
            save_grade_progress(ctx.session_id, "failed", "批改失败", {"error": str(e)})
            return GradeResponse(
                wrong_items=[],
                summary="批改失败",
                subject=req.subject,
                job_id=None,
                session_id=ctx.session_id,
                status="failed",
                total_items=None,
                wrong_count=None,
                cross_subject_flag=None,
                warnings=[f"autonomous_agent_error: {e}"],
                vision_raw_text=None,
                questions=[],
            )

    if autonomous.status == "rejected":
        save_grade_progress(
            ctx.session_id, "failed", "输入非作业图片，已拒绝批改", None
        )
        return GradeResponse(
            wrong_items=[],
            summary=autonomous.summary,
            subject=req.subject,
            job_id=None,
            session_id=ctx.session_id,
            status="rejected",
            total_items=None,
            wrong_count=None,
            cross_subject_flag=None,
            warnings=[autonomous.reason or "not_homework"],
            vision_raw_text=autonomous.ocr_text,
            questions=[],
        )

    grading_result = _build_grading_result_from_autonomous(
        autonomous=autonomous, subject=req.subject
    )

    # T3: Quality Gate (Conservative Correctness)
    # Downgrade 'correct' to 'uncertain' if risks are detected (e.g. OCR failure)
    gate_warnings = enforce_conservative_grading(
        grading_result, autonomous.warnings or []
    )
    if gate_warnings:
        # Apply gate warnings to the grading result (used for response + qbank snapshot).
        # NOTE: Do not touch FastAPI `Response` here; this function is also used by workers.
        if not hasattr(grading_result, "warnings"):
            grading_result.warnings = []
        grading_result.warnings.extend(gate_warnings)

    extra_warn = _persist_done_qbank_snapshot(
        ctx=ctx,
        req=req,
        grading_result=grading_result,
        vision_raw_text=autonomous.ocr_text,
        visual_facts_map=None,
        page_image_urls=ctx.page_image_urls,
        vision_fallback_warning=None,
    )

    _ensure_grading_counts(grading_result)
    _log_grade_done(ctx=ctx, grading_result=grading_result)
    save_grade_progress(
        ctx.session_id, "done", "批改结果已生成", {"timings_ms": ctx.timings_ms}
    )

    return _build_done_grade_response(
        ctx=ctx,
        req=req,
        grading_result=grading_result,
        vision_raw_text=autonomous.ocr_text,
        visual_facts_map=None,
        figure_present_map=None,
        vision_fallback_warning=None,
        extra_warn=extra_warn,
        visual_facts_warn=None,
    )


@trace_span("grade.perform_grading")
async def perform_grading(
    req: GradeRequest, provider_str: str, *, experiment_key: Optional[str] = None
) -> GradeResponse:
    """执行批改（同步/后台共用），统一走 Autonomous Agent。"""
    return await _perform_autonomous_grading(
        req, provider_str, experiment_key=experiment_key
    )


async def background_grade(job_id: str, req: GradeRequest, provider_str: str):
    """后台执行批改，更新 job_cache。"""
    try:
        result = await perform_grading(req, provider_str)
        cache_store.set(
            f"job:{job_id}",
            {
                "status": "done",
                "created_at": datetime.now().isoformat(),
                "request": req.model_dump(),
                "result": result.model_dump(),
                "finished_at": datetime.now().isoformat(),
            },
            ttl_seconds=IDP_TTL_HOURS * 3600,
        )
    except Exception as e:
        cache_store.set(
            f"job:{job_id}",
            {
                "status": "failed",
                "created_at": datetime.now().isoformat(),
                "request": req.model_dump(),
                "result": None,
                "error": str(e),
                "finished_at": datetime.now().isoformat(),
            },
            ttl_seconds=IDP_TTL_HOURS * 3600,
        )


def background_build_question_index(session_id: str, page_urls: List[str]) -> None:
    """Deprecated: qindex is handled by an external worker (see `qindex_queue.py`)."""
    logger.warning(
        "background_build_question_index called but is deprecated; session_id=%s pages=%s",
        session_id,
        len(page_urls or []),
    )
    return None


def validate_images(images: List[Any], provider: VisionProvider):
    """Early validation of image inputs to fail fast."""
    for idx, img in enumerate(images):
        if img.url:
            url_str = str(img.url)
            if not (url_str.startswith("http://") or url_str.startswith("https://")):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: URL must be HTTP/HTTPS",
                )
            if "localhost" in url_str or "127.0.0.1" in url_str:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: URL must be public (no localhost/127)",
                )
        elif img.base64:
            if provider == VisionProvider.DOUBAO:
                # Prefer URLs, but allow Data URL base64 as an internal fallback (avoids provider-side URL fetch).
                if not str(img.base64).lstrip().lower().startswith("data:image/"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Image index {idx}: Doubao base64 must be a data URL (data:image/...;base64,...)",
                    )
            # Estimate size: len * 0.75
            est_size = len(img.base64) * 0.75
            if est_size > 20 * 1024 * 1024:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image index {idx}: Base64 image too large (>20MB), please use URL",
                )


def _resolve_images_from_upload_id(
    upload_id: str,
    *,
    user_id: str,
    profile_id: Optional[str] = None,
    prefer_proxy: bool = True,
) -> List[str]:
    """
    Backward-compatible name: we treat upload_id as submission_id (one upload == one Submission).
    Resolve canonical page_image_urls from Supabase Postgres.
    """
    return [
        str(u).strip()
        for u in (
            resolve_page_image_urls(
                user_id=user_id,
                profile_id=profile_id,
                submission_id=str(upload_id),
                prefer_proxy=bool(prefer_proxy),
            )
            or []
        )
        if str(u).strip()
    ]


@router.post("/grade", response_model=GradeResponse, status_code=status.HTTP_200_OK)
async def grade_homework(
    req: GradeRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_profile_id: Optional[str] = Header(None, alias="X-Profile-Id"),
    x_force_async: Optional[str] = Header(None, alias="X-Force-Async"),
    x_grade_image_input_variant: Optional[str] = Header(
        None, alias="X-Grade-Image-Input-Variant"
    ),
):
    """
    批改作业 API (Stub)
    """
    # 1. Resolve images (optional upload_id) + Early Validation
    user_id = require_user_id(
        authorization=request.headers.get("Authorization"), x_user_id=x_user_id
    )
    profile_id = require_profile_id(user_id=user_id, x_profile_id=x_profile_id)
    settings = get_settings()
    # WS-E: Quota enforcement is enabled when we're not in pure dev auth mode.
    if str(getattr(settings, "auth_mode", "dev") or "dev").strip().lower() != "dev":
        wallet = load_wallet(user_id=user_id)
        if not wallet or wallet.bt_spendable <= 0:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="quota_insufficient",
            )
    upload_id = (getattr(req, "upload_id", None) or "").strip()

    variant_raw = (
        (x_grade_image_input_variant or "").strip()
        or str(getattr(settings, "grade_image_input_variant", "") or "").strip()
        or "auto"
    )
    grade_image_input_variant = str(variant_raw).strip().lower() or "auto"
    allowed_variants = {
        "auto",
        "url",
        "proxy",
        "data_url_first_page",
        "data_url_on_small_figure",
    }
    if grade_image_input_variant not in allowed_variants:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Grade-Image-Input-Variant (allowed: {sorted(allowed_variants)})",
        )
    prefer_proxy = grade_image_input_variant != "url"
    try:
        setattr(req, "_grade_image_input_variant", grade_image_input_variant)
    except Exception as e:
        logger.debug(f"Setting _grade_image_input_variant on request failed: {e}")

    if upload_id and not (req.images or []):
        urls = _resolve_images_from_upload_id(
            upload_id, user_id=user_id, profile_id=profile_id, prefer_proxy=prefer_proxy
        )
        if not urls:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="upload_id not found for this user",
            )
        req = req.model_copy(update={"images": [ImageRef(url=u) for u in urls]})

    if not (req.images or []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Images cannot be empty (provide images or upload_id)",
        )

    validate_images(req.images, req.vision_provider)

    request_id = getattr(
        getattr(request, "state", None), "request_id", None
    ) or get_request_id_from_headers(request.headers)
    if not request_id:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
    try:
        setattr(req, "_request_id", request_id)
    except Exception as e:
        logger.debug(f"Setting request_id on request failed: {e}")
    log_event(
        logger,
        "grade_request",
        request_id=request_id,
        session_id=req.session_id or req.batch_id,
        user_id=user_id,
        upload_id=upload_id or None,
        subject=getattr(req.subject, "value", str(req.subject)),
        images=len(req.images or []),
        vision_provider=getattr(req.vision_provider, "value", str(req.vision_provider)),
        has_idempotency=bool(x_idempotency_key),
        grade_image_input_variant=grade_image_input_variant,
    )

    # Best-effort: touch Submission last_active_at (180-day inactivity cleanup uses this).
    if upload_id:
        try:
            touch_submission(user_id=user_id, profile_id=profile_id, submission_id=upload_id)
        except Exception as e:
            logger.debug(f"touch_submission failed (best-effort): {e}")

    # 2. 幂等性校验
    idempotency_key = get_idempotency_key(None, x_idempotency_key)
    if idempotency_key:
        fp = _idempotency_fingerprint(req)
        cached_response = _check_idempotency_or_raise(
            idempotency_key=idempotency_key, fingerprint=fp
        )
        if cached_response:
            log_event(
                logger,
                "grade_idempotency_hit",
                request_id=request_id,
                idempotency_key=idempotency_key,
            )
            return cached_response

    # 2.5 Ensure session_id is always present so results can be delivered to /chat
    session_for_ctx = _ensure_session_id(req.session_id or req.batch_id)
    req = req.model_copy(update={"session_id": session_for_ctx})
    save_grade_progress(
        session_for_ctx, "accepted", "已开始处理…", {"request_id": request_id}
    )

    # Best-effort: link session_id back to durable Submission for later history/chat mapping.
    if upload_id:
        try:
            subj = (
                req.subject.value if hasattr(req.subject, "value") else str(req.subject)
            )
            link_session_to_submission(
                user_id=user_id,
                submission_id=upload_id,
                session_id=session_for_ctx,
                subject=subj,
            )
        except Exception as e:
            logger.debug(f"link_session_to_submission failed (best-effort): {e}")

    # 3. 决定同步/异步
    force_async = str(x_force_async or "").strip().lower() in {"1", "true", "yes"}
    is_large_batch = len(req.images) > 5 or force_async
    # LLM provider: use explicit llm_provider if set, else derive from vision_provider
    if req.llm_provider:
        provider_str = req.llm_provider  # "ark" or "silicon"
    else:
        provider_str = (
            "silicon" if req.vision_provider == VisionProvider.QWEN3 else "ark"
        )
    log_event(
        logger,
        "grade_request_start",
        request_id=request_id,
        session_id=session_for_ctx,
        subject=getattr(req.subject, "value", str(req.subject)),
        images=len(req.images or []),
        provider=provider_str,
        upload_id=upload_id,
        grade_image_input_variant=grade_image_input_variant,
    )

    if is_large_batch:
        response.status_code = status.HTTP_202_ACCEPTED
        job_id = generate_job_id()
        ttl_seconds = int(IDP_TTL_HOURS * 3600)
        queued = False
        require_redis = os.getenv("REQUIRE_REDIS", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        try:
            queued = enqueue_grade_job(
                job_id=job_id,
                grade_request=req.model_dump(),
                provider=provider_str,
                request_id=request_id,
                session_id=session_for_ctx,
                user_id=user_id,
                ttl_seconds=ttl_seconds,
                grade_image_input_variant=grade_image_input_variant,
                idempotency_key=idempotency_key or request_id,
            )
        except Exception as e:
            if require_redis:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Redis grade queue unavailable (REQUIRE_REDIS=1): {e}",
                )
            logger.debug(f"enqueue_grade_job failed: {e}")
            queued = False

        if require_redis and not queued:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Redis grade queue unavailable (REQUIRE_REDIS=1)",
            )

        if not queued:
            # Dev fallback: keep old in-process BackgroundTasks behavior when Redis is unavailable.
            cache_store.set(
                f"job:{job_id}",
                {
                    "status": "processing",
                    "created_at": datetime.now().isoformat(),
                    "request": req.model_dump(),
                    "result": None,
                },
                ttl_seconds=ttl_seconds,
            )
            background_tasks.add_task(background_grade, job_id, req, provider_str)
            log_event(
                logger,
                "grade_async_enqueued",
                request_id=request_id,
                session_id=session_for_ctx,
                job_id=job_id,
                images=len(req.images or []),
                mode="background_tasks_fallback",
            )
        else:
            log_event(
                logger,
                "grade_async_enqueued",
                request_id=request_id,
                session_id=session_for_ctx,
                job_id=job_id,
                images=len(req.images or []),
                mode="redis_queue",
            )
        return GradeResponse(
            wrong_items=[],
            summary="任务已创建，正在处理中...",
            subject=req.subject,
            job_id=job_id,
            session_id=session_for_ctx,
            status="processing",
            total_items=None,
            wrong_count=None,
            cross_subject_flag=None,
            warnings=["大批量任务已转为异步处理"],
            vision_raw_text=None,
            figure_present=None,
        )

    try:
        response = await perform_grading(req, provider_str, experiment_key=user_id)

        # Best-effort: persist Submission facts to Supabase Postgres (long-term "hard disk").
        # We treat upload_id as submission_id.
        if upload_id:
            try:
                bank_now = (
                    get_question_bank(session_for_ctx) if session_for_ctx else None
                )
                meta_now = (
                    (bank_now or {}).get("meta") if isinstance(bank_now, dict) else None
                )
                meta_now = meta_now if isinstance(meta_now, dict) else {}
                page_urls_now = (
                    (bank_now or {}).get("page_image_urls")
                    if isinstance(bank_now, dict)
                    else None
                )
                page_urls_now = (
                    page_urls_now if isinstance(page_urls_now, list) else None
                )
                proxy_urls_now = meta_now.get("page_image_urls_proxy")
                proxy_urls_now = (
                    proxy_urls_now if isinstance(proxy_urls_now, list) else None
                )

                subj = (
                    req.subject.value
                    if hasattr(req.subject, "value")
                    else str(req.subject)
                )
                db_start = time.monotonic()
                update_submission_after_grade(
                    user_id=user_id,
                    submission_id=upload_id,
                    session_id=session_for_ctx,
                    profile_id=profile_id,
                    request_id=request_id,
                    subject=subj,
                    page_image_urls=(
                        [str(u) for u in (page_urls_now or []) if str(u).strip()]
                        if page_urls_now
                        else None
                    ),
                    proxy_page_image_urls=(
                        [str(u) for u in (proxy_urls_now or []) if str(u).strip()]
                        if proxy_urls_now
                        else None
                    ),
                    vision_raw_text=getattr(response, "vision_raw_text", None),
                    grade_result=(
                        response.model_dump() if hasattr(response, "model_dump") else {}
                    ),
                    warnings=list(getattr(response, "warnings", None) or []),
                    meta=(
                        {k: v for k, v in meta_now.items() if v is not None}
                        if isinstance(meta_now, dict)
                        else None
                    ),
                )
                log_event(
                    logger,
                    "submission_grade_persist_done",
                    request_id=request_id,
                    session_id=session_for_ctx,
                    submission_id=upload_id,
                    elapsed_ms=int((time.monotonic() - db_start) * 1000),
                )
                try:
                    enqueue_facts_job(
                        submission_id=upload_id,
                        user_id=user_id,
                        session_id=session_for_ctx,
                        request_id=request_id,
                    )
                except Exception as e:
                    logger.debug(f"enqueue_facts_job failed (best-effort): {e}")
            except Exception as e:
                logger.debug(
                    f"update_submission_grade_result failed (best-effort): {e}"
                )

        if session_for_ctx:
            wrong_items_payload: List[Dict[str, Any]] = []
            for item in response.wrong_items or []:
                if hasattr(item, "model_dump"):
                    wrong_items_payload.append(item.model_dump())
                elif isinstance(item, dict):
                    wrong_items_payload.append(item)
                else:
                    # last resort: attempt dict() conversion
                    try:
                        wrong_items_payload.append(dict(item))
                    except Exception as e:
                        logger.debug(f"dict conversion for wrong_item failed: {e}")
                        continue
            save_mistakes(session_for_ctx, wrong_items_payload)
            # QIndex: optional background optimization (bbox/slice).
            # Product decision: keep grading fast/stable by default; only run qindex when user explicitly requests it
            # (e.g. from Question Detail "生成图示切片") or when AUTO_QINDEX_ON_GRADE=1 is set.
            auto_qindex = str(os.getenv("AUTO_QINDEX_ON_GRADE", "0") or "0").strip() in {
                "1",
                "true",
                "yes",
            }
            bank = get_question_bank(session_for_ctx) if session_for_ctx else None
            page_urls = None
            if isinstance(bank, dict):
                pu = bank.get("page_image_urls")
                if isinstance(pu, list):
                    page_urls = [str(u) for u in pu if str(u).strip()]
            if not page_urls:
                page_urls = [
                    str(img.url) for img in req.images if getattr(img, "url", None)
                ]
            must_slice = False
            try:
                must_slice = _visual_risk_warning_text() in (response.warnings or [])
            except Exception as e:
                logger.debug(f"Checking visual risk warning failed: {e}")
                must_slice = False
            if (
                auto_qindex
                and page_urls
                and isinstance(bank, dict)
                and (should_create_slices_for_bank(bank) or must_slice)
            ):
                ok, reason = qindex_is_configured()
                if not ok:
                    save_qindex_placeholder(
                        session_for_ctx, f"qindex skipped: {reason}"
                    )
                else:
                    allow = pick_question_numbers_for_slices(bank)
                    if not allow:
                        # Safety: if we decided to slice but couldn't pick, fall back to all questions.
                        try:
                            qs = bank.get("questions")
                            if isinstance(qs, dict):
                                allow = [str(k) for k in qs.keys() if str(k).strip()]
                        except Exception as e:
                            logger.debug(
                                f"Fallback question number extraction failed: {e}"
                            )
                            allow = []
                    enqueued = enqueue_qindex_job(
                        session_for_ctx,
                        [
                            v
                            for u in page_urls
                            for v in [_normalize_public_url(str(u))]
                            if v
                        ],
                        question_numbers=allow,
                        request_id=request_id,
                    )
                    if enqueued:
                        save_question_index(
                            session_for_ctx,
                            {"questions": {}, "warnings": ["qindex queued"]},
                        )
                    else:
                        save_qindex_placeholder(
                            session_for_ctx, "qindex skipped: redis_unavailable"
                        )

        # WS-E: bill grade by LLM usage (BT = prompt + 10 * completion).
        if str(getattr(settings, "auth_mode", "dev") or "dev").strip().lower() != "dev":
            try:
                bank_now = get_question_bank(session_for_ctx) if session_for_ctx else None
                meta_now = (bank_now or {}).get("meta") if isinstance(bank_now, dict) else None
                meta_now = meta_now if isinstance(meta_now, dict) else {}
                usage = meta_now.get("llm_usage") if isinstance(meta_now, dict) else None
                if isinstance(usage, dict):
                    bt_cost = bt_from_usage(
                        prompt_tokens=int(usage.get("prompt_tokens") or 0),
                        completion_tokens=int(usage.get("completion_tokens") or 0),
                    )
                    ok, err = charge_bt_spendable(
                        user_id=user_id,
                        bt_cost=int(bt_cost),
                        idempotency_key=idempotency_key or request_id,
                        request_id=request_id,
                        endpoint="/api/v1/grade",
                        stage="grade",
                        model=str(meta_now.get("llm_model") or "") or None,
                        usage={
                            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                            "completion_tokens": int(usage.get("completion_tokens") or 0),
                            "total_tokens": int(usage.get("total_tokens") or 0),
                        },
                    )
                    if not ok:
                        log_event(
                            logger,
                            "quota_charge_failed",
                            level="warning",
                            request_id=request_id,
                            session_id=session_for_ctx,
                            user_id=user_id,
                            endpoint="/api/v1/grade",
                            stage="grade",
                            error=str(err or ""),
                        )
                else:
                    log_event(
                        logger,
                        "quota_usage_missing",
                        level="warning",
                        request_id=request_id,
                        session_id=session_for_ctx,
                        user_id=user_id,
                        endpoint="/api/v1/grade",
                        stage="grade",
                    )
            except Exception as e:
                log_event(
                    logger,
                    "quota_charge_exception",
                    level="warning",
                    request_id=request_id,
                    session_id=session_for_ctx,
                    user_id=user_id,
                    endpoint="/api/v1/grade",
                    stage="grade",
                    error_type=e.__class__.__name__,
                    error=str(e),
                )
        if idempotency_key:
            cache_response(
                idempotency_key, response, fingerprint=_idempotency_fingerprint(req)
            )
        return response
    except HTTPException:
        raise
    except Exception as e:
        save_grade_progress(
            session_for_ctx,
            "failed",
            f"系统错误：{str(e)}",
            {"error_type": e.__class__.__name__},
        )
        log_event(
            logger,
            "grade_failed",
            level="error",
            request_id=request_id,
            session_id=session_for_ctx,
            error_type=e.__class__.__name__,
            error=str(e),
        )
        # Do not leak internal errors to clients; keep details in logs only.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
