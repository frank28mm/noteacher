from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    allow_origins: list[str] = Field(default=["*"], validation_alias="ALLOW_ORIGINS")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
