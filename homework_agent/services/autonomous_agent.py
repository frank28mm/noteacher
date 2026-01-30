from __future__ import annotations

import asyncio
import json
import logging
import re
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


_TEMPLATE_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def _resolve_template_expr(expr: str, state: SessionState) -> str:
    e = str(expr or "").strip()
    if not e:
        return ""
    if e == "session_id":
        return str(state.session_id or "")
    if e.startswith("slice_urls."):
        rest = e[len("slice_urls.") :]
        m = re.fullmatch(r"(figure|question)\[(\d+)\]", rest)
        if m:
            kind = m.group(1)
            idx = int(m.group(2))
            urls = state.slice_urls.get(kind) or []
            if 0 <= idx < len(urls):
                return str(urls[idx] or "")
        return ""
    m = re.fullmatch(r"image_urls\[(\d+)\]", e)
    if m:
        idx = int(m.group(1))
        urls = state.image_urls or []
        if 0 <= idx < len(urls):
            return str(urls[idx] or "")
        return ""
    return ""


def _resolve_templates(value: Any, state: SessionState) -> Any:
    try:
        if isinstance(value, str):
            if "{{" not in value:
                return value

            def _repl(m: re.Match) -> str:
                return _resolve_template_expr(m.group(1), state)

            return _TEMPLATE_RE.sub(_repl, value)
        if isinstance(value, dict):
            return {k: _resolve_templates(v, state) for k, v in value.items()}
        if isinstance(value, list):
            return [_resolve_templates(v, state) for v in value]
        return value
    except Exception:
        return value


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
            preprocess_mode = (
                str((state.preprocess_meta or {}).get("mode") or "").strip().lower()
            )
            # Keep VLM-based locator out of fast path unless preprocess is "full".
            if preprocess_mode == "full":
                if not attempted.get("vision_roi_detect", {}).get("status") == "ok":
                    forced_plan.append(
                        {
                            "step": "vision_roi_detect",
                            "args": {
                                "image": (
                                    state.image_urls[0] if state.image_urls else ""
                                ),
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
            args = _resolve_templates(step.get("args") or {}, state) or {}
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
                    timings["tools_total_ms"] = int(
                        timings.get("tools_total_ms", 0)
                    ) + int(duration_ms)
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

        ocr_text = str(state.ocr_text or "")
        visual_risk = False
        try:
            # Heuristic trigger for geometry/diagram-heavy pages where text-only aggregation is brittle.
            # Kept intentionally simple and explainable (documented in A-5 visual validation).
            signals = (
                "如图",
                "下图",
                "右图",
                "左图",
                "图中",
                "图1",
                "图2",
                "坐标",
                "函数",
                "抛物线",
                "直线",
                "圆",
                "扇形",
                "三角形",
                "平行四边形",
                "梯形",
                "矩形",
                "正方形",
                "菱形",
                "∠",
                "△",
                "⊙",
                "⟂",
                "∥",
            )
            visual_risk = any(s in ocr_text for s in signals)
        except Exception:
            visual_risk = False
        state.preprocess_meta["visual_risk"] = bool(visual_risk)

        # Determine image source and apply P0.2 compression
        image_source = "unknown"
        grade_variant = (
            str(state.preprocess_meta.get("grade_image_input_variant") or "auto")
            .strip()
            .lower()
            or "auto"
        )
        image_input_mode = "url"
        # P0.2: Compress original images if needed (also used as a fallback when slices are imperfect).
        original_urls = _dedupe_images(state.image_urls or [])[:1]
        compressed_original_urls: List[str] = []
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
            compressed_original_urls.append(compressed_url)
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
                        compress_totals[dst_k] = int(compress_totals[dst_k]) + int(v)
            except Exception:
                pass
        try:
            timings = state.partial_results.setdefault("timings_ms", {})
            if isinstance(timings, dict):
                for k, v in compress_totals.items():
                    timings[k] = int(timings.get(k, 0)) + int(v)
        except Exception:
            pass

        if figure_urls and not figure_too_small:
            # Include original page as a robust fallback: if a slice misses the key diagram,
            # image_process can still zoom/locate on the full page.
            image_urls = _dedupe_images(
                figure_urls
                + (question_urls if question_urls else [])
                + (compressed_original_urls if compressed_original_urls else [])
            )
            image_source = "slices_plus_original"
        else:
            image_urls = list(compressed_original_urls)
            if figure_too_small:
                image_source = "original_fallback_small_figure"
            else:
                image_source = "original_fallback_no_figure"

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

        preprocess_mode = (
            str((state.preprocess_meta or {}).get("mode") or "").strip().lower()
        )
        use_images_for_aggregate = True
        if (
            preprocess_mode in {"off", "qindex_only"}
            and not figure_urls
            and not question_urls
            and bool(state.ocr_text)
            and not bool((state.preprocess_meta or {}).get("visual_risk"))
        ):
            # Fast path: when we already have OCR and no visual slices exist, prefer text-only aggregation.
            use_images_for_aggregate = False
            image_source = "ocr_only"
            image_input_mode = "none"

        image_refs = (
            [
                (
                    ImageRef(url=u)
                    if not u.startswith("data:image/")
                    else ImageRef(base64=u)
                )
                for u in image_urls
            ]
            if use_images_for_aggregate
            else []
        )

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
        if not use_images_for_aggregate:
            model = (
                self.llm.silicon_model
                if self.provider == "silicon"
                else self.llm.ark_model
            )
        try:
            settings = get_settings()
            use_image_tools = bool(
                self.provider == "ark"
                and bool(getattr(settings, "ark_image_process_enabled", False))
            )
            if not use_images_for_aggregate:
                use_image_tools = False
            visual_risk = bool((state.preprocess_meta or {}).get("visual_risk"))
            if use_image_tools and not (figure_urls or visual_risk):
                # Only enable image_process when we either have explicit slices OR we have a clear
                # diagram/geometry risk signal from OCR (slices may be missing in qindex_only/off).
                use_image_tools = False

            def _call_llm(max_tokens: int):
                if use_images_for_aggregate:
                    return self.llm.generate_with_images(
                        system_prompt=system_prompt,
                        user_prompt=prompt,
                        images=image_refs,
                        provider=self.provider,
                        max_tokens=int(max_tokens),
                        temperature=0.2,
                        use_tools=use_image_tools,
                    )
                return self.llm.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    provider=self.provider,
                    max_tokens=int(max_tokens),
                    temperature=0.2,
                )

            text = await _call_llm_with_backoff(
                lambda: _call_llm(
                    int(max(int(self.max_tokens), 12000))
                    if not use_images_for_aggregate
                    else int(self.max_tokens)
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
        try:
            usage = getattr(text, "usage", None)
        except Exception:
            usage = None
        if isinstance(usage, dict):
            # Keep only the standard keys for downstream billing/audit.
            state.partial_results.setdefault("llm_trace", {})["llm_usage"] = {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
            }
        state.partial_results.setdefault("llm_trace", {})["llm_model"] = str(
            model or ""
        )
        state.partial_results.setdefault("llm_trace", {})["llm_provider"] = str(
            self.provider or ""
        )
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
            # If the model output was truncated (e.g., max_output_tokens too low), retry once with a higher cap.
            # This keeps fast-path latency lower while preserving correctness for multi-question pages.
            if self.provider == "ark":
                retry_max_tokens = int(max(int(self.max_tokens) * 3, 12000))
                if retry_max_tokens != int(self.max_tokens):
                    log_event(
                        aggregator_logger,
                        "agent_aggregate_parse_retry",
                        session_id=state.session_id,
                        request_id=request_id,
                        prev_max_tokens=int(self.max_tokens),
                        retry_max_tokens=retry_max_tokens,
                    )
                    try:
                        text2 = await _call_llm_with_backoff(
                            lambda: _call_llm(retry_max_tokens),
                            timeout_s=effective_timeout,
                        )
                        raw2 = text2.text if hasattr(text2, "text") else str(text2)
                        parse_start2 = time.monotonic()
                        parsed2 = _parse_json(raw2, AutonomousPayload)
                        parse_ms2 = int((time.monotonic() - parse_start2) * 1000)
                        try:
                            timings = state.partial_results.setdefault("timings_ms", {})
                            if isinstance(timings, dict):
                                timings["llm_aggregate_parse_retry_ms"] = int(
                                    timings.get("llm_aggregate_parse_retry_ms", 0)
                                ) + int(parse_ms2)
                        except Exception:
                            pass
                        if parsed2:
                            return parsed2
                    except Exception as retry_err:
                        log_event(
                            aggregator_logger,
                            "agent_aggregate_parse_retry_failed",
                            level="warning",
                            session_id=state.session_id,
                            request_id=request_id,
                            error_type=retry_err.__class__.__name__,
                            error=str(retry_err),
                        )
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
    settings = get_settings()
    preprocess_mode = (
        str(getattr(settings, "autonomous_preprocess_mode", "full") or "full")
        .strip()
        .lower()
    )
    if preprocess_mode not in {"full", "qindex_only", "off"}:
        preprocess_mode = "full"
    state.preprocess_meta["mode"] = preprocess_mode
    try:
        # Guardrail: the default token budget (e.g. 12k) is too small for real pages (OCR + evidence + output),
        # and can cause premature "token_budget_exhausted" downgrades in full/visual paths.
        if budget.token_budget_total is not None:
            budget.token_budget_total = max(int(budget.token_budget_total), 40000)
    except Exception:
        pass

    if preprocess_mode == "off":
        log_event(
            logger,
            "agent_preprocess_skipped",
            session_id=session_id,
            request_id=request_id,
            mode=preprocess_mode,
        )
    else:
        enable_vlm = preprocess_mode == "full"
        enable_opencv = preprocess_mode == "full"
        pipeline = PreprocessingPipeline(
            session_id=session_id,
            request_id=request_id,
            enable_qindex_cache=True,
            enable_vlm=enable_vlm,
            enable_opencv=enable_opencv,
        )
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
        mode=preprocess_mode,
    )
    state.partial_results.setdefault("timings_ms", {})[
        "preprocess_total_ms"
    ] = preprocess_total_ms
    for k, v in preprocess_stage_ms.items():
        state.partial_results.setdefault("timings_ms", {})[f"preprocess_{k}"] = int(v)

    store = get_session_store()
    store.save(session_id, state)

    # Fast-path guardrail: for qindex_only/off modes, ensure we have OCR text before the loop,
    # so Aggregator can prefer text-only aggregation (much faster than deep vision reasoning).
    try:
        if preprocess_mode in {"qindex_only", "off"} and not state.ocr_text:
            img0 = state.image_urls[0] if state.image_urls else ""
            if img0:
                log_event(
                    executor_logger,
                    "agent_tool_call",
                    session_id=state.session_id,
                    request_id=request_id,
                    tool="ocr_fallback",
                    status="running",
                    iteration=0,
                )
                t0 = time.monotonic()
                raw = await asyncio.to_thread(
                    ocr_fallback, image=img0, provider=provider
                )
                dur_ms = int((time.monotonic() - t0) * 1000)
                tr = ToolResult.from_legacy(
                    tool_name="ocr_fallback",
                    stage="autonomous.tool.ocr_fallback",
                    raw=raw,
                    request_id=request_id,
                    session_id=state.session_id,
                    timing_ms=dur_ms,
                )
                state.tool_results["ocr_fallback"] = tr.to_dict(merge_raw=True)
                state.attempted_tools["ocr_fallback"] = {
                    "status": raw.get("status") if isinstance(raw, dict) else "error",
                    "reason": (raw.get("message") if isinstance(raw, dict) else None),
                }
                if isinstance(raw, dict) and raw.get("status") == "ok":
                    state.ocr_text = raw.get("text") or state.ocr_text
                try:
                    timings = state.partial_results.setdefault("timings_ms", {})
                    if isinstance(timings, dict):
                        timings["tools_total_ms"] = int(
                            timings.get("tools_total_ms", 0)
                        ) + int(dur_ms)
                        timings["tool_ocr_fallback_ms"] = int(
                            timings.get("tool_ocr_fallback_ms", 0)
                        ) + int(dur_ms)
                except Exception:
                    pass
                log_event(
                    executor_logger,
                    "agent_tool_done",
                    session_id=state.session_id,
                    request_id=request_id,
                    tool="ocr_fallback",
                    status="completed" if bool(tr.ok) else "error",
                    iteration=0,
                    duration_ms=dur_ms,
                    needs_review=bool(tr.needs_review),
                    warning_codes=tr.warning_codes,
                    error_code=tr.error_code,
                )
                store.save(session_id, state)
    except Exception:
        pass

    planner_max_tokens = int(
        getattr(
            settings,
            "autonomous_agent_planner_max_tokens",
            min(1200, int(max_tokens)),
        )
    )
    reflector_max_tokens = int(
        getattr(
            settings,
            "autonomous_agent_reflector_max_tokens",
            min(1200, int(max_tokens)),
        )
    )
    planner = PlannerAgent(
        llm=llm,
        provider=provider,
        max_tokens=planner_max_tokens,
        timeout_s=timeout_s,
    )
    executor = ExecutorAgent(provider=provider, session_id=session_id)
    reflector = ReflectorAgent(
        llm=llm,
        provider=provider,
        max_tokens=reflector_max_tokens,
        timeout_s=timeout_s,
    )
    aggregator = AggregatorAgent(
        llm=llm,
        provider=provider,
        max_tokens=max_tokens,
        subject=subject,
        timeout_s=timeout_s,
    )

    fast_finalize = bool(
        preprocess_mode in {"off", "qindex_only"}
        and bool(state.ocr_text)
        and not (state.slice_urls.get("figure") or [])
        and not (state.slice_urls.get("question") or [])
    )
    if fast_finalize:
        max_iterations = 0

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
