from functools import lru_cache
from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    openai_api_key: str | None = Field(default=None, env="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", env="OPENAI_BASE_URL")
    model_reasoning: str = Field(default="gpt-4o", env="MODEL_REASONING")
    model_vision: str = Field(default="gpt-4o", env="MODEL_VISION")

    silicon_api_key: str | None = Field(default=None, env="SILICON_API_KEY")
    silicon_base_url: str = Field(default="https://api.siliconflow.cn/v1", env="SILICON_BASE_URL")
    silicon_vision_model: str = Field(default="Qwen/Qwen3-VL-32B-Thinking", env="SILICON_VISION_MODEL")

    ark_api_key: str | None = Field(default=None, env="ARK_API_KEY")
    ark_base_url: str = Field(default="https://ark.cn-beijing.volces.com/api/v3", env="ARK_BASE_URL")
    ark_vision_model: str = Field(default="doubao-seed-1-6-vision-250815", env="ARK_VISION_MODEL")

    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    allow_origins: list[str] = Field(default=["*"], env="ALLOW_ORIGINS")

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
