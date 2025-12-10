"""
LLM Client - 文本推理客户端

支持:
- qwen3 (SiliconFlow) 和 doubao (Ark) 国内模型
- 数学/英语批改和苏格拉底辅导提示词
- 结构化JSON输出
- 批处理支持
"""

import json
import logging
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field

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

from core.prompts import (
    MATH_GRADER_SYSTEM_PROMPT,
    ENGLISH_GRADER_SYSTEM_PROMPT,
    SOCRATIC_TUTOR_SYSTEM_PROMPT,
)
from models.schemas import Subject, SimilarityMode, Severity
from utils.settings import get_settings

logger = logging.getLogger(__name__)


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
    wrong_items: List[Dict[str, Any]] = Field(default_factory=list, description="错误项列表")
    summary: str = Field(..., description="总体摘要")
    subject: Subject = Subject.MATH
    total_items: Optional[int] = Field(None, description="检测到的题目总数")
    wrong_count: Optional[int] = Field(None, description="错误数量")
    cross_subject_flag: Optional[bool] = Field(None, description="跨学科标记")
    warnings: List[str] = Field(default_factory=list, description="警告信息")


class EnglishGradingResult(BaseModel):
    """英语批改结果"""
    wrong_items: List[Dict[str, Any]] = Field(default_factory=list, description="错误项列表")
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

        # OpenAI配置 (可选)
        self.openai_api_key = settings.openai_api_key
        self.openai_base_url = settings.openai_base_url
        self.model_reasoning = settings.model_reasoning

        # SiliconFlow配置 (qwen3)
        self.silicon_api_key = settings.silicon_api_key
        self.silicon_base_url = settings.silicon_base_url
        # 使用专用配置，若未设置则回退到 generic model_reasoning (需确保兼容) 或默认值
        self.silicon_model = settings.silicon_reasoning_model or settings.model_reasoning

        # Ark配置 (doubao)
        self.ark_api_key = settings.ark_api_key
        self.ark_base_url = settings.ark_base_url
        # Doubao 文本模型（可通过环境变量 model_reasoning 覆盖）
        self.ark_model = settings.model_reasoning

    def _normalize_math_wrong_items(self, wrong_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将 math_steps 中非白名单的 severity 归一化，避免后续 Pydantic 校验报错。"""
        allowed = {sev.value for sev in Severity}
        normalized: List[Dict[str, Any]] = []
        for item in wrong_items or []:
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

    def _get_client(self, provider: str = "silicon") -> OpenAI:
        """获取OpenAI兼容客户端"""
        allowed = {"silicon", "ark", "openai"}
        if provider not in allowed:
            raise ValueError(f"Unsupported provider: {provider}")
        if provider == "silicon":
            if not self.silicon_api_key:
                raise ValueError("SILICON_API_KEY not configured")
            return OpenAI(base_url=self.silicon_base_url, api_key=self.silicon_api_key, timeout=300.0)
        elif provider == "ark":
            if not self.ark_api_key:
                raise ValueError("ARK_API_KEY not configured")
            return OpenAI(base_url=self.ark_base_url, api_key=self.ark_api_key, timeout=120.0)
        elif provider == "openai":
            if not self.openai_api_key:
                raise ValueError("OPENAI_API_KEY not configured")
            return OpenAI(base_url=self.openai_base_url, api_key=self.openai_api_key, timeout=60.0)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

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
                max_tokens=2000,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            try:
                result_data = json.loads(content)
                if "wrong_items" in result_data:
                    result_data["wrong_items"] = self._normalize_math_wrong_items(result_data.get("wrong_items"))
                return MathGradingResult(**result_data)
            except Exception as parse_err:
                logger.error(f"Math grading parse failed: {parse_err}; raw content: {content}")
                return MathGradingResult(
                    wrong_items=[],
                    summary="批改结果解析失败",
                    warnings=[f"Parse error: {parse_err}"],
                )

        except (APIConnectionError, APITimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            # Re-raise network/timeout errors so tenacity can trigger retries
            raise e
        except Exception as e:
            logger.error(f"Math grading failed: {str(e)}")
            # Return error result for non-retryable errors (or after retries exhausted if wrapped elsewhere)
            # Note: Since tenacity reraise=True, final timeout will propagate out. 
            # If we want to return a Result object on final failure, we'd need an outer wrapper.
            # For now, we follow the instruction to "re-raise network errors".
            return MathGradingResult(
                wrong_items=[],
                summary=f"批改失败: {str(e)}",
                warnings=[f"Error: {str(e)}"],
            )

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
                max_tokens=2000,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            try:
                result_data = json.loads(content)
                return EnglishGradingResult(**result_data)
            except Exception as parse_err:
                logger.error(f"English grading parse failed: {parse_err}; raw content: {content}")
                return EnglishGradingResult(
                    wrong_items=[],
                    summary="批改结果解析失败",
                    warnings=[f"Parse error: {parse_err}"],
                )

        except (APIConnectionError, APITimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            raise e
        except Exception as e:
            logger.error(f"English grading failed: {str(e)}")
            return EnglishGradingResult(
                wrong_items=[],
                summary=f"批改失败: {str(e)}",
                warnings=[f"Error: {str(e)}"],
            )

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

        # 递进提示策略，根据交互次数构造引导语
        turn = min(interaction_count, 4)
        if turn == 0:
            strategy = "轻提示：肯定已正确部分，指出第一个疑点，不给答案。"
        elif turn == 1:
            strategy = "方向提示：指向相关公式/概念/检查点，不给答案。"
        elif turn == 2:
            strategy = "重提示：指出错误类型或可能位置，不给结果。"
        elif turn == 3:
            strategy = "引导验证：引导逐步验证关键步骤，仍不直接给答案。"
        else:
            strategy = "最后一轮：如仍未解决，提供完整解析。"

        context_text = ""
        if wrong_item_context:
            context_text = f"\n\n错误上下文: {json.dumps(wrong_item_context, ensure_ascii=False)}"

        messages = [
            {"role": "system", "content": SOCRATIC_TUTOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""学生问题: {question}{context_text}

当前交互次数: {interaction_count}/5
会话ID: {session_id or 'N/A'}
引导策略: {strategy}

请按策略提供引导式辅导，若为最后一轮可给出解析。""",
            },
        ]

        try:
            model = self.silicon_model if provider == "silicon" else self.ark_model
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
            )

            content = response.choices[0].message.content

            # 判断状态：第 5 轮（interaction_count>=4）可给解析，标记 explained
            status = "continue"
            if interaction_count >= 4:
                status = "explained"

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
