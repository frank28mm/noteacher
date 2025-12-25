"""
LLM Client - 文本推理客户端

支持:
- qwen3 (SiliconFlow) 和 doubao (Ark) 国内模型
- 数学/英语批改和苏格拉底辅导提示词
- 结构化JSON输出
- 批处理支持
"""

import json
import re
import logging
import time
from typing import Optional, List, Dict, Any, Union, Iterable
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

from openai import OpenAI, APIConnectionError, APITimeoutError
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from functools import partial
from fastapi.encoders import jsonable_encoder

from homework_agent.core.prompts import (
    MATH_GRADER_SYSTEM_PROMPT,
    ENGLISH_GRADER_SYSTEM_PROMPT,
    SOCRATIC_TUTOR_SYSTEM_PROMPT,
)
from homework_agent.models.schemas import Subject, SimilarityMode, Severity, ImageRef
from homework_agent.utils.settings import get_settings
from homework_agent.utils.observability import log_event, trace_span
from homework_agent.core.tools import get_default_tool_registry, load_default_tools

logger = logging.getLogger(__name__)


def _extract_first_json_object(text: str) -> Optional[str]:
    if not text:
        return None
    s = str(text)
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def _repair_json_text(text: str) -> Optional[str]:
    """
    Attempt to repair malformed JSON from LLM output.
    
    Handles common issues:
    - Trailing commas before } or ]
    - Missing commas between elements (e.g., }{, ][, "...", etc.)
    - Leading/trailing prose around JSON block
    """
    if not text:
        return None
    s = str(text)
    block = _extract_first_json_object(s)
    if not block:
        start = s.find("{")
        end = s.rfind("}")
        if start >= 0 and end > start:
            block = s[start : end + 1]
        elif start >= 0:
            # Truncated JSON - no closing brace found, extract from start to end
            block = s[start:]
        else:
            return None
    
    # Step 1: Remove trailing commas before closing braces/brackets.
    cleaned = re.sub(r",\s*([}\]])", r"\1", block)
    
    # Step 2: Insert missing commas between elements.
    # Pattern: `}` followed by whitespace/newline then `{` or `"` (next element)
    cleaned = re.sub(r"}\s*\n\s*{", r"},\n{", cleaned)
    cleaned = re.sub(r"}\s*\n\s*\"", r"},\n\"", cleaned)
    # Pattern: `]` followed by whitespace/newline then `{` or `[` (next element in array context)
    cleaned = re.sub(r"]\s*\n\s*\[", r"],\n[", cleaned)
    cleaned = re.sub(r"]\s*\n\s*{", r"},\n{", cleaned)  # Note: this might be inside an array of objects
    # Pattern: closing quote of value, newline, then opening quote of key (missing comma)
    # e.g., "value"\n"key" -> "value",\n"key"
    # Be careful: only match when it looks like end-of-value followed by new key
    cleaned = re.sub(r'"\s*\n\s*"([^"]+)":', r'",\n"\1":', cleaned)
    
    # Step 3: Try to fix unterminated strings by attempting suffix repairs
    # Count unbalanced quotes, braces, brackets
    try:
        import json
        json.loads(cleaned)
        return cleaned  # Already valid
    except Exception:
        pass
    
    # Step 3b: Escape control characters that might be in unterminated strings
    # This helps when LLM output is truncated mid-string
    def escape_control_chars(s: str) -> str:
        # Escape newlines and tabs that aren't already escaped
        result = []
        i = 0
        while i < len(s):
            c = s[i]
            if c == '\\' and i + 1 < len(s):
                # Already escaped, keep as is
                result.append(s[i:i+2])
                i += 2
            elif c == '\n':
                result.append('\\n')
                i += 1
            elif c == '\r':
                result.append('\\r')
                i += 1
            elif c == '\t':
                result.append('\\t')
                i += 1
            else:
                result.append(c)
                i += 1
        return ''.join(result)
    
    cleaned_escaped = escape_control_chars(cleaned)
    
    # Try common suffix repairs for truncated output
    suffixes_to_try = [
        '"}]}',      # Close string, close array, close object
        '"}]',       # Close string, close array
        '"]}',       # Close string, close array, close object
        '"}',        # Close string, close object
        '"]',        # Close string, close array
        '"',         # Just close string
        '}]}',       # Close array, close object
        '}]',        # Close array
        ']}',        # Close array, close object
        '}',         # Close object
        ']',         # Close array
    ]
    
    for suffix in suffixes_to_try:
        try:
            import json
            json.loads(cleaned_escaped + suffix)
            return cleaned_escaped + suffix
        except Exception:
            continue
    
    return cleaned


