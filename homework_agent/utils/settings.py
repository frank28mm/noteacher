from functools import lru_cache
import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App environment
    # dev | test | staging | prod
    app_env: str = Field(default="dev", validation_alias="APP_ENV")

    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1", validation_alias="OPENAI_BASE_URL"
    )
    model_reasoning: str = Field(default="gpt-4o", validation_alias="MODEL_REASONING")
    model_vision: str = Field(default="gpt-4o", validation_alias="MODEL_VISION")

    silicon_api_key: str | None = Field(
        default=None, validation_alias="SILICON_API_KEY"
    )
    silicon_base_url: str = Field(
        default="https://api.siliconflow.cn/v1", validation_alias="SILICON_BASE_URL"
    )
    silicon_vision_model: str = Field(
        default="Qwen/Qwen3-VL-32B-Thinking", validation_alias="SILICON_VISION_MODEL"
    )
    # Strict user requirement: Use Qwen3-VL-32B-Thinking for reasoning as well
    silicon_reasoning_model: str = Field(
        default="Qwen/Qwen3-VL-235B-A22B-Instruct",
        validation_alias="SILICON_REASONING_MODEL",
    )

    ark_api_key: str | None = Field(default=None, validation_alias="ARK_API_KEY")
    ark_base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/v3",
        validation_alias="ARK_BASE_URL",
    )
    ark_vision_model: str = Field(
        default="doubao-seed-1-6-vision-250815", validation_alias="ARK_VISION_MODEL"
    )
    # Ark built-in image processing tool (image_process: zoom/rotate/grounding/point).
    # Default off: enable only after verification against Ark Responses API behavior.
    ark_image_process_enabled: bool = Field(
        default=False, validation_alias="ARK_IMAGE_PROCESS_ENABLED"
    )
    # Ark Responses API output cap (max_output_tokens). Default off because deep-thinking models may spend
    # the entire cap on reasoning and fail to emit final output_text (causing parse_failed).
    ark_responses_enable_output_cap: bool = Field(
        default=False, validation_alias="ARK_RESPONSES_ENABLE_OUTPUT_CAP"
    )
    # /grade experiment: choose image input strategy for Ark to isolate URL-fetch latency.
    # Values: auto|url|proxy|data_url_first_page|data_url_on_small_figure
    grade_image_input_variant: str = Field(
        default="url", validation_alias="GRADE_IMAGE_INPUT_VARIANT"
    )
    # Ark/Doubao text reasoning models for chat/grading
    ark_reasoning_model: str = Field(
        default="Doubao-Seed-1-6", validation_alias="ARK_REASONING_MODEL"
    )
    ark_reasoning_model_thinking: str = Field(
        default="Doubao-Seed-1-6-thinking",
        validation_alias="ARK_REASONING_MODEL_THINKING",
    )
    ark_report_model: str = Field(
        default="doubao-seed-1-6-251015",
        validation_alias="ARK_REPORT_MODEL",
    )
    # Narrative Layer (LLM) for reports: enabled by default (set REPORT_NARRATIVE_ENABLED=0 for deterministic E2E).
    report_narrative_enabled: bool = Field(
        default=True, validation_alias="REPORT_NARRATIVE_ENABLED"
    )

    # Baidu PaddleOCR-VL (OCR + layout)
    baidu_ocr_api_key: str | None = Field(
        default=None, validation_alias="BAIDU_OCR_API_KEY"
    )
    baidu_ocr_secret_key: str | None = Field(
        default=None, validation_alias="BAIDU_OCR_SECRET_KEY"
    )
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
    baidu_ocr_timeout_seconds: int = Field(
        default=60, validation_alias="BAIDU_OCR_TIMEOUT_SECONDS"
    )
    baidu_ocr_poll_interval_seconds: float = Field(
        # Baidu doc recommends polling every 5-10 seconds (query QPS limit applies).
        default=5.0,
        validation_alias="BAIDU_OCR_POLL_INTERVAL_SECONDS",
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
    ocr_provider: str = Field(
        default="siliconflow_qwen3_vl", validation_alias="OCR_PROVIDER"
    )

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
    slice_padding_ratio: float = Field(
        default=0.05, validation_alias="SLICE_PADDING_RATIO"
    )
    slice_ttl_seconds: int = Field(
        default=24 * 3600, validation_alias="SLICE_TTL_SECONDS"
    )

    # SLA / Time budgets (seconds)
    grade_completion_sla_seconds: int = Field(
        # Completion SLA should cover both Vision (240s) and LLM (600s) budgets (+ margin).
        default=900,
        validation_alias="GRADE_COMPLETION_SLA_SECONDS",
    )
    grade_vision_timeout_seconds: int = Field(
        # Vision can be slow on some images; keep a safer default than 60s.
        default=240,
        validation_alias="GRADE_VISION_TIMEOUT_SECONDS",
    )
    grade_llm_timeout_seconds: int = Field(
        # Full-question grading JSON can be slow; 600s (10min) for large homework with detailed judgment_basis.
        default=600,
        validation_alias="GRADE_LLM_TIMEOUT_SECONDS",
    )
    # Chat (SSE)
    chat_heartbeat_interval_seconds: float = Field(
        # SSE heartbeat cadence when LLM is "thinking" / no tokens are produced.
        default=30.0,
        validation_alias="CHAT_HEARTBEAT_INTERVAL_SECONDS",
    )
    chat_idle_disconnect_seconds: float = Field(
        # Optional: if the LLM produces no stream chunks for too long, close the SSE connection.
        # This is a safety valve for stuck upstream streams; set to 0 to disable.
        default=0.0,
        validation_alias="CHAT_IDLE_DISCONNECT_SECONDS",
    )
    chat_producer_join_timeout_seconds: float = Field(
        # When the SSE consumer finishes early, don't block forever waiting for the producer thread.
        default=1.0,
        validation_alias="CHAT_PRODUCER_JOIN_TIMEOUT_SECONDS",
    )
    chat_relook_enabled: bool = Field(
        # Optional: enable best-effort VFE relook in /chat for visually risky disputes.
        default=False,
        validation_alias="CHAT_RELOOK_ENABLED",
    )
    vision_client_timeout_seconds: int = Field(
        # Low-level client timeout should not undercut grade vision budget.
        default=240,
        validation_alias="VISION_CLIENT_TIMEOUT_SECONDS",
    )
    llm_client_timeout_seconds: int = Field(
        default=600, validation_alias="LLM_CLIENT_TIMEOUT_SECONDS"
    )
    tool_calling_enabled: bool = Field(
        default=True, validation_alias="TOOL_CALLING_ENABLED"
    )
    max_tool_calls: int = Field(default=3, validation_alias="MAX_TOOL_CALLS")
    tool_choice: str = Field(default="auto", validation_alias="TOOL_CHOICE")

    # Concurrency limits (to avoid thread pile-ups)
    max_concurrent_vision: int = Field(
        default=2, validation_alias="MAX_CONCURRENT_VISION"
    )
    max_concurrent_llm: int = Field(default=4, validation_alias="MAX_CONCURRENT_LLM")

    # Unified Vision-Grade Agent
    enable_unified_vision_grade: bool = Field(
        default=False, validation_alias="ENABLE_UNIFIED_VISION_GRADE"
    )
    unified_agent_fallback_to_legacy: bool = Field(
        default=False, validation_alias="UNIFIED_AGENT_FALLBACK_TO_LEGACY"
    )
    unified_agent_max_concurrency: int = Field(
        default=2, validation_alias="UNIFIED_AGENT_MAX_CONCURRENCY"
    )
    unified_agent_timeout_seconds: int = Field(
        default=600, validation_alias="UNIFIED_AGENT_TIMEOUT_SECONDS"
    )
    unified_agent_max_tokens: int = Field(
        default=1600, validation_alias="UNIFIED_AGENT_MAX_TOKENS"
    )
    json_repair_max_attempts: int = Field(
        default=1, validation_alias="JSON_REPAIR_MAX_ATTEMPTS"
    )
    judgment_basis_min_length: int = Field(
        default=2, validation_alias="JUDGMENT_BASIS_MIN_LENGTH"
    )
    max_math_steps_per_question: int = Field(
        default=5, validation_alias="MAX_MATH_STEPS_PER_QUESTION"
    )

    # Derived facts extraction (question_attempts / question_steps)
    facts_queue_name: str = Field(
        default="facts:queue", validation_alias="FACTS_QUEUE_NAME"
    )
    facts_lock_ttl_seconds: int = Field(
        default=600, validation_alias="FACTS_LOCK_TTL_SECONDS"
    )

    # Autonomous Grade Agent
    enable_autonomous_grade_agent: bool = Field(
        default=True, validation_alias="ENABLE_AUTONOMOUS_GRADE_AGENT"
    )
    autonomous_agent_max_concurrency: int = Field(
        default=2, validation_alias="AUTONOMOUS_AGENT_MAX_CONCURRENCY"
    )
    autonomous_agent_timeout_seconds: int = Field(
        default=600, validation_alias="AUTONOMOUS_AGENT_TIMEOUT_SECONDS"
    )
    autonomous_agent_max_tokens: int = Field(
        default=4000, validation_alias="AUTONOMOUS_AGENT_MAX_TOKENS"
    )
    autonomous_agent_max_iterations: int = Field(
        # Keep the Planner/Executor/Reflector loop off by default for deterministic + faster /grade.
        # Use the feature flag `grade.autonomous_loop` (iter2/iter3) to enable canary runs.
        default=0,
        validation_alias="AUTONOMOUS_AGENT_MAX_ITERATIONS",
    )
    autonomous_agent_confidence_threshold: float = Field(
        default=0.90, validation_alias="AUTONOMOUS_AGENT_CONFIDENCE_THRESHOLD"
    )
    autonomous_agent_token_budget_total: int = Field(
        default=12000, validation_alias="AUTONOMOUS_AGENT_TOKEN_BUDGET_TOTAL"
    )
    autonomous_agent_min_aggregator_seconds: int = Field(
        default=20, validation_alias="AUTONOMOUS_AGENT_MIN_AGGREGATOR_SECONDS"
    )
    # Autonomous preprocessing pipeline control:
    # - full: qindex cache -> VLM locator -> OpenCV fallback (slow, highest coverage)
    # - qindex_only: only use cached qindex slices; if miss, skip preprocessing
    # - off: skip preprocessing entirely (fastest)
    autonomous_preprocess_mode: str = Field(
        default="qindex_only", validation_alias="AUTONOMOUS_PREPROCESS_MODE"
    )

    # OpenCV pipeline
    opencv_processing_timeout: int = Field(
        default=30, validation_alias="OPENCV_PROCESSING_TIMEOUT"
    )
    opencv_processing_max_bytes: int = Field(
        default=20 * 1024 * 1024, validation_alias="OPENCV_PROCESSING_MAX_BYTES"
    )

    # Vision/OCR preprocessing (OpenCV-enhanced)
    vision_preprocess_enabled: bool = Field(
        default=False, validation_alias="VISION_PREPROCESS_ENABLED"
    )
    vision_preprocess_timeout_seconds: int = Field(
        default=20, validation_alias="VISION_PREPROCESS_TIMEOUT_SECONDS"
    )
    vision_preprocess_max_bytes: int = Field(
        default=20 * 1024 * 1024, validation_alias="VISION_PREPROCESS_MAX_BYTES"
    )

    ocr_preprocess_enabled: bool = Field(
        default=False, validation_alias="OCR_PREPROCESS_ENABLED"
    )
    ocr_preprocess_prefix: str = Field(
        default="preprocessed/ocr/", validation_alias="OCR_PREPROCESS_PREFIX"
    )
    ocr_preprocess_timeout_seconds: int = Field(
        default=20, validation_alias="OCR_PREPROCESS_TIMEOUT_SECONDS"
    )
    ocr_preprocess_max_bytes: int = Field(
        default=20 * 1024 * 1024, validation_alias="OCR_PREPROCESS_MAX_BYTES"
    )

    # Context compaction (session memory)
    # Backward-compatible flag: historically used to toggle LLM-based summarization.
    # Prefer CONTEXT_COMPACTION_MODE for new setups.
    context_compaction_enabled: bool = Field(
        default=False, validation_alias="CONTEXT_COMPACTION_ENABLED"
    )
    # off | deterministic | llm
    context_compaction_mode: str = Field(
        default="deterministic", validation_alias="CONTEXT_COMPACTION_MODE"
    )
    context_compaction_max_messages: int = Field(
        default=24, validation_alias="CONTEXT_COMPACTION_MAX_MESSAGES"
    )
    context_compaction_overlap: int = Field(
        default=6, validation_alias="CONTEXT_COMPACTION_OVERLAP"
    )
    context_compaction_interval: int = Field(
        default=8, validation_alias="CONTEXT_COMPACTION_INTERVAL"
    )

    # Reviewer workflow (P2)
    review_api_enabled: bool = Field(
        default=False, validation_alias="REVIEW_API_ENABLED"
    )
    review_admin_token: str = Field(default="", validation_alias="REVIEW_ADMIN_TOKEN")
    review_item_ttl_seconds: int = Field(
        default=7 * 24 * 3600, validation_alias="REVIEW_ITEM_TTL_SECONDS"
    )
    review_ui_enabled: bool = Field(default=False, validation_alias="REVIEW_UI_ENABLED")

    # Feature flags / experiments (P2)
    feature_flags_json: str = Field(default="{}", validation_alias="FEATURE_FLAGS_JSON")
    feature_flags_salt: str = Field(
        default="ff_v1", validation_alias="FEATURE_FLAGS_SALT"
    )

    # Metrics (P2)
    metrics_enabled: bool = Field(default=False, validation_alias="METRICS_ENABLED")
    metrics_token: str = Field(default="", validation_alias="METRICS_TOKEN")

    # QIndex worker queue (Redis required)
    qindex_queue_name: str = Field(
        default="qindex:queue", validation_alias="QINDEX_QUEUE_NAME"
    )
    grade_queue_name: str = Field(
        default="grade:queue", validation_alias="GRADE_QUEUE_NAME"
    )

    # Review cards (Layer 3: auto re-check for visually risky items)
    grade_review_cards_enabled: bool = Field(
        default=True, validation_alias="GRADE_REVIEW_CARDS_ENABLED"
    )
    grade_review_cards_max_per_page: int = Field(
        default=2, validation_alias="GRADE_REVIEW_CARDS_MAX_PER_PAGE"
    )
    grade_review_cards_timeout_seconds: int = Field(
        # Per-item VFE budget (smaller than full grade vision budget).
        default=60, validation_alias="GRADE_REVIEW_CARDS_TIMEOUT_SECONDS"
    )

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    # CORS: default to explicit dev origins (production must set ALLOW_ORIGINS explicitly).
    allow_origins: list[str] = Field(
        default=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        validation_alias="ALLOW_ORIGINS",
    )
    log_to_file: bool = Field(default=True, validation_alias="LOG_TO_FILE")
    log_file_path: str = Field(
        default=os.path.join("logs", "backend.log"),
        validation_alias="LOG_FILE_PATH",
    )

    # Auth (Phase A): when enabled, endpoints require Authorization: Bearer <jwt>
    # and will derive user_id from token; otherwise dev fallback applies.
    auth_required: bool = Field(default=False, validation_alias="AUTH_REQUIRED")

    # Auth provider mode:
    # - dev: accept X-User-Id / DEV_USER_ID fallback (AUTH_REQUIRED must be 0)
    # - supabase: verify Supabase Auth JWT via /auth/v1/user
    # - local: verify locally-issued JWT (phone login)
    auth_mode: str = Field(default="dev", validation_alias="AUTH_MODE")

    # Local JWT (phone login)
    jwt_secret: str = Field(default="", validation_alias="JWT_SECRET")
    jwt_issuer: str = Field(default="noteacher", validation_alias="JWT_ISSUER")
    jwt_access_token_ttl_seconds: int = Field(
        default=7 * 24 * 3600, validation_alias="JWT_ACCESS_TOKEN_TTL_SECONDS"
    )

    # SMS auth
    sms_provider: str = Field(default="mock", validation_alias="SMS_PROVIDER")
    sms_code_ttl_seconds: int = Field(
        default=5 * 60, validation_alias="SMS_CODE_TTL_SECONDS"
    )
    sms_send_cooldown_seconds: int = Field(
        default=60, validation_alias="SMS_SEND_COOLDOWN_SECONDS"
    )
    sms_return_code_in_response: bool = Field(
        # Dev-only convenience; production should keep this false.
        default=True,
        validation_alias="SMS_RETURN_CODE_IN_RESPONSE",
    )

    # Admin API (WS-G): token-based gate for the first iteration (no admin auth UI yet).
    admin_token: str = Field(default="", validation_alias="ADMIN_TOKEN")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
