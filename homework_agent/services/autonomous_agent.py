from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict

from homework_agent.core.prompts_autonomous import (
    PROMPT_VERSION,
    PLANNER_SYSTEM_PROMPT,
    REFLECTOR_SYSTEM_PROMPT,
    AGGREGATOR_SYSTEM_PROMPT_MATH,
    AGGREGATOR_SYSTEM_PROMPT_ENGLISH,
    build_planner_user_prompt,
    build_reflector_user_prompt,
    build_aggregator_user_prompt,
)
from homework_agent.models.schemas import ImageRef, Subject
from homework_agent.services.llm import LLMClient, _repair_json_text
from homework_agent.services.preprocessing import PreprocessingPipeline
from homework_agent.services.session_state import SessionState, get_session_store
from homework_agent.services.autonomous_tools import (
    diagram_slice,
    qindex_fetch,
    vision_roi_detect,
    math_verify,
    ocr_fallback,
    _compress_image_if_needed,
    _compress_image_if_needed_with_metrics,
    _compute_image_hash,
)
from homework_agent.models.tool_result import ToolResult
from homework_agent.utils.observability import log_event, log_llm_usage, trace_span
from homework_agent.utils.settings import get_settings
from homework_agent.utils.budget import RunBudget
from homework_agent.utils.versioning import stable_json_hash
from homework_agent.utils.url_image_helpers import _download_as_data_uri

logger = logging.getLogger("homework_agent.autonomous")
planner_logger = logging.getLogger("homework_agent.autonomous.planner")
executor_logger = logging.getLogger("homework_agent.autonomous.executor")
reflector_logger = logging.getLogger("homework_agent.autonomous.reflector")
aggregator_logger = logging.getLogger("homework_agent.autonomous.aggregator")


def _is_rate_limit_error(err: Exception) -> bool:
    msg = str(err or "").lower()
    return any(
        s in msg for s in ("429", "rate limit", "tpm limit", "too many requests")
    )


async def _call_llm_with_backoff(
    fn, *, timeout_s: float, retries: int = 2, base_delay: float = 1.0
):
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout_s)
        except Exception as e:
            if _is_rate_limit_error(e) and attempt < retries:
                await asyncio.sleep(base_delay * (2**attempt))
                continue
            raise


class PlannerPayload(BaseModel):
    thoughts: Optional[str] = None
    plan: List[Dict[str, Any]] = Field(default_factory=list)
    action: Optional[str] = None


class ReflectorPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    pass_: bool = Field(..., alias="pass")
    issues: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    suggestion: Optional[str] = None


class AutonomousPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: Optional[str] = None
    reason: Optional[str] = None
    ocr_text: Optional[str] = None
    results: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


@dataclass
class AutonomousGradeResult:
    status: str
    reason: Optional[str]
    ocr_text: str
    results: List[Dict[str, Any]]
    summary: str
    warnings: List[str]
    iterations: int
    tokens_used: Optional[int] = None
    duration_ms: Optional[int] = None
    needs_review: Optional[bool] = None
    llm_trace: Optional[Dict[str, Any]] = None
    timings_ms: Optional[Dict[str, int]] = None


def _normalize_verdict(v: Any) -> str:
    s = str(v or "").strip().lower()
    if s in {"correct", "incorrect", "uncertain"}:
        return s
    if s in {"wrong", "error"}:
        return "incorrect"
    return "uncertain"


def _ensure_judgment_basis(result: Dict[str, Any], *, min_len: int) -> None:
    basis = result.get("judgment_basis")
    if not isinstance(basis, list) or not basis:
        result["judgment_basis"] = ["依据来源：图像+题干综合判断"]
        return
    out = [str(b).strip() for b in basis if str(b).strip()]
    if not any("依据来源" in b for b in out):
        out = ["依据来源：图像+题干综合判断"] + out
    if min_len > 0 and len(out) < min_len:
        out = out + ["依据题干与作答进行判断"]
    result["judgment_basis"] = out


def _parse_json(text: str, model: Any) -> Optional[Any]:
    if not text:
        return None
    raw = str(text)
    try:
        data = json.loads(raw)
        return model.model_validate(data)
    except Exception:
        repaired = _repair_json_text(raw)
        if not repaired:
            return None
        try:
            data = json.loads(repaired)
            return model.model_validate(data)
        except Exception:
            return None


