from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict

from homework_agent.core.prompts_autonomous import (
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
    math_verify,
    ocr_fallback,
    _compress_image_if_needed,
)
from homework_agent.utils.observability import log_event, trace_span
from homework_agent.utils.settings import get_settings

logger = logging.getLogger("homework_agent.autonomous")
planner_logger = logging.getLogger("homework_agent.autonomous.planner")
executor_logger = logging.getLogger("homework_agent.autonomous.executor")
reflector_logger = logging.getLogger("homework_agent.autonomous.reflector")
aggregator_logger = logging.getLogger("homework_agent.autonomous.aggregator")


def _is_rate_limit_error(err: Exception) -> bool:
    msg = str(err or "").lower()
    return any(s in msg for s in ("429", "rate limit", "tpm limit", "too many requests"))


async def _call_llm_with_backoff(fn, *, timeout_s: float, retries: int = 2, base_delay: float = 1.0):
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
    def __init__(self, llm: LLMClient, provider: str, max_tokens: int, timeout_s: float) -> None:
        self.llm = llm
        self.provider = provider
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s

    async def run(self, state: SessionState) -> PlannerPayload:
        payload = json.dumps(
            {
                "image_urls": state.image_urls,
                "slice_urls": state.slice_urls,
                "ocr_text": state.ocr_text,
                "plan_history": (state.plan_history or [])[-2:],
                "reflection_result": state.partial_results.get("reflection"),
            },
            ensure_ascii=False,
        )
        prompt = build_planner_user_prompt(state_payload=payload)
        text = await _call_llm_with_backoff(
            lambda: self.llm.generate(
                prompt=prompt,
                system_prompt=PLANNER_SYSTEM_PROMPT,
                provider=self.provider,
                max_tokens=self.max_tokens,
                temperature=0.2,
            ),
            timeout_s=self.timeout_s,
        )
        parsed = _parse_json(text.text if hasattr(text, "text") else str(text), PlannerPayload)
        if not parsed:
            return PlannerPayload(thoughts="planner_parse_failed", plan=[], action="execute_tools")
        if not parsed.action:
            parsed.action = "execute_tools"

        # P1.2: OpenCV parameter grading - skip diagram_slice on iteration 3 if it failed before
        iteration = state.reflection_count + 1
        if iteration >= 3:
            prev_failed = any(
                "diagram" in str(v).lower() and "roi_not_found" in str(v).lower()
                for v in state.tool_results.values()
            )
            if prev_failed:
                logger.info(f"Planner: Iteration {iteration}, skipping diagram_slice due to previous failures")
                # Replace diagram_slice with ocr_fallback in the plan
                for step in parsed.plan:
                    if step.get("step") == "diagram_slice":
                        step["step"] = "ocr_fallback"
                        step["args"] = {"image": state.image_urls[0] if state.image_urls else ""}

        return parsed