def _log_retry(op: str, retry_state):
    provider = retry_state.kwargs.get("provider", "unknown")
    model = None
    try:
        self_obj = retry_state.args[0]
        if provider == "silicon":
            model = getattr(self_obj, "silicon_model", None)
        elif provider == "ark":
            model = getattr(self_obj, "ark_model", None)
        else:
            model = getattr(self_obj, "model_reasoning", None)
    except Exception:
        model = model or "unknown"
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "Retrying %s (provider=%s, model=%s), attempt=%s, exception=%s",
        op,
        provider,
        model,
        retry_state.attempt_number,
        exc,
    )


class LLMResult(BaseModel):
    """LLM推理结果"""
    text: str = Field(..., description="模型返回的文本内容")
    raw: Dict[str, Any] = Field(default_factory=dict, description="原始API响应")
    usage: Optional[Dict[str, int]] = Field(None, description="token使用统计")


class MathGradingResult(BaseModel):
    """数学批改结果"""
    model_config = ConfigDict(extra="ignore")
    wrong_items: List[Dict[str, Any]] = Field(default_factory=list, description="错误项列表")
    questions: List[Dict[str, Any]] = Field(default_factory=list, description="全题列表（用于按题号检索对话）")
    summary: str = Field(..., description="总体摘要")
    subject: Subject = Subject.MATH
    total_items: Optional[int] = Field(None, description="检测到的题目总数")
    wrong_count: Optional[int] = Field(None, description="错误数量")
    cross_subject_flag: Optional[bool] = Field(None, description="跨学科标记")
    warnings: List[str] = Field(default_factory=list, description="警告信息")


class EnglishGradingResult(BaseModel):
    """英语批改结果"""
    model_config = ConfigDict(extra="ignore")
    wrong_items: List[Dict[str, Any]] = Field(default_factory=list, description="错误项列表")
    questions: List[Dict[str, Any]] = Field(default_factory=list, description="全题列表（用于按题号检索对话）")
    summary: str = Field(..., description="总体摘要")
    subject: Subject = Subject.ENGLISH
    total_items: Optional[int] = Field(None, description="检测到的题目总数")
    wrong_count: Optional[int] = Field(None, description="错误数量")
    cross_subject_flag: Optional[bool] = Field(None, description="跨学科标记")
    warnings: List[str] = Field(default_factory=list, description="警告信息")


class SocraticTutorResult(BaseModel):
    """苏格拉底辅导结果"""
    messages: List[Dict[str, str]] = Field(default_factory=list, description="对话消息")
    session_id: Optional[str] = Field(None, description="会话ID")
    status: str = Field(..., description="状态: continue/limit_reached/explained")
    interaction_count: int = Field(default=0, description="交互次数")