def _dedupe_images(images: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for u in images or []:
        s = str(u or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


class PlannerAgent:
    def __init__(
        self, llm: LLMClient, provider: str, max_tokens: int, timeout_s: float
    ) -> None:
        self.llm = llm
        self.provider = provider
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s

    async def run(
        self,
        state: SessionState,
        *,
        request_id: Optional[str] = None,
        budget: Optional[RunBudget] = None,
        min_reserve_s: float = 0.0,
    ) -> PlannerPayload:
        payload = json.dumps(
            {
                "image_urls": state.image_urls,
                "slice_urls": state.slice_urls,
                "ocr_text": state.ocr_text,
                "plan_history": (state.plan_history or [])[-2:],
                "reflection_result": state.partial_results.get("reflection"),
                "slice_failed_cache": state.slice_failed_cache,
                "attempted_tools": state.attempted_tools,
                "preprocess_meta": state.preprocess_meta,
            },
            ensure_ascii=False,
        )
        prompt = build_planner_user_prompt(state_payload=payload)
        if budget is None:
            budget = RunBudget.for_timeout_seconds(
                timeout_seconds=float(self.timeout_s), token_budget_total=None
            )
        remaining = float(budget.remaining_seconds())
        effective_timeout = max(
            0.0, min(float(self.timeout_s), float(remaining - min_reserve_s))
        )
        if effective_timeout <= 0:
            return PlannerPayload(
                thoughts="budget_exhausted_before_planner",
                plan=[],
                action="execute_tools",
            )
        model = (
            self.llm.silicon_model if self.provider == "silicon" else self.llm.ark_model
        )
        try:
            text = await _call_llm_with_backoff(
                lambda: self.llm.generate(
                    prompt=prompt,
                    system_prompt=PLANNER_SYSTEM_PROMPT,
                    provider=self.provider,
                    max_tokens=self.max_tokens,
                    temperature=0.2,
                ),
                timeout_s=effective_timeout,
            )
        except Exception as e:
            log_event(
                planner_logger,
                "agent_plan_llm_failed",
                level="warning",
                request_id=request_id,
                session_id=state.session_id,
                iteration=state.reflection_count + 1,
                error_type=e.__class__.__name__,
                error=str(e),
            )
            return PlannerPayload(
                thoughts="planner_llm_failed", plan=[], action="execute_tools"
            )

        usage = getattr(text, "usage", None)
        budget.consume_usage(usage)
        log_llm_usage(
            planner_logger,
            request_id=str(request_id or ""),
            session_id=str(state.session_id or ""),
            provider=self.provider,
            model=str(model or ""),
            usage=usage or {},
            stage="autonomous.planner",
        )
        parsed = _parse_json(
            text.text if hasattr(text, "text") else str(text), PlannerPayload
        )
        if not parsed:
            return PlannerPayload(
                thoughts="planner_parse_failed", plan=[], action="execute_tools"
            )
        if not parsed.action:
            parsed.action = "execute_tools"

        # Planner failure strategy: enforce qindex_fetch -> vision_roi_detect -> text_only
        issues = []
        reflection = state.partial_results.get("reflection")
        if isinstance(reflection, dict):
            issues = reflection.get("issues") or []
        diagram_issue = any("diagram_roi_not_found" in str(i) for i in issues)
        slice_failed = False
        if state.slice_failed_cache and state.image_urls:
            img_hash = _compute_image_hash(state.image_urls[0] or "")
            slice_failed = bool(img_hash and state.slice_failed_cache.get(img_hash))

        if diagram_issue or slice_failed:
            forced_plan: List[Dict[str, Any]] = []
            attempted = state.attempted_tools or {}
            if not attempted.get("qindex_fetch", {}).get("status") == "ok":
                forced_plan.append(
                    {"step": "qindex_fetch", "args": {"session_id": state.session_id}}
                )
            if not attempted.get("vision_roi_detect", {}).get("status") == "ok":
                forced_plan.append(
                    {
                        "step": "vision_roi_detect",
                        "args": {
                            "image": state.image_urls[0] if state.image_urls else "",
                            "prefix": f"autonomous/slices/{state.session_id}/",
                        },
                    }
                )
            if not state.ocr_text:
                forced_plan.append(
                    {
                        "step": "ocr_fallback",
                        "args": {
                            "image": state.image_urls[0] if state.image_urls else ""
                        },
                    }
                )
            parsed.plan = forced_plan

        return parsed


class ExecutorAgent:
    def __init__(self, provider: str, session_id: str) -> None:
        self.provider = provider
        self.session_id = session_id

    async def run(
        self,
        state: SessionState,
        plan: List[Dict[str, Any]],
        *,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        retry_attempts = 1
        backoff_s = 0.5
        for step in plan or []:
            if not isinstance(step, dict):
                continue
            tool_name = step.get("step") or step.get("tool")
            args = step.get("args") or {}
            if not tool_name:
                continue
            log_event(
                executor_logger,
                "agent_tool_call",
                session_id=state.session_id,
                request_id=request_id,
                tool=tool_name,
                status="running",
                iteration=state.reflection_count + 1,
            )
            start = time.monotonic()
            result: Dict[str, Any] = {"status": "error", "message": "tool_not_run"}
            for attempt in range(retry_attempts + 1):
                try:
                    if tool_name == "diagram_slice":
                        image = args.get("image") or (
                            state.image_urls[0] if state.image_urls else ""
                        )
                        prefix = f"autonomous/slices/{state.session_id}/"
                        result = await asyncio.to_thread(
                            diagram_slice, image=image, prefix=prefix
                        )
                        urls = result.get("urls") or {}
                        if urls.get("figure_url"):
                            state.slice_urls.setdefault("figure", []).append(
                                urls["figure_url"]
                            )
                        if urls.get("question_url"):
                            state.slice_urls.setdefault("question", []).append(
                                urls["question_url"]
                            )
                        if result.get(
                            "status"
                        ) == "error" and "diagram_roi_not_found" in str(
                            result.get("message", "")
                        ):
                            img_hash = _compute_image_hash(image or "")
                            if img_hash:
                                state.slice_failed_cache[img_hash] = True
                        if result.get("status") == "ok":
                            break
                    elif tool_name == "vision_roi_detect":
                        image = args.get("image") or (
                            state.image_urls[0] if state.image_urls else ""
                        )
                        prefix = (
                            args.get("prefix")
                            or f"autonomous/slices/{state.session_id}/"
                        )
                        result = await asyncio.to_thread(
                            vision_roi_detect, image=image, prefix=prefix
                        )
                        for region in result.get("regions") or []:
                            if not isinstance(region, dict):
                                continue
                            url = region.get("slice_url")
                            if not url:
                                continue
                            kind = str(region.get("kind") or "question").strip().lower()
                            if kind == "figure":
                                state.slice_urls.setdefault("figure", []).append(url)
                            else:
                                state.slice_urls.setdefault("question", []).append(url)
                        if result.get("status") == "ok":
                            break
                    elif tool_name == "qindex_fetch":
                        session_id = args.get("session_id") or state.session_id
                        result = await asyncio.to_thread(
                            qindex_fetch, session_id=session_id
                        )
                        if result.get("status") == "ok":
                            for qn, data in (result.get("questions") or {}).items():
                                for page in data.get("pages", []):
                                    for region in page.get("regions", []):
                                        url = region.get("slice_image_url")
                                        if not url:
                                            continue
                                        kind = (
                                            str(region.get("kind") or "question")
                                            .strip()
                                            .lower()
                                        )
                                        if kind == "figure":
                                            state.slice_urls.setdefault(
                                                "figure", []
                                            ).append(url)
                                        else:
                                            state.slice_urls.setdefault(
                                                "question", []
                                            ).append(url)
                        if result.get("status") == "ok":
                            break
                    elif tool_name == "math_verify":
                        expr = args.get("expression") or ""
                        result = await asyncio.to_thread(math_verify, expression=expr)
                        if result.get("status") == "ok":
                            break
                    elif tool_name == "ocr_fallback":
                        image = args.get("image") or (
                            state.image_urls[0] if state.image_urls else ""
                        )
                        result = await asyncio.to_thread(
                            ocr_fallback, image=image, provider=self.provider
                        )
                        if result.get("status") == "ok":
                            state.ocr_text = result.get("text") or state.ocr_text
                            break
                    else:
                        result = {"status": "error", "message": "tool_not_supported"}
                        break
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                if attempt < retry_attempts:
                    await asyncio.sleep(backoff_s * (2**attempt))

            if tool_name == "diagram_slice" and result.get("status") != "ok":
                image = args.get("image") or (
                    state.image_urls[0] if state.image_urls else ""
                )
                fallback = await asyncio.to_thread(
                    ocr_fallback, image=image, provider=self.provider
                )
                if fallback.get("status") == "ok":
                    state.ocr_text = fallback.get("text") or state.ocr_text
                    result = {
                        "status": "degraded",
                        "message": "diagram_slice_failed_fallback_ocr",
                        "ocr_fallback": fallback,
                    }
                    state.warnings.append("diagram_slice_failed_fallback_ocr")

            # Normalize to unified ToolResult (while keeping legacy keys for compatibility).
            duration_ms = int((time.monotonic() - start) * 1000)
            try:
                timings = state.partial_results.setdefault("timings_ms", {})
                if isinstance(timings, dict):
                    timings["tools_total_ms"] = int(timings.get("tools_total_ms", 0)) + int(
                        duration_ms
                    )
                    key = f"tool_{str(tool_name).strip().lower()}_ms"
                    timings[key] = int(timings.get(key, 0)) + int(duration_ms)
            except Exception:
                pass
            tr = ToolResult.from_legacy(
                tool_name=str(tool_name),
                stage=f"autonomous.tool.{tool_name}",
                raw=result,
                request_id=request_id,
                session_id=state.session_id,
                timing_ms=duration_ms,
            )
            results[tool_name] = tr.to_dict(merge_raw=True)
            state.attempted_tools[tool_name] = {
                "status": result.get("status"),
                "reason": result.get("message") or result.get("warning"),
            }
            status = str(result.get("status") or "").lower()
            status_label = (
                "completed" if status in {"ok", "degraded", "empty"} else "error"
            )
            log_event(
                executor_logger,
                "agent_tool_done",
                session_id=state.session_id,
                request_id=request_id,
                tool=tool_name,
                status=status_label,
                iteration=state.reflection_count + 1,
                duration_ms=duration_ms,
                needs_review=bool(tr.needs_review),
                warning_codes=tr.warning_codes,
                error_code=tr.error_code,
            )
        state.tool_results.update(results)
        return results


class ReflectorAgent:
    def __init__(
        self, llm: LLMClient, provider: str, max_tokens: int, timeout_s: float
    ) -> None:
        self.llm = llm
        self.provider = provider
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s

    async def run(
        self,
        state: SessionState,
        plan: List[Dict[str, Any]],
        *,
        request_id: Optional[str] = None,
        budget: Optional[RunBudget] = None,
        min_reserve_s: float = 0.0,
    ) -> ReflectorPayload:
        payload = json.dumps(
            {
                "tool_results": state.tool_results,
                "ocr_text": state.ocr_text,
                "plan": plan,
                "plan_history": (state.plan_history or [])[-2:],
            },
            ensure_ascii=False,
        )
        prompt = build_reflector_user_prompt(payload=payload)
        if budget is None:
            budget = RunBudget.for_timeout_seconds(
                timeout_seconds=float(self.timeout_s), token_budget_total=None
            )
        remaining = float(budget.remaining_seconds())
        effective_timeout = max(
            0.0, min(float(self.timeout_s), float(remaining - min_reserve_s))
        )
        if effective_timeout <= 0:
            return ReflectorPayload(
                pass_=False,
                issues=["budget_exhausted"],
                confidence=0.0,
                suggestion="finalize",
            )
        model = (
            self.llm.silicon_model if self.provider == "silicon" else self.llm.ark_model
        )
        try:
            text = await _call_llm_with_backoff(
                lambda: self.llm.generate(
                    prompt=prompt,
                    system_prompt=REFLECTOR_SYSTEM_PROMPT,
                    provider=self.provider,
                    max_tokens=self.max_tokens,
                    temperature=0.2,
                ),
                timeout_s=effective_timeout,
            )
        except Exception as e:
            log_event(
                reflector_logger,
                "agent_reflect_llm_failed",
                level="warning",
                request_id=request_id,
                session_id=state.session_id,
                iteration=state.reflection_count + 1,
                error_type=e.__class__.__name__,
                error=str(e),
            )
            return ReflectorPayload(
                pass_=False,
                issues=["reflector_llm_failed"],
                confidence=0.0,
                suggestion="finalize",
            )

        usage = getattr(text, "usage", None)
        budget.consume_usage(usage)
        log_llm_usage(
            reflector_logger,
            request_id=str(request_id or ""),
            session_id=str(state.session_id or ""),
            provider=self.provider,
            model=str(model or ""),
            usage=usage or {},
            stage="autonomous.reflector",
        )
        parsed = _parse_json(
            text.text if hasattr(text, "text") else str(text), ReflectorPayload
        )
        if not parsed:
            return ReflectorPayload(
                pass_=False,
                issues=["reflector_parse_failed"],
                confidence=0.0,
                suggestion="replan",
            )

        # Assessment-only: record diagram issues without forcing pass/confidence.
        has_diagram_failure = any(
            "diagram" in str(v).lower()
            and ("roi_not_found" in str(v).lower() or "failed" in str(v).lower())
            for v in state.tool_results.values()
        )
        if has_diagram_failure and "diagram_roi_not_found" not in parsed.issues:
            parsed.issues.append("diagram_roi_not_found")
            if not parsed.suggestion:
                parsed.suggestion = "缺少图示证据，建议改用 qindex 或 text_only"

        return parsed


class AggregatorAgent:
    def __init__(
        self,
        llm: LLMClient,
        provider: str,
        max_tokens: int,
        subject: Subject,
        timeout_s: float,
    ) -> None:
        self.llm = llm
        self.provider = provider
        self.max_tokens = max_tokens
        self.subject = subject
        self.timeout_s = timeout_s

    async def run(
        self,
        state: SessionState,
        *,
        request_id: Optional[str] = None,
        budget: Optional[RunBudget] = None,
    ) -> AutonomousPayload:
        evidence = json.dumps(
            {
                "ocr_text": state.ocr_text,
                "tool_results": state.tool_results,
                "plan_history": (state.plan_history or [])[-2:],
                "reflection_result": state.partial_results.get("reflection"),
                "warnings": state.warnings,
            },
            ensure_ascii=False,
        )
        prompt = build_aggregator_user_prompt(
            subject=str(self.subject.value), payload=evidence
        )
        system_prompt = (
            AGGREGATOR_SYSTEM_PROMPT_ENGLISH
            if self.subject == Subject.ENGLISH
            else AGGREGATOR_SYSTEM_PROMPT_MATH
        )

        figure_urls = state.slice_urls.get("figure") or []
        question_urls = state.slice_urls.get("question") or []
        figure_urls = figure_urls[:1]
        question_urls = question_urls[:1]
        figure_too_small = bool(state.preprocess_meta.get("figure_too_small"))

        # Determine image source and apply P0.2 compression
        image_source = "unknown"
        grade_variant = (
            str(state.preprocess_meta.get("grade_image_input_variant") or "auto")
            .strip()
            .lower()
            or "auto"
        )
        image_input_mode = "url"
        if figure_urls and not figure_too_small:
            image_urls = _dedupe_images(
                figure_urls + (question_urls if question_urls else [])
            )
            image_source = "slices"
        else:
            # P0.2: Compress original images if needed
            original_urls = _dedupe_images(state.image_urls or [])[:1]
            image_urls = []
            compress_totals = {
                "compress_total_ms": 0,
                "compress_download_ms": 0,
                "compress_decode_ms": 0,
                "compress_resize_ms": 0,
                "compress_encode_ms": 0,
                "compress_upload_ms": 0,
            }
            for url in original_urls:
                compressed_url, metrics = _compress_image_if_needed_with_metrics(
                    url, max_side=1280
                )
                image_urls.append(compressed_url)
                try:
                    for src_k, dst_k in (
                        ("total_ms", "compress_total_ms"),
                        ("download_ms", "compress_download_ms"),
                        ("decode_ms", "compress_decode_ms"),
                        ("resize_ms", "compress_resize_ms"),
                        ("encode_ms", "compress_encode_ms"),
                        ("upload_ms", "compress_upload_ms"),
                    ):
                        v = metrics.get(src_k)
                        if isinstance(v, int):
                            compress_totals[dst_k] = int(compress_totals[dst_k]) + int(
                                v
                            )
                except Exception:
                    pass
            if figure_too_small:
                image_source = "original_fallback_small_figure"
            else:
                image_source = "original_fallback_no_figure"
            try:
                timings = state.partial_results.setdefault("timings_ms", {})
                if isinstance(timings, dict):
                    for k, v in compress_totals.items():
                        timings[k] = int(timings.get(k, 0)) + int(v)
            except Exception:
                pass

        # T2: A/B/C variant for Ark image input (URL vs Data URL).
        if self.provider == "ark" and image_urls:
            use_data_url = False
            if grade_variant == "data_url_first_page":
                use_data_url = True
            elif grade_variant == "data_url_on_small_figure" and figure_too_small:
                use_data_url = True
            if use_data_url:
                src0 = str(image_urls[0] or "")
                if src0 and not src0.startswith("data:image/"):
                    t_data = time.monotonic()
                    data_url = _download_as_data_uri(src0)
                    data_ms = int((time.monotonic() - t_data) * 1000)
                    try:
                        timings = state.partial_results.setdefault("timings_ms", {})
                        if isinstance(timings, dict):
                            timings["image_data_url_download_encode_ms"] = int(
                                timings.get("image_data_url_download_encode_ms", 0)
                            ) + int(data_ms)
                    except Exception:
                        pass
                    if data_url:
                        image_urls[0] = data_url
                        image_input_mode = "data_url"

        image_refs = [
            ImageRef(url=u) if not u.startswith("data:image/") else ImageRef(base64=u)
            for u in image_urls
        ]

        # P0.4: Enhanced logging with image_source
        log_event(
            aggregator_logger,
            "agent_aggregate_start",
            session_id=state.session_id,
            request_id=request_id,
            image_source=image_source,
            grade_image_input_variant=grade_variant,
            image_input_mode=image_input_mode,
            image_count=len(image_refs),
            original_image_count=len(state.image_urls or []),
            figure_count=len(figure_urls),
            question_count=len(question_urls),
        )
        start = time.monotonic()
        remaining = (
            float(budget.remaining_seconds())
            if budget is not None
            else float(self.timeout_s)
        )
        effective_timeout = max(0.0, min(float(self.timeout_s), remaining))
        if effective_timeout <= 0:
            return AutonomousPayload(
                status="failed",
                reason="budget_exhausted",
                ocr_text=state.ocr_text,
                results=[],
                summary="超时预算已耗尽，建议人工复核",
                warnings=["budget_exhausted_needs_review"],
            )
        model = (
            self.llm.silicon_vision_model
            if self.provider == "silicon"
            else self.llm.ark_vision_model
        )
        try:
            settings = get_settings()
            use_image_tools = bool(
                self.provider == "ark"
                and bool(getattr(settings, "ark_image_process_enabled", False))
            )
            text = await _call_llm_with_backoff(
                lambda: self.llm.generate_with_images(
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    images=image_refs,
                    provider=self.provider,
                    max_tokens=self.max_tokens,
                    temperature=0.2,
                    use_tools=use_image_tools,
                ),
                timeout_s=effective_timeout,
            )
        except Exception as e:
            log_event(
                aggregator_logger,
                "agent_aggregate_llm_failed",
                level="warning",
                session_id=state.session_id,
                request_id=request_id,
                error_type=e.__class__.__name__,
                error=str(e),
            )
            return AutonomousPayload(
                status="failed",
                reason="llm_failed",
                ocr_text=state.ocr_text,
                results=[],
                summary="批改暂时失败，建议稍后重试或人工复核",
                warnings=["autonomous_agent_llm_failed", "needs_review"],
            )
        response_id = None
        try:
            response_id = getattr(text, "response_id", None)
        except Exception:
            response_id = None
        response_id = (
            str(response_id).strip()
            if response_id is not None and str(response_id).strip()
            else None
        )
        if response_id:
            state.partial_results.setdefault("llm_trace", {})[
                "ark_response_id"
            ] = response_id
        state.partial_results.setdefault("llm_trace", {})[
            "ark_image_process_requested"
        ] = bool(use_image_tools)
        state.partial_results.setdefault("llm_trace", {})[
            "grade_image_input_variant"
        ] = grade_variant
        state.partial_results.setdefault("llm_trace", {})[
            "ark_image_input_mode"
        ] = image_input_mode
        llm_call_ms = int((time.monotonic() - start) * 1000)
        try:
            timings = state.partial_results.setdefault("timings_ms", {})
            if isinstance(timings, dict):
                timings["llm_aggregate_call_ms"] = int(
                    timings.get("llm_aggregate_call_ms", 0)
                ) + int(llm_call_ms)
        except Exception:
            pass
        log_event(
            aggregator_logger,
            "agent_aggregate_done",
            session_id=state.session_id,
            request_id=request_id,
            duration_ms=llm_call_ms,
            response_id=response_id,
            ark_image_process_requested=bool(use_image_tools),
        )
        usage = getattr(text, "usage", None)
        if budget is not None:
            budget.consume_usage(usage)
        log_llm_usage(
            aggregator_logger,
            request_id=str(request_id or ""),
            session_id=str(state.session_id or ""),
            provider=self.provider,
            model=str(model or ""),
            usage=usage or {},
            stage="autonomous.aggregator",
        )
        raw_text = text.text if hasattr(text, "text") else str(text)
        parse_start = time.monotonic()
        parsed = _parse_json(raw_text, AutonomousPayload)
        parse_ms = int((time.monotonic() - parse_start) * 1000)
        try:
            timings = state.partial_results.setdefault("timings_ms", {})
            if isinstance(timings, dict):
                timings["llm_aggregate_parse_ms"] = int(
                    timings.get("llm_aggregate_parse_ms", 0)
                ) + int(parse_ms)
        except Exception:
            pass
        if not parsed:
            logger.error(
                f"Aggregator parse failed for {state.session_id}. Raw response (first 500 chars): {raw_text[:500]}"
            )
            return AutonomousPayload(
                status="failed",
                reason="parse_failed",
                ocr_text=state.ocr_text,
                results=[],
                summary="批改结果解析失败",
                warnings=["autonomous_agent_parse_failed"],
            )
        return parsed


@trace_span("autonomous_agent.run")
async def run_autonomous_grade_agent(
    *,
    images: List[ImageRef],
    subject: Subject,
    provider: str,
    session_id: str,
    request_id: Optional[str],
    max_iterations_override: Optional[int] = None,
    confidence_threshold_override: Optional[float] = None,
    timeout_seconds_override: Optional[float] = None,
    token_budget_total_override: Optional[int] = None,
    experiments: Optional[Dict[str, Any]] = None,
    grade_image_input_variant: Optional[str] = None,
) -> AutonomousGradeResult:
    settings = get_settings()
    llm = LLMClient()
    max_tokens = int(getattr(settings, "autonomous_agent_max_tokens", 1600))
    max_iterations = int(getattr(settings, "autonomous_agent_max_iterations", 3))
    confidence_threshold = float(
        getattr(settings, "autonomous_agent_confidence_threshold", 0.90)
    )
    timeout_s = float(getattr(settings, "autonomous_agent_timeout_seconds", 600))
    token_budget_total = int(
        getattr(settings, "autonomous_agent_token_budget_total", 12000)
    )
    min_aggregator_s = float(
        getattr(settings, "autonomous_agent_min_aggregator_seconds", 20)
    )

    if max_iterations_override is not None:
        try:
            max_iterations = max(1, int(max_iterations_override))
        except Exception:
            pass
    if confidence_threshold_override is not None:
        try:
            confidence_threshold = float(confidence_threshold_override)
        except Exception:
            pass
    if timeout_seconds_override is not None:
        try:
            timeout_s = max(1.0, float(timeout_seconds_override))
        except Exception:
            pass
    if token_budget_total_override is not None:
        try:
            token_budget_total = max(1, int(token_budget_total_override))
        except Exception:
            pass

    # Keep this guardrail adaptive for tests/dev where timeout may be small.
    min_aggregator_s = min(min_aggregator_s, max(0.0, timeout_s * 0.4))
    overall_start = time.monotonic()
    budget = RunBudget.for_timeout_seconds(
        timeout_seconds=timeout_s, token_budget_total=token_budget_total
    )

    thresholds = {
        "max_iterations": max_iterations,
        "confidence_threshold": confidence_threshold,
        "timeout_seconds": timeout_s,
        "token_budget_total": token_budget_total,
        "min_aggregator_seconds": min_aggregator_s,
        "max_tokens_per_call": max_tokens,
    }
    thresholds_hash = stable_json_hash(thresholds)[:16]
    # P0.6: Make prompt/model/thresholds traceable in every run.
    try:
        model_text = llm.silicon_model if provider == "silicon" else llm.ark_model
        model_vision = (
            llm.silicon_vision_model if provider == "silicon" else llm.ark_vision_model
        )
    except Exception:
        model_text = None
        model_vision = None
    log_event(
        logger,
        "run_versions",
        session_id=session_id,
        request_id=request_id,
        prompt_id="autonomous",
        prompt_version=str(PROMPT_VERSION),
        provider=provider,
        model=str(model_text or ""),
        vision_model=str(model_vision or ""),
        thresholds=thresholds,
        thresholds_hash=thresholds_hash,
        experiments=experiments or {},
    )

    state = SessionState(
        session_id=session_id,
        image_urls=[str(ref.url or ref.base64 or "") for ref in images or []],
    )
    if isinstance(grade_image_input_variant, str) and grade_image_input_variant.strip():
        state.preprocess_meta["grade_image_input_variant"] = (
            grade_image_input_variant.strip().lower()
        )

    prep_start = time.monotonic()
    log_event(
        logger,
        "agent_preprocess_start",
        session_id=session_id,
        request_id=request_id,
        images=len(images or []),
    )
    # Use 3-tier preprocessing pipeline: A (qindex cache) → B (VLM locator) → C (OpenCV fallback)
    pipeline = PreprocessingPipeline(session_id=session_id, request_id=request_id)
    for ref in images or []:
        result = await pipeline.process_image(
            ref, prefix=f"autonomous/prep/{session_id}/", use_cache=True
        )
        # Add all figure slices
        for fig_url in result.figure_urls or []:
            state.slice_urls.setdefault("figure", []).append(fig_url)
        # Add all question slices
        for q_url in result.question_urls or []:
            state.slice_urls.setdefault("question", []).append(q_url)
        if result.warnings:
            state.warnings.extend(result.warnings)
        state.preprocess_meta.setdefault("results", []).append(result.to_dict())
        if result.figure_too_small:
            state.preprocess_meta["figure_too_small"] = True
        # Per-image preprocess details already logged inside preprocessing pipeline.

    # Aggregate preprocess sources + timings across pages (for T1 timing breakdown).
    source_counts: Dict[str, int] = {}
    preprocess_stage_ms: Dict[str, int] = {}
    for r in state.preprocess_meta.get("results") or []:
        if not isinstance(r, dict):
            continue
        src = str(r.get("source") or "unknown").strip().lower() or "unknown"
        source_counts[src] = int(source_counts.get(src, 0)) + 1
        tms = r.get("timings_ms")
        if isinstance(tms, dict):
            for k, v in tms.items():
                if not isinstance(k, str) or not k.strip():
                    continue
                if not isinstance(v, int):
                    continue
                preprocess_stage_ms[k] = int(preprocess_stage_ms.get(k, 0)) + int(v)

    log_event(
        logger,
        "agent_preprocess_breakdown",
        session_id=session_id,
        request_id=request_id,
        sources=source_counts,
        timings_ms=preprocess_stage_ms,
    )

    preprocess_total_ms = int((time.monotonic() - prep_start) * 1000)
    log_event(
        logger,
        "agent_preprocess_done",
        session_id=session_id,
        request_id=request_id,
        figure=len(state.slice_urls.get("figure") or []),
        question=len(state.slice_urls.get("question") or []),
        elapsed_ms=preprocess_total_ms,
    )
    state.partial_results.setdefault("timings_ms", {})["preprocess_total_ms"] = (
        preprocess_total_ms
    )
    for k, v in preprocess_stage_ms.items():
        state.partial_results.setdefault("timings_ms", {})[f"preprocess_{k}"] = int(v)

    store = get_session_store()
    store.save(session_id, state)

    planner = PlannerAgent(
        llm=llm, provider=provider, max_tokens=max_tokens, timeout_s=timeout_s
    )
    executor = ExecutorAgent(provider=provider, session_id=session_id)
    reflector = ReflectorAgent(
        llm=llm, provider=provider, max_tokens=max_tokens, timeout_s=timeout_s
    )
    aggregator = AggregatorAgent(
        llm=llm,
        provider=provider,
        max_tokens=max_tokens,
        subject=subject,
        timeout_s=timeout_s,
    )

    for iteration in range(max_iterations):
        if budget.is_time_exhausted():
            state.warnings.append("budget_exhausted_needs_review")
            break
        if budget.is_token_exhausted():
            state.warnings.append("token_budget_exhausted_needs_review")
            break
        if budget.remaining_seconds() <= min_aggregator_s + 1.0:
            state.warnings.append("budget_low_reserving_for_finalize")
            break
        log_event(
            planner_logger,
            "agent_plan_start",
            session_id=session_id,
            request_id=request_id,
            iteration=iteration + 1,
            agent="planner",
            message="正在分析题目结构…",
        )
        plan_started = time.monotonic()
        plan_payload = await planner.run(
            state, request_id=request_id, budget=budget, min_reserve_s=min_aggregator_s
        )
        state.plan_history.append(
            {
                "iteration": iteration + 1,
                "plan": plan_payload.plan,
                "thoughts": plan_payload.thoughts,
                "timestamp": time.time(),
            }
        )
        log_event(
            planner_logger,
            "agent_plan_done",
            session_id=session_id,
            request_id=request_id,
            iteration=iteration + 1,
            plan_steps=len(plan_payload.plan or []),
            duration_ms=int((time.monotonic() - plan_started) * 1000),
        )

        await executor.run(state, plan_payload.plan or [], request_id=request_id)

        reflect_started = time.monotonic()
        reflection = await reflector.run(
            state,
            plan_payload.plan or [],
            request_id=request_id,
            budget=budget,
            min_reserve_s=min_aggregator_s,
        )
        state.partial_results["reflection"] = reflection.model_dump(by_alias=True)
        state.reflection_count += 1
        log_event(
            reflector_logger,
            (
                "agent_reflect_pass"
                if reflection.pass_ and reflection.confidence >= confidence_threshold
                else "agent_reflect_fail"
            ),
            session_id=session_id,
            request_id=request_id,
            iteration=iteration + 1,
            pass_flag=reflection.pass_,
            confidence=reflection.confidence,
            issues=reflection.issues if not reflection.pass_ else None,
            duration_ms=int((time.monotonic() - reflect_started) * 1000),
        )

        store.save(session_id, state)
        if reflection.pass_ and reflection.confidence >= confidence_threshold:
            break
        if iteration == max_iterations - 1:
            state.warnings.append("Loop max iterations reached")

    payload = await aggregator.run(state, request_id=request_id, budget=budget)
    timings_ms_out: Optional[Dict[str, int]] = None
    try:
        t0 = state.partial_results.get("timings_ms")
        if isinstance(t0, dict):
            cleaned: Dict[str, int] = {}
            for k, v in t0.items():
                if not isinstance(k, str) or not k.strip():
                    continue
                if isinstance(v, bool):
                    continue
                if isinstance(v, int):
                    cleaned[k] = int(v)
            cleaned["grade_total_duration_ms"] = int(
                (time.monotonic() - overall_start) * 1000
            )
            timings_ms_out = cleaned
    except Exception:
        timings_ms_out = None
    status = (payload.status or "done").strip().lower()
    if status == "rejected":
        needs_review = bool(
            any(str(w) == "needs_review" for w in (payload.warnings or []))
        )
        return AutonomousGradeResult(
            status="rejected",
            reason=payload.reason or "not_homework",
            ocr_text=payload.ocr_text or "",
            results=[],
            summary="输入非作业图片，已拒绝批改",
            warnings=payload.warnings or [],
            iterations=state.reflection_count,
            tokens_used=getattr(budget, "tokens_used", None),
            duration_ms=int((time.monotonic() - overall_start) * 1000),
            needs_review=needs_review,
            llm_trace=(
                state.partial_results.get("llm_trace")
                if isinstance(state.partial_results, dict)
                else None
            ),
            timings_ms=timings_ms_out,
        )

    results: List[Dict[str, Any]] = []
    min_len = int(getattr(settings, "judgment_basis_min_length", 2))
    for item in payload.results or []:
        if not isinstance(item, dict):
            continue
        copy_item = dict(item)
        copy_item["verdict"] = _normalize_verdict(copy_item.get("verdict"))
        _ensure_judgment_basis(copy_item, min_len=min_len)
        results.append(copy_item)

    warnings = list(payload.warnings or [])
    warnings.extend(state.warnings)

    # P0.5: Promote tool-level HITL signals to run-level warnings.
    tool_warning_codes: List[str] = []
    run_needs_review = False
    for tool_name, res in (state.tool_results or {}).items():
        if not isinstance(res, dict):
            continue
        if bool(res.get("needs_review")):
            run_needs_review = True
        codes = res.get("warning_codes")
        if isinstance(codes, list):
            for c in codes:
                s = str(c or "").strip()
                if s:
                    tool_warning_codes.append(s)
        # High-signal degradation should be visible even if needs_review isn't set.
        if str(res.get("status") or "").strip().lower() == "degraded":
            tool_warning_codes.append(f"tool_degraded:{tool_name}")

    # Budget / hard guardrails should also trigger HITL.
    for w in state.warnings or []:
        ws = str(w or "").strip().lower()
        if not ws:
            continue
        if (
            "needs_review" in ws
            or "budget_exhausted" in ws
            or "token_budget_exhausted" in ws
        ):
            run_needs_review = True
            if "budget_exhausted" in ws:
                tool_warning_codes.append("budget_exhausted")
            if "token_budget_exhausted" in ws:
                tool_warning_codes.append("token_budget_exhausted")

    # Dedup tool warning codes (preserve order).
    seen = set()
    deduped_tool_codes: List[str] = []
    for c in tool_warning_codes:
        if c in seen:
            continue
        seen.add(c)
        deduped_tool_codes.append(c)

    safety_codes = [
        c for c in deduped_tool_codes if c in {"pii_detected", "prompt_injection"}
    ]
    if run_needs_review or safety_codes:
        if "needs_review" not in warnings:
            warnings.append("needs_review")
        for c in safety_codes:
            if c not in warnings:
                warnings.append(c)

    if budget.is_token_exhausted():
        warnings.append("⚠️ Token预算已耗尽，结果可能不完整，建议人工复核")
    if budget.is_time_exhausted():
        warnings.append("⚠️ 超时预算已耗尽，结果可能不完整，建议人工复核")

    # P1.3: Add explicit warning for missing figures
    if any("diagram_roi_not_found" in str(w) for w in state.warnings):
        warnings.append("⚠️ 图示识别失败，批改结果基于文本推断，建议人工复核")

    log_event(
        aggregator_logger,
        "agent_finalize_done",
        session_id=session_id,
        request_id=request_id,
        total_iterations=state.reflection_count,
        results=len(results),
        warnings_count=len(warnings),
        needs_review=bool(run_needs_review or safety_codes),
        warning_codes=deduped_tool_codes,
        tokens_used=getattr(budget, "tokens_used", None),
        token_budget_total=getattr(budget, "token_budget_total", None),
        remaining_s=budget.remaining_seconds(),
        duration_ms=int((time.monotonic() - overall_start) * 1000),
    )

    # P2: enqueue review item for human-in-the-loop workflow (best-effort).
    if bool(run_needs_review or safety_codes):
        try:
            from homework_agent.services.review_queue import enqueue_review_item

            enqueue_review_item(
                request_id=str(request_id or ""),
                session_id=str(session_id or ""),
                subject=(
                    str(getattr(subject, "value", subject))
                    if subject is not None
                    else None
                ),
                warning_codes=deduped_tool_codes,
                evidence_urls=[
                    u for u in (state.image_urls or []) if isinstance(u, str)
                ],
                run_versions={
                    "prompt_id": "autonomous",
                    "prompt_version": str(PROMPT_VERSION),
                    "provider": str(provider or ""),
                    "model": str(model_text or ""),
                },
                note="autonomous_agent_needs_review",
            )
        except Exception:
            pass

    return AutonomousGradeResult(
        status="done",
        reason=None,
        ocr_text=payload.ocr_text or state.ocr_text or "",
        results=results,
        summary=payload.summary or "批改完成",
        warnings=warnings,
        iterations=state.reflection_count,
        tokens_used=getattr(budget, "tokens_used", None),
        duration_ms=int((time.monotonic() - overall_start) * 1000),
        needs_review=bool(run_needs_review or safety_codes),
        llm_trace=(
            state.partial_results.get("llm_trace")
            if isinstance(state.partial_results, dict)
            else None
        ),
        timings_ms=timings_ms_out,
    )
