from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import os


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", validation_alias="OPENAI_BASE_URL")
    model_reasoning: str = Field(default="gpt-4o", validation_alias="MODEL_REASONING")
    model_vision: str = Field(default="gpt-4o", validation_alias="MODEL_VISION")

    silicon_api_key: str | None = Field(default=None, validation_alias="SILICON_API_KEY")
    silicon_base_url: str = Field(default="https://api.siliconflow.cn/v1", validation_alias="SILICON_BASE_URL")
    silicon_vision_model: str = Field(default="Qwen/Qwen3-VL-32B-Thinking", validation_alias="SILICON_VISION_MODEL")
    # Strict user requirement: Use Qwen3-VL-32B-Thinking for reasoning as well
    silicon_reasoning_model: str = Field(default="Qwen/Qwen3-VL-32B-Thinking", validation_alias="SILICON_REASONING_MODEL")

    ark_api_key: str | None = Field(default=None, validation_alias="ARK_API_KEY")
    ark_base_url: str = Field(default="https://ark.cn-beijing.volces.com/api/v3", validation_alias="ARK_BASE_URL")
    ark_vision_model: str = Field(default="doubao-seed-1-6-vision-250815", validation_alias="ARK_VISION_MODEL")
    # Ark/Doubao text reasoning models for chat/grading
    ark_reasoning_model: str = Field(default="Doubao-Seed-1-6", validation_alias="ARK_REASONING_MODEL")
    ark_reasoning_model_thinking: str = Field(
        default="Doubao-Seed-1-6-thinking",
        validation_alias="ARK_REASONING_MODEL_THINKING",
    )

    # Baidu PaddleOCR-VL (OCR + layout)
    baidu_ocr_api_key: str | None = Field(default=None, validation_alias="BAIDU_OCR_API_KEY")
    baidu_ocr_secret_key: str | None = Field(default=None, validation_alias="BAIDU_OCR_SECRET_KEY")
    baidu_ocr_oauth_url: str = Field(
        default="https://aip.baidubce.com/oauth/2.0/token",
        validation_alias="BAIDU_OCR_OAUTH_URL",
    )
    baidu_ocr_submit_url: str = Field(
        default="https://aip.baidubce.com/rest/2.0/brain/online/v2/paddle-vl-parser/task",
        validation_alias="BAIDU_OCR_SUBMIT_URL",
    )
    baidu_ocr_query_url: str = Field(
        default="https://aip.baidubce.com/rest/2.0/brain/online/v2/paddle-vl-parser/task/query",
        validation_alias="BAIDU_OCR_QUERY_URL",
    )
    baidu_ocr_timeout_seconds: int = Field(default=60, validation_alias="BAIDU_OCR_TIMEOUT_SECONDS")
    baidu_ocr_poll_interval_seconds: float = Field(
        # Baidu doc recommends polling every 5-10 seconds (query QPS limit applies).
        default=5.0, validation_alias="BAIDU_OCR_POLL_INTERVAL_SECONDS"
    )
    baidu_ocr_poll_max_seconds: int = Field(
        default=60, validation_alias="BAIDU_OCR_POLL_MAX_SECONDS"
    )

    # OCR provider for qindex (bbox/slice). Default: SiliconFlow DeepSeek-OCR.
    # Values:
    # - siliconflow_qwen3_vl: use SiliconFlow vision model (Qwen3-VL) to locate per-question bbox (recommended)
    # - siliconflow_deepseek: use SiliconFlow chat-completions with deepseek-ai/DeepSeek-OCR
    # - baidu_paddleocr_vl: use Baidu PaddleOCR-VL (legacy; can be disabled if quota is limited)
    # - disabled: do not run OCR (qindex will be skipped)
    ocr_provider: str = Field(default="siliconflow_qwen3_vl", validation_alias="OCR_PROVIDER")

    # SiliconFlow OCR model (OpenAI-compatible chat completions)
    silicon_ocr_model: str = Field(
        default="deepseek-ai/DeepSeek-OCR",
        validation_alias="SILICON_OCR_MODEL",
    )
    silicon_ocr_timeout_seconds: int = Field(
        default=60,
        validation_alias="SILICON_OCR_TIMEOUT_SECONDS",
    )
    silicon_ocr_max_tokens: int = Field(
        default=2048,
        validation_alias="SILICON_OCR_MAX_TOKENS",
    )

    # SiliconFlow qindex locator model (vision, bbox-only; recommended for slices)
    silicon_qindex_model: str = Field(
        default="Qwen/Qwen3-VL-32B-Thinking",
        validation_alias="SILICON_QINDEX_MODEL",
    )
    silicon_qindex_timeout_seconds: int = Field(
        default=180,
        validation_alias="SILICON_QINDEX_TIMEOUT_SECONDS",
    )
    silicon_qindex_max_tokens: int = Field(
        default=900,
        validation_alias="SILICON_QINDEX_MAX_TOKENS",
    )

    # Ark qindex locator model (vision, bbox-only; optional)
    ark_qindex_model: str = Field(
        default="doubao-seed-1-6-vision-250815",
        validation_alias="ARK_QINDEX_MODEL",
    )
    ark_qindex_timeout_seconds: int = Field(
        default=180,
        validation_alias="ARK_QINDEX_TIMEOUT_SECONDS",
    )
    ark_qindex_max_tokens: int = Field(
        default=900,
        validation_alias="ARK_QINDEX_MAX_TOKENS",
    )

    # Slice generation (BBox + Slice)
    slice_padding_ratio: float = Field(default=0.05, validation_alias="SLICE_PADDING_RATIO")
    slice_ttl_seconds: int = Field(default=24 * 3600, validation_alias="SLICE_TTL_SECONDS")

    # SLA / Time budgets (seconds)
    grade_completion_sla_seconds: int = Field(
        # Completion SLA should cover both Vision and LLM budgets (+ margin).
        default=600, validation_alias="GRADE_COMPLETION_SLA_SECONDS"
    )
    grade_vision_timeout_seconds: int = Field(
        # Vision can be slow on some images; keep a safer default than 60s.
        default=240, validation_alias="GRADE_VISION_TIMEOUT_SECONDS"
    )
    grade_llm_timeout_seconds: int = Field(
        # Full-question grading JSON can be slow; keep a safer default.
        default=300, validation_alias="GRADE_LLM_TIMEOUT_SECONDS"
    )
    vision_client_timeout_seconds: int = Field(
        # Low-level client timeout should not undercut grade vision budget.
        default=240, validation_alias="VISION_CLIENT_TIMEOUT_SECONDS"
    )
    llm_client_timeout_seconds: int = Field(
        default=300, validation_alias="LLM_CLIENT_TIMEOUT_SECONDS"
    )

    # Concurrency limits (to avoid thread pile-ups)
    max_concurrent_vision: int = Field(default=2, validation_alias="MAX_CONCURRENT_VISION")
    max_concurrent_llm: int = Field(default=4, validation_alias="MAX_CONCURRENT_LLM")

    # QIndex worker queue (Redis required)
    qindex_queue_name: str = Field(default="qindex:queue", validation_alias="QINDEX_QUEUE_NAME")

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    allow_origins: list[str] = Field(default=["*"], validation_alias="ALLOW_ORIGINS")
    log_to_file: bool = Field(default=True, validation_alias="LOG_TO_FILE")
    log_file_path: str = Field(
        default=os.path.join("logs", "backend.log"),
        validation_alias="LOG_FILE_PATH",
    )

    # Auth (Phase A): when enabled, endpoints require Authorization: Bearer <jwt>
    # and will derive user_id from Supabase Auth token; otherwise dev fallback applies.
    auth_required: bool = Field(default=False, validation_alias="AUTH_REQUIRED")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