class ExecutorAgent:
    def __init__(self, provider: str, session_id: str) -> None:
        self.provider = provider
        self.session_id = session_id

    async def run(self, state: SessionState, plan: List[Dict[str, Any]]) -> Dict[str, Any]:
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
                tool=tool_name,
                status="running",
                iteration=state.reflection_count + 1,
            )
            start = time.monotonic()
            result: Dict[str, Any] = {"status": "error", "message": "tool_not_run"}
            for attempt in range(retry_attempts + 1):
                try:
                    if tool_name == "diagram_slice":
                        image = args.get("image") or (state.image_urls[0] if state.image_urls else "")
                        prefix = f"autonomous/slices/{state.session_id}/"
                        result = await asyncio.to_thread(diagram_slice, image=image, prefix=prefix)
                        urls = result.get("urls") or {}
                        if urls.get("figure_url"):
                            state.slice_urls.setdefault("figure", []).append(urls["figure_url"])
                        if urls.get("question_url"):
                            state.slice_urls.setdefault("question", []).append(urls["question_url"])
                        if result.get("status") == "ok":
                            break
                    elif tool_name == "qindex_fetch":
                        session_id = args.get("session_id") or state.session_id
                        result = await asyncio.to_thread(qindex_fetch, session_id=session_id)
                        if result.get("status") == "ok":
                            break
                    elif tool_name == "math_verify":
                        expr = args.get("expression") or ""
                        result = await asyncio.to_thread(math_verify, expression=expr)
                        if result.get("status") == "ok":
                            break
                    elif tool_name == "ocr_fallback":
                        image = args.get("image") or (state.image_urls[0] if state.image_urls else "")
                        result = await asyncio.to_thread(ocr_fallback, image=image, provider=self.provider)
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
                image = args.get("image") or (state.image_urls[0] if state.image_urls else "")
                fallback = await asyncio.to_thread(ocr_fallback, image=image, provider=self.provider)
                if fallback.get("status") == "ok":
                    state.ocr_text = fallback.get("text") or state.ocr_text
                    result = {
                        "status": "degraded",
                        "message": "diagram_slice_failed_fallback_ocr",
                        "ocr_fallback": fallback,
                    }
                    state.warnings.append("diagram_slice_failed_fallback_ocr")

            results[tool_name] = result
            status = str(result.get("status") or "").lower()
            status_label = "completed" if status in {"ok", "degraded", "empty"} else "error"
            log_event(
                executor_logger,
                "agent_tool_done",
                session_id=state.session_id,
                tool=tool_name,
                status=status_label,
                iteration=state.reflection_count + 1,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        state.tool_results.update(results)
        return results


class ReflectorAgent:
    def __init__(self, llm: LLMClient, provider: str, max_tokens: int, timeout_s: float) -> None:
        self.llm = llm
        self.provider = provider
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s

    async def run(self, state: SessionState, plan: List[Dict[str, Any]]) -> ReflectorPayload:
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
        text = await _call_llm_with_backoff(
            lambda: self.llm.generate(
                prompt=prompt,
                system_prompt=REFLECTOR_SYSTEM_PROMPT,
                provider=self.provider,
                max_tokens=self.max_tokens,
                temperature=0.2,
            ),
            timeout_s=self.timeout_s,
        )
        parsed = _parse_json(text.text if hasattr(text, "text") else str(text), ReflectorPayload)
        if not parsed:
            return ReflectorPayload(pass_=False, issues=["reflector_parse_failed"], confidence=0.0, suggestion="replan")

        # P1.1: Figure exemption logic
        # If OCR is complete but diagram failed, boost confidence to avoid unnecessary iterations
        if (not parsed.pass_
            and 0.70 <= parsed.confidence < 0.90
            and len(state.ocr_text or "") > 100):
            # Check if diagram_slice failed
            has_diagram_failure = any(
                "diagram" in str(v).lower() and ("roi_not_found" in str(v).lower() or "failed" in str(v).lower())
                for v in state.tool_results.values()
            )
            if has_diagram_failure:
                logger.info(f"Reflector: Figure exemption triggered, boosting confidence from {parsed.confidence:.2f} to 0.90")
                parsed.pass_ = True
                parsed.confidence = 0.90
                parsed.suggestion = "图示不足，基于完整文本推断"

        return parsed


class AggregatorAgent:
    def __init__(self, llm: LLMClient, provider: str, max_tokens: int, subject: Subject, timeout_s: float) -> None:
        self.llm = llm
        self.provider = provider
        self.max_tokens = max_tokens
        self.subject = subject
        self.timeout_s = timeout_s

    async def run(self, state: SessionState) -> AutonomousPayload:
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
        prompt = build_aggregator_user_prompt(subject=str(self.subject.value), payload=evidence)
        system_prompt = AGGREGATOR_SYSTEM_PROMPT_ENGLISH if self.subject == Subject.ENGLISH else AGGREGATOR_SYSTEM_PROMPT_MATH

        figure_urls = state.slice_urls.get("figure") or []
        question_urls = state.slice_urls.get("question") or []
        figure_urls = figure_urls[:1]
        question_urls = question_urls[:1]

        # Determine image source and apply P0.2 compression
        image_source = "unknown"
        if figure_urls or question_urls:
            image_urls = _dedupe_images(figure_urls + question_urls)
            image_source = "slices"
        else:
            # P0.2: Compress original images if needed
            original_urls = _dedupe_images(state.image_urls or [])[:1]
            image_urls = []
            for url in original_urls:
                compressed_url = _compress_image_if_needed(url, max_side=1280)
                image_urls.append(compressed_url)
            image_source = "original"

        image_refs = [ImageRef(url=u) if not u.startswith("data:image/") else ImageRef(base64=u) for u in image_urls]

        # P0.4: Enhanced logging with image_source
        log_event(
            aggregator_logger,
            "agent_aggregate_start",
            session_id=state.session_id,
            image_source=image_source,
            image_count=len(image_refs),
            original_image_count=len(state.image_urls or []),
            figure_count=len(figure_urls),
            question_count=len(question_urls),
        )
        start = time.monotonic()
        text = await _call_llm_with_backoff(
            lambda: self.llm.generate_with_images(
                system_prompt=system_prompt,
                user_prompt=prompt,
                images=image_refs,
                provider=self.provider,
                max_tokens=self.max_tokens,
                temperature=0.2,
                use_tools=False,
            ),
            timeout_s=self.timeout_s,
        )
        log_event(
            aggregator_logger,
            "agent_aggregate_done",
            session_id=state.session_id,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        parsed = _parse_json(text.text if hasattr(text, "text") else str(text), AutonomousPayload)
        if not parsed:
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
) -> AutonomousGradeResult:
    settings = get_settings()
    llm = LLMClient()
    max_tokens = int(getattr(settings, "autonomous_agent_max_tokens", 1600))
    max_iterations = int(getattr(settings, "autonomous_agent_max_iterations", 3))
    confidence_threshold = float(getattr(settings, "autonomous_agent_confidence_threshold", 0.90))
    timeout_s = float(getattr(settings, "autonomous_agent_timeout_seconds", 600))
    overall_start = time.monotonic()

    state = SessionState(
        session_id=session_id,
        image_urls=[str(ref.url or ref.base64 or "") for ref in images or []],
    )

    prep_start = time.monotonic()
    log_event(
        logger,
        "agent_preprocess_start",
        session_id=session_id,
        request_id=request_id,
        images=len(images or []),
    )

    # P2.2: Use unified preprocessing pipeline
    pipeline = PreprocessingPipeline(session_id=session_id)
    for ref in images or []:
        result = await pipeline.process_image(ref, prefix=f"autonomous/prep/{session_id}/", use_cache=True)
        if result.figure_url:
            state.slice_urls.setdefault("figure", []).append(result.figure_url)
        if result.question_url:
            state.slice_urls.setdefault("question", []).append(result.question_url)
        if result.warnings:
            state.warnings.extend(result.warnings)

    log_event(
        logger,
        "agent_preprocess_done",
        session_id=session_id,
        request_id=request_id,
        figure=len(state.slice_urls.get("figure") or []),
        question=len(state.slice_urls.get("question") or []),
        elapsed_ms=int((time.monotonic() - prep_start) * 1000),
    )

    store = get_session_store()
    store.save(session_id, state)

    planner = PlannerAgent(llm=llm, provider=provider, max_tokens=max_tokens, timeout_s=timeout_s)
    executor = ExecutorAgent(provider=provider, session_id=session_id)
    reflector = ReflectorAgent(llm=llm, provider=provider, max_tokens=max_tokens, timeout_s=timeout_s)
    aggregator = AggregatorAgent(
        llm=llm, provider=provider, max_tokens=max_tokens, subject=subject, timeout_s=timeout_s
    )

    for iteration in range(max_iterations):
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
        plan_payload = await planner.run(state)
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

        await executor.run(state, plan_payload.plan or [])

        reflect_started = time.monotonic()
        reflection = await reflector.run(state, plan_payload.plan or [])
        state.partial_results["reflection"] = reflection.model_dump(by_alias=True)
        state.reflection_count += 1
        log_event(
            reflector_logger,
            "agent_reflect_pass" if reflection.pass_ and reflection.confidence >= confidence_threshold else "agent_reflect_fail",
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

    payload = await aggregator.run(state)
    status = (payload.status or "done").strip().lower()
    if status == "rejected":
        return AutonomousGradeResult(
            status="rejected",
            reason=payload.reason or "not_homework",
            ocr_text=payload.ocr_text or "",
            results=[],
            summary="输入非作业图片，已拒绝批改",
            warnings=payload.warnings or [],
            iterations=state.reflection_count,
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
        duration_ms=int((time.monotonic() - overall_start) * 1000),
    )

    return AutonomousGradeResult(
        status="done",
        reason=None,
        ocr_text=payload.ocr_text or state.ocr_text or "",
        results=results,
        summary=payload.summary or "批改完成",
        warnings=warnings,
        iterations=state.reflection_count,
    )