class LLMClient:
    """LLM客户端，支持国内模型"""

    def __init__(self):
        """初始化LLM客户端"""
        settings = get_settings()
        load_default_tools()

        # OpenAI配置 (可选)
        self.openai_api_key = settings.openai_api_key
        self.openai_base_url = settings.openai_base_url
        self.model_reasoning = settings.model_reasoning

        # SiliconFlow配置 (qwen3)
        self.silicon_api_key = settings.silicon_api_key
        self.silicon_base_url = settings.silicon_base_url
        # 使用专用配置，若未设置则回退到 generic model_reasoning (需确保兼容) 或默认值
        self.silicon_model = settings.silicon_reasoning_model or settings.model_reasoning
        self.silicon_vision_model = settings.silicon_vision_model or self.silicon_model

        # Ark配置 (doubao)
        self.ark_api_key = settings.ark_api_key
        self.ark_base_url = settings.ark_base_url
        # Doubao 文本模型（Ark）
        self.ark_model = settings.ark_reasoning_model
        self.ark_model_thinking = settings.ark_reasoning_model_thinking
        self.ark_vision_model = settings.ark_vision_model
        # Ensure lower-level client timeout is never smaller than grade LLM budget
        self.timeout_seconds = max(
            int(settings.llm_client_timeout_seconds),
            int(settings.grade_llm_timeout_seconds),
        )
        self.tool_calling_enabled = bool(getattr(settings, "tool_calling_enabled", True))
        self.max_tool_calls = int(getattr(settings, "max_tool_calls", 3))
        self.tool_choice = getattr(settings, "tool_choice", "auto") or "auto"

    def _image_blocks_from_refs(
        self, images: List["ImageRef"], provider: str
    ) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []
        for ref in images or []:
            url = getattr(ref, "url", None)
            b64 = getattr(ref, "base64", None)
            if url:
                if provider == "ark":
                    blocks.append({"type": "input_image", "image_url": str(url)})
                else:
                    blocks.append({"type": "image_url", "image_url": {"url": str(url)}})
            elif b64:
                # keep data-uri prefix if present
                if provider == "ark":
                    blocks.append({"type": "input_image", "image_url": str(b64)})
                else:
                    blocks.append({"type": "image_url", "image_url": {"url": str(b64)}})
        return blocks

    def _normalize_math_wrong_items(self, wrong_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将 math_steps 中非白名单的 severity 归一化，避免后续 Pydantic 校验报错。"""
        allowed = {sev.value for sev in Severity}
        normalized: List[Dict[str, Any]] = []
        for item in wrong_items or []:
            if not isinstance(item, dict):
                continue
            copy_item = dict(item)
            steps = copy_item.get("math_steps") or copy_item.get("steps")
            if isinstance(steps, list):
                for step in steps:
                    sev = step.get("severity")
                    if isinstance(sev, str):
                        sev_lower = sev.strip().lower()
                        if sev_lower not in allowed:
                            step["severity"] = Severity.UNKNOWN.value
                        else:
                            step["severity"] = sev_lower
            # geometry_check 如果不是 dict/Model，则置空，避免校验失败
            geom = copy_item.get("geometry_check")
            if geom is not None and not isinstance(geom, dict):
                copy_item["geometry_check"] = None
            normalized.append(copy_item)
        return normalized

    def _normalize_judgment_basis(
        self, basis: Any, *, reason: Optional[str] = None
    ) -> List[str]:
        """Clamp judgment_basis to 2-5 short Chinese sentences; fill if missing."""
        out: List[str] = []
        if isinstance(basis, list):
            for item in basis:
                s = str(item).strip()
                if s:
                    out.append(s)
        elif isinstance(basis, str):
            s = basis.strip()
            if s:
                out.append(s)

        reason_line = None
        if reason:
            reason_line = f"依据：{str(reason).strip()}"

        if len(out) < 2 and reason_line and reason_line not in out:
            out.append(reason_line)
        if len(out) < 2:
            out.append("依据题干与作答进行判断")

        if len(out) > 5:
            out = out[:5]
        return out

    def _get_client(self, provider: str = "silicon") -> OpenAI:
        """获取OpenAI兼容客户端"""
        allowed = {"silicon", "ark", "openai"}
        if provider not in allowed:
            raise ValueError(f"Unsupported provider: {provider}")
        if provider == "silicon":
            if not self.silicon_api_key:
                raise ValueError("SILICON_API_KEY not configured")
            return OpenAI(
                base_url=self.silicon_base_url,
                api_key=self.silicon_api_key,
                timeout=float(self.timeout_seconds),
            )
        elif provider == "ark":
            if not self.ark_api_key:
                raise ValueError("ARK_API_KEY not configured")
            return OpenAI(
                base_url=self.ark_base_url,
                api_key=self.ark_api_key,
                timeout=float(self.timeout_seconds),
            )
        elif provider == "openai":
            if not self.openai_api_key:
                raise ValueError("OPENAI_API_KEY not configured")
            return OpenAI(base_url=self.openai_base_url, api_key=self.openai_api_key, timeout=60.0)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    def _parse_tool_arguments(self, raw_args: Any) -> Dict[str, Any]:
        if raw_args is None:
            return {}
        if isinstance(raw_args, dict):
            return raw_args
        raw = str(raw_args)
        try:
            return json.loads(raw)
        except Exception:
            repaired = _repair_json_text(raw)
            if repaired:
                try:
                    return json.loads(repaired)
                except Exception:
                    return {}
        return {}

    def _tool_call_payload(self, call: Any) -> Dict[str, Any]:
        try:
            return call.model_dump()
        except Exception:
            fn = getattr(call, "function", None)
            return {
                "id": getattr(call, "id", None),
                "type": "function",
                "function": {
                    "name": getattr(fn, "name", None),
                    "arguments": getattr(fn, "arguments", None),
                },
            }

    def _run_tool_loop(
        self,
        *,
        client: OpenAI,
        messages: List[Dict[str, Any]],
        provider: str,
        model: str,
        progress_cb: Optional[Any] = None,
    ) -> tuple[List[Dict[str, Any]], Optional[str]]:
        if not self.tool_calling_enabled:
            return messages, None

        registry = get_default_tool_registry()
        tools = registry.openai_tools()
        if not tools:
            return messages, None

        steps = 0
        while steps < self.max_tool_calls:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice=self.tool_choice,
                temperature=0.2,
                max_tokens=800,
            )
            msg = response.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []
            if not tool_calls:
                return messages, msg.content or ""

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [self._tool_call_payload(c) for c in tool_calls],
                }
            )
            for call in tool_calls:
                fn = getattr(call, "function", None)
                name = getattr(fn, "name", None) or ""
                raw_args = getattr(fn, "arguments", None)
                args = self._parse_tool_arguments(raw_args)
                log_event(
                    logger,
                    "tool_call_start",
                    provider=provider,
                    model=model,
                    tool=name,
                )
                t0 = time.monotonic()
                try:
                    if progress_cb:
                        progress_cb(
                            {
                                "tool": name,
                                "status": "running",
                            }
                        )
                    result = registry.call(name, args, progress_cb=progress_cb)
                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    log_event(
                        logger,
                        "tool_call_done",
                        provider=provider,
                        model=model,
                        tool=name,
                        elapsed_ms=elapsed_ms,
                    )
                except Exception as e:
                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    log_event(
                        logger,
                        "tool_call_error",
                        level="warning",
                        provider=provider,
                        model=model,
                        tool=name,
                        error_type=e.__class__.__name__,
                        error=str(e),
                        elapsed_ms=elapsed_ms,
                    )
                    result = {"status": "error", "message": str(e)}

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": getattr(call, "id", None),
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            steps += 1
        return messages, None

    @trace_span("grade_math")
    @trace_span("llm.generate")
    @retry(
        retry=retry_if_exception_type(
            (APIConnectionError, APITimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout)
        ),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        before_sleep=partial(_log_retry, "grade_math"),
        reraise=True,
    )
    def grade_math(
        self,
        text_content: str,
        provider: str = "silicon",
    ) -> MathGradingResult:
        """
        数学批改

        Args:
            text_content: 从图像中提取的文本内容
            provider: 模型提供商 (silicon/ark/openai)

        Returns:
            MathGradingResult: 数学批改结果
        """
        client = self._get_client(provider)

        messages = [
            {"role": "system", "content": MATH_GRADER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""请批改以下数学作业内容：

{text_content}

请返回结构化的JSON结果。""",
            },
        ]

        try:
            model = self.silicon_model if provider == "silicon" else self.ark_model
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                # Full-question `questions[]` can be long; use doubao's max (32768) to avoid truncation.
                max_tokens=32768,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            # Log finish_reason to check if output was truncated
            finish_reason = (
                getattr(response.choices[0], "finish_reason", "unknown") if response.choices else "unknown"
            )
            logger.info(f"[grade_math] finish_reason={finish_reason}, content_len={len(content or '')}")
            try:
                result_data = json.loads(content)
                # Log questions count for debugging
                questions = result_data.get("questions") or []
                logger.info(f"[grade_math] questions_count={len(questions)}, total_items={result_data.get('total_items')}")
                # Output contract hardening:
                # - Do not keep `standard_answer` (avoid leakage + reduce payload).
                # - Keep only the first non-correct step for incorrect/uncertain; omit steps for correct.
                questions = result_data.get("questions")
                if isinstance(questions, list):
                    for q in questions:
                        if not isinstance(q, dict):
                            continue
                        q.pop("standard_answer", None)
                        verdict = (q.get("verdict") or "").strip().lower()
                        steps = q.get("math_steps") or q.get("steps")
                        q["judgment_basis"] = self._normalize_judgment_basis(
                            q.get("judgment_basis"), reason=q.get("reason")
                        )
                        if verdict == "correct":
                            q.pop("math_steps", None)
                            q.pop("steps", None)
                        else:
                            if isinstance(steps, list) and steps:
                                first_bad = None
                                for s in steps:
                                    if isinstance(s, dict) and (s.get("verdict") or "").strip().lower() != "correct":
                                        first_bad = s
                                        break
                                first_bad = first_bad or steps[0]
                                if isinstance(first_bad, dict):
                                    q["math_steps"] = [first_bad]
                            else:
                                q.pop("math_steps", None)
                                q.pop("steps", None)

                if "wrong_items" in result_data:
                    result_data["wrong_items"] = self._normalize_math_wrong_items(result_data.get("wrong_items"))
                    for it in result_data["wrong_items"] or []:
                        if isinstance(it, dict):
                            it.pop("standard_answer", None)
                            it["judgment_basis"] = self._normalize_judgment_basis(
                                it.get("judgment_basis"), reason=it.get("reason")
                            )
                log_event(
                    logger,
                    "llm_grade_math_parsed",
                    provider=provider,
                    model=model,
                    content_len=len(content or ""),
                    questions=len(result_data.get("questions") or []) if isinstance(result_data.get("questions"), list) else None,
                    wrong_items=len(result_data.get("wrong_items") or []) if isinstance(result_data.get("wrong_items"), list) else None,
                    usage=getattr(response, "usage", None) and getattr(response.usage, "model_dump", lambda: None)(),
                )
                return MathGradingResult(**result_data)
            except Exception as parse_err:
                repaired = _repair_json_text(content or "")
                if repaired:
                    try:
                        result_data = json.loads(repaired)
                        if "wrong_items" in result_data:
                            result_data["wrong_items"] = self._normalize_math_wrong_items(result_data.get("wrong_items"))
                            for it in result_data["wrong_items"] or []:
                                if isinstance(it, dict):
                                    it.pop("standard_answer", None)
                                    it["judgment_basis"] = self._normalize_judgment_basis(
                                        it.get("judgment_basis"), reason=it.get("reason")
                                    )
                        questions = result_data.get("questions")
                        if isinstance(questions, list):
                            for q in questions:
                                if isinstance(q, dict):
                                    q["judgment_basis"] = self._normalize_judgment_basis(
                                        q.get("judgment_basis"), reason=q.get("reason")
                                    )
                        log_event(
                            logger,
                            "llm_grade_math_parsed_repaired",
                            provider=provider,
                            model=model,
                            content_len=len(content or ""),
                            repaired_len=len(repaired),
                        )
                        return MathGradingResult(**result_data)
                    except Exception as repair_err:
                        log_event(
                            logger,
                            "llm_grade_math_parse_repair_failed",
                            level="error",
                            provider=provider,
                            model=model,
                            error_type=repair_err.__class__.__name__,
                            error=str(repair_err),
                            content_len=len(content or ""),
                            content_tail=(content or "")[-200:],
                        )
                log_event(
                    logger,
                    "llm_grade_math_parse_failed",
                    level="error",
                    provider=provider,
                    model=model,
                    error_type=parse_err.__class__.__name__,
                    error=str(parse_err),
                    content_len=len(content or ""),
                    content_tail=(content or "")[-200:],
                )
                return MathGradingResult(
                    wrong_items=[],
                    summary="批改结果解析失败",
                    warnings=[f"Parse error: {parse_err}"],
                )

        except (APIConnectionError, APITimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            # Re-raise network/timeout errors so tenacity can trigger retries
            raise e
        except Exception as e:
            log_event(
                logger,
                "llm_grade_math_failed",
                level="error",
                provider=provider,
                model=model if "model" in locals() else None,
                error_type=e.__class__.__name__,
                error=str(e),
            )
            # Return error result for non-retryable errors (or after retries exhausted if wrapped elsewhere)
            # Note: Since tenacity reraise=True, final timeout will propagate out. 
            # If we want to return a Result object on final failure, we'd need an outer wrapper.
            # For now, we follow the instruction to "re-raise network errors".
            return MathGradingResult(
                wrong_items=[],
                summary=f"批改失败: {str(e)}",
                warnings=[f"Error: {str(e)}"],
            )

    @trace_span("grade_english")
    @retry(
        retry=retry_if_exception_type(
            (APIConnectionError, APITimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout)
        ),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        before_sleep=partial(_log_retry, "grade_english"),
        reraise=True,
    )
    def grade_english(
        self,
        text_content: str,
        mode: SimilarityMode = SimilarityMode.NORMAL,
        provider: str = "silicon",
    ) -> EnglishGradingResult:
        """
        英语批改

        Args:
            text_content: 从图像中提取的文本内容
            mode: 判分模式 (normal/strict)
            provider: 模型提供商

        Returns:
            EnglishGradingResult: 英语批改结果
        """
        client = self._get_client(provider)

        messages = [
            {"role": "system", "content": ENGLISH_GRADER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""请批改以下英语作业内容：

{text_content}

判分模式: {mode.value}

请返回结构化的JSON结果。""",
            },
        ]

        try:
            model = self.silicon_model if provider == "silicon" else self.ark_model
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=32768,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            try:
                result_data = json.loads(content)
                questions = result_data.get("questions")
                if isinstance(questions, list):
                    for q in questions:
                        if isinstance(q, dict):
                            q["judgment_basis"] = self._normalize_judgment_basis(
                                q.get("judgment_basis"), reason=q.get("reason")
                            )
                wrong_items = result_data.get("wrong_items")
                if isinstance(wrong_items, list):
                    for it in wrong_items:
                        if isinstance(it, dict):
                            it["judgment_basis"] = self._normalize_judgment_basis(
                                it.get("judgment_basis"), reason=it.get("reason")
                            )
                log_event(
                    logger,
                    "llm_grade_english_parsed",
                    provider=provider,
                    model=model,
                    content_len=len(content or ""),
                    questions=len(result_data.get("questions") or []) if isinstance(result_data.get("questions"), list) else None,
                    wrong_items=len(result_data.get("wrong_items") or []) if isinstance(result_data.get("wrong_items"), list) else None,
                    usage=getattr(response, "usage", None) and getattr(response.usage, "model_dump", lambda: None)(),
                )
                return EnglishGradingResult(**result_data)
            except Exception as parse_err:
                repaired = _repair_json_text(content or "")
                if repaired:
                    try:
                        result_data = json.loads(repaired)
                        questions = result_data.get("questions")
                        if isinstance(questions, list):
                            for q in questions:
                                if isinstance(q, dict):
                                    q["judgment_basis"] = self._normalize_judgment_basis(
                                        q.get("judgment_basis"), reason=q.get("reason")
                                    )
                        wrong_items = result_data.get("wrong_items")
                        if isinstance(wrong_items, list):
                            for it in wrong_items:
                                if isinstance(it, dict):
                                    it["judgment_basis"] = self._normalize_judgment_basis(
                                        it.get("judgment_basis"), reason=it.get("reason")
                                    )
                        log_event(
                            logger,
                            "llm_grade_english_parsed_repaired",
                            provider=provider,
                            model=model,
                            content_len=len(content or ""),
                            repaired_len=len(repaired),
                        )
                        return EnglishGradingResult(**result_data)
                    except Exception as repair_err:
                        log_event(
                            logger,
                            "llm_grade_english_parse_repair_failed",
                            level="error",
                            provider=provider,
                            model=model,
                            error_type=repair_err.__class__.__name__,
                            error=str(repair_err),
                            content_len=len(content or ""),
                            content_tail=(content or "")[-200:],
                        )
                log_event(
                    logger,
                    "llm_grade_english_parse_failed",
                    level="error",
                    provider=provider,
                    model=model,
                    error_type=parse_err.__class__.__name__,
                    error=str(parse_err),
                    content_len=len(content or ""),
                    content_tail=(content or "")[-200:],
                )
                return EnglishGradingResult(
                    wrong_items=[],
                    summary="批改结果解析失败",
                    warnings=[f"Parse error: {parse_err}"],
                )

        except (APIConnectionError, APITimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            raise e
        except Exception as e:
            log_event(
                logger,
                "llm_grade_english_failed",
                level="error",
                provider=provider,
                model=model if "model" in locals() else None,
                error_type=e.__class__.__name__,
                error=str(e),
            )
            return EnglishGradingResult(
                wrong_items=[],
                summary=f"批改失败: {str(e)}",
                warnings=[f"Error: {str(e)}"],
            )

    @trace_span("socratic_tutor")
    @retry(
        retry=retry_if_exception_type(
            (APIConnectionError, APITimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout)
        ),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        before_sleep=partial(_log_retry, "socratic_tutor"),
        reraise=True,
    )
    def socratic_tutor(
        self,
        question: str,
        wrong_item_context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        interaction_count: int = 0,
        provider: str = "silicon",
        model_override: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> SocraticTutorResult:
        """
        苏格拉底式辅导

        Args:
            question: 学生的问题
            wrong_item_context: 错误项上下文
            session_id: 会话ID
            interaction_count: 当前交互次数
            provider: 模型提供商

        Returns:
            SocraticTutorResult: 辅导结果
        """
        client = self._get_client(provider)

        # 递进提示策略，根据交互次数构造引导语（无硬性最后一轮）
        turn = interaction_count % 3
        if turn == 0:
            strategy = "轻提示：肯定已正确部分，指出第一个疑点，不给答案。"
        elif turn == 1:
            strategy = "方向提示：指向相关公式/概念/检查点，不给答案。"
        else:
            strategy = "重提示：指出错误类型或可能位置，但仍不直接给答案。"

        # Build a normal chat transcript so the model can follow the user's flow.
        meta = {
            "session_id": session_id or "N/A",
            "interaction_count": interaction_count,
            "strategy": strategy,
        }
        messages = [{"role": "system", "content": SOCRATIC_TUTOR_SYSTEM_PROMPT}]
        if wrong_item_context:
            messages.append(
                {
                    "role": "system",
                    "content": "本次作业辅导上下文（仅供参考，勿编造；若存在歧义/误读提示，请优先向学生确认）：\n"
                    + json.dumps(jsonable_encoder(wrong_item_context), ensure_ascii=False),
                }
            )
        messages.append(
            {
                "role": "system",
                "content": "会话元信息（勿原样复述给学生）：\n"
                + json.dumps(meta, ensure_ascii=False),
            }
        )

        # Include a short tail of history so the model can react naturally (e.g., user corrections).
        if history:
            tail = history[-12:]
            for m in tail:
                role = (m.get("role") if isinstance(m, dict) else None) or None
                content = (m.get("content") if isinstance(m, dict) else None) or ""
                if role not in {"user", "assistant", "system"}:
                    continue
                messages.append({"role": role, "content": str(content)})

        # Ensure the current user question is included as the last message.
        if not messages or messages[-1]["role"] != "user" or messages[-1]["content"] != str(question):
            messages.append({"role": "user", "content": str(question)})

        try:
            if model_override:
                model = model_override
            else:
                model = self.silicon_model if provider == "silicon" else self.ark_model

            messages, tool_content = self._run_tool_loop(
                client=client,
                messages=messages,
                provider=provider,
                model=model,
            )
            if tool_content is not None:
                content = tool_content
            else:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.4,
                    max_tokens=800,
                )
                content = response.choices[0].message.content

            status = "continue"

            return SocraticTutorResult(
                messages=[{"role": "assistant", "content": content}],
                session_id=session_id,
                status=status,
                interaction_count=interaction_count + 1,
            )

        except (APIConnectionError, APITimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            raise e
        except Exception as e:
            logger.error(f"Socratic tutoring failed: {str(e)}")
            return SocraticTutorResult(
                messages=[{"role": "assistant", "content": f"抱歉，辅导服务暂时不可用: {str(e)}"}],
                session_id=session_id,
                status="error",
                interaction_count=interaction_count,
            )

    def _extract_slice_url_from_context(self, wrong_item_context: Optional[Dict[str, Any]]) -> Optional[str]:
        """从辅导上下文中提取切片 URL"""
        if not wrong_item_context:
            return None

        focus_question = wrong_item_context.get("focus_question")
        if not isinstance(focus_question, dict):
            return None

        def _extract_from_pages(pages):
            """从 pages 列表中提取切片 URL"""
            if not isinstance(pages, list):
                return None
            for p in pages:
                if not isinstance(p, dict):
                    continue
                # 优先：regions 中标注为 figure 的切片（几何题通常必须看图）
                regions = p.get("regions")
                if isinstance(regions, list):
                    for r in regions:
                        if not isinstance(r, dict):
                            continue
                        if (r.get("kind") or "").lower() == "figure" and r.get("slice_image_url"):
                            return str(r.get("slice_image_url"))
                # 优先选择 slice_image_urls（列表）
                slice_urls = p.get("slice_image_urls")
                if isinstance(slice_urls, list) and slice_urls:
                    return str(slice_urls[0])
                # 备选：slice_image_url（单个）
                slice_url = p.get("slice_image_url")
                if slice_url:
                    return str(slice_url)
                # 再备选：regions 中的切片
                if isinstance(regions, list):
                    for r in regions:
                        if isinstance(r, dict):
                            r_slice = r.get("slice_image_url")
                            if r_slice:
                                return str(r_slice)
            return None

        # 方式1：从 image_refs 中提取（如果存在）
        image_refs = focus_question.get("image_refs")
        if isinstance(image_refs, dict):
            pages = image_refs.get("pages")
            url = _extract_from_pages(pages)
            if url:
                return url

        # 方式2：从 focus_question.pages 中直接提取（qindex 数据结构）
        pages = focus_question.get("pages")
        url = _extract_from_pages(pages)
        if url:
            return url

        # 回退到 page_image_urls
        page_urls = focus_question.get("page_image_urls")
        if isinstance(page_urls, list) and page_urls:
            return str(page_urls[0])

        # 最后一个回退：单个 page_image_url
        page_url = focus_question.get("page_image_url")
        if page_url:
            return str(page_url)

        return None

    def socratic_tutor_stream(
        self,
        *,
        question: str,
        wrong_item_context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        interaction_count: int = 0,
        provider: str = "silicon",
        model_override: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Iterable[Any]:
        """
        Stream 苏格拉底式辅导输出（同步生成器，供 SSE 透传）。
        - 仅产出文本增量，不返回结构化 status/interaction_count（调用方自行更新会话状态）。
        """
        client = self._get_client(provider)

        turn = interaction_count % 3
        if turn == 0:
            strategy = "轻提示：肯定已正确部分，指出第一个疑点，不给答案。"
        elif turn == 1:
            strategy = "方向提示：指向相关公式/概念/检查点，不给答案。"
        else:
            strategy = "重提示：指出错误类型或可能位置，但仍不直接给答案。"

        meta = {
            "session_id": session_id or "N/A",
            "interaction_count": interaction_count,
            "strategy": strategy,
        }
        messages: List[Dict[str, str]] = [{"role": "system", "content": SOCRATIC_TUTOR_SYSTEM_PROMPT}]
        # For visually risky questions, force the model to anchor on the image first (facts before reasoning).
        has_visual_facts = False
        gate_passed = False
        try:
            focus_q = (wrong_item_context or {}).get("focus_question") if isinstance(wrong_item_context, dict) else None
            visual_risk = bool(isinstance(focus_q, dict) and focus_q.get("visual_risk") is True)
            has_visual_facts = bool(isinstance(focus_q, dict) and isinstance(focus_q.get("visual_facts"), dict))
            gate = focus_q.get("vfe_gate") if isinstance(focus_q, dict) else None
            gate_passed = bool(isinstance(gate, dict) and gate.get("passed") is True)
            if visual_risk:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "该题为图形/视觉风险题。若上下文提供了 visual_facts（VFE 结构化事实），"
                            "必须把它当作唯一可引用的“图上事实来源”；若提供 hypotheses，需先检查其 evidence 是否与 facts 一致再引用；"
                            "不要根据图片自行补充或改写事实；"
                            "若 visual_facts 缺失/不足，请明确说明“视觉事实不足”，再基于识别原文给出解释，并提示可能不确定。"
                        ),
                    }
                )
        except Exception:
            pass
        if wrong_item_context:
            messages.append(
                {
                    "role": "system",
                    "content": "本次作业辅导上下文（仅供参考，勿编造；若存在歧义/误读提示，请优先向学生确认）：\n"
                    + json.dumps(jsonable_encoder(wrong_item_context), ensure_ascii=False),
                }
            )
        messages.append(
            {
                "role": "system",
                "content": "会话元信息（勿原样复述给学生）：\n"
                + json.dumps(meta, ensure_ascii=False),
            }
        )

        # Append a short tail of history (so the model can react to user corrections).
        # IMPORTANT: do not let a fixed “请结合图片…” message override the user's real input.
        current_question = str(question)
        last_user_idx: Optional[int] = None
        if history:
            tail = history[-12:]
            for m in tail:
                role = (m.get("role") if isinstance(m, dict) else None) or None
                content = (m.get("content") if isinstance(m, dict) else None) or ""
                if role not in {"user", "assistant", "system"}:
                    continue
                messages.append({"role": role, "content": str(content)})
                if role == "user" and str(content) == current_question:
                    last_user_idx = len(messages) - 1

        # Ensure the current user question is present as the latest turn.
        # (Upstream usually appends it into `history`, but keep this defensive.)
        if last_user_idx is None:
            messages.append({"role": "user", "content": current_question})
            last_user_idx = len(messages) - 1
        else:
            # If the last message isn't the current question (e.g. mis-ordered history),
            # append a fresh copy so the model answers the right prompt.
            if messages[-1].get("role") != "user" or messages[-1].get("content") != current_question:
                messages.append({"role": "user", "content": current_question})
                last_user_idx = len(messages) - 1

        # Stable mode: do not attach images to chat LLM; rely on cached visual_facts only.

        model = model_override or (self.silicon_model if provider == "silicon" else self.ark_model)

        tool_events: List[Dict[str, Any]] = []

        def _progress_cb(payload: Dict[str, Any]) -> None:
            tool_events.append({"event": "tool_progress", "data": payload})

        messages, tool_content = self._run_tool_loop(
            client=client,
            messages=messages,
            provider=provider,
            model=model,
            progress_cb=_progress_cb,
        )

        for evt in tool_events:
            yield evt

        if tool_content is not None:
            yield tool_content
            return

        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.4,
            # Allow longer tutoring responses; UI streaming handles incremental rendering.
            max_tokens=1600,
            stream=True,
        )
        for event in stream:
            try:
                choice = (getattr(event, "choices", None) or [None])[0]
                delta = getattr(choice, "delta", None)
                text = getattr(delta, "content", None)
                if text:
                    yield text
            except Exception:
                continue

    @retry(
        retry=retry_if_exception_type(
            (APIConnectionError, APITimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout)
        ),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        before_sleep=partial(_log_retry, "generate"),
        reraise=True,
    )
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        provider: str = "silicon",
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> LLMResult:
        """
        通用文本生成

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            provider: 模型提供商
            max_tokens: 最大令牌数
            temperature: 温度参数

        Returns:
            LLMResult: 包含文本和原始响应的结果
        """
        client = self._get_client(provider)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            model = self.silicon_model if provider == "silicon" else self.ark_model
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            return LLMResult(
                text=response.choices[0].message.content,
                raw=response.to_dict(),
                usage={
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                    "total_tokens": getattr(response.usage, "total_tokens", 0),
                }
            )

        except (APIConnectionError, APITimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            raise e
        except Exception as e:
            logger.error(f"LLM generation failed: {str(e)}")
            return LLMResult(
                text=f"生成失败: {str(e)}",
                raw={"error": str(e)},
            )

    def generate_with_images(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        images: List["ImageRef"],
        provider: str = "silicon",
        max_tokens: int = 1600,
        temperature: float = 0.2,
        use_tools: bool = False,
    ) -> LLMResult:
        """
        Multimodal generation with images + text prompt.
        Uses chat.completions for SiliconFlow; Ark uses responses API when tools are off.
        """
        client = self._get_client(provider)
        use_tools = bool(use_tools and provider != "ark")

        if provider == "silicon":
            model = self.silicon_vision_model or self.silicon_model
            content_blocks = [{"type": "text", "text": user_prompt}] + self._image_blocks_from_refs(images, provider)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content_blocks},
            ]
            if use_tools:
                messages, tool_content = self._run_tool_loop(
                    client=client,
                    messages=messages,
                    provider=provider,
                    model=model,
                )
                if tool_content is not None:
                    return LLMResult(text=tool_content, raw={})
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return LLMResult(
                text=response.choices[0].message.content,
                raw=response.to_dict(),
                usage={
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                    "total_tokens": getattr(response.usage, "total_tokens", 0),
                },
            )

        if provider == "ark":
            model = self.ark_vision_model or self.ark_model
            content_blocks: List[Dict[str, Any]] = [{"type": "input_text", "text": user_prompt}]
            content_blocks += self._image_blocks_from_refs(images, provider)
            # responses API does not support tool calls; use direct call.
            resp = client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                    {"role": "user", "content": content_blocks},
                ],
            )
            text_parts: List[str] = []
            for item in getattr(resp, "output", []) or []:
                for c in getattr(item, "content", []) or []:
                    if getattr(c, "type", None) == "output_text":
                        text_parts.append(getattr(c, "text", ""))
            return LLMResult(text="\n".join(text_parts), raw=resp.to_dict())

        raise ValueError(f"Unsupported provider for generate_with_images: {provider}")
