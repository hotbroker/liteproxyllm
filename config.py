import os
import json
from datetime import datetime, timedelta

from loguru import logger
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


if __name__ == "__main__":
    logger.add("log{}.log".format(os.path.basename(os.path.abspath(__file__))), rotation="1 MB", retention="3 days", level="INFO")

logger.info(f'start with file {os.path.basename(os.path.abspath(__file__))} pid {os.getpid()}@ filetime {datetime.fromtimestamp(os.path.getctime(os.path.abspath(__file__))).strftime("%Y-%m-%d, %H:%M:%S")}')


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    listen_host: str = "0.0.0.0"
    listen_port: int = 8080
    upstream_base_url: str = Field(..., description="OpenAI-compatible upstream base URL")
    upstream_api_key: str = Field(..., description="Upstream API key")
    chat_completions_path: str = "/v1/chat/completions"
    responses_path: str = "/v1/responses"
    default_upstream_model: str | None = None
    request_timeout_seconds: float = 120.0
    model_map: dict[str, str] = Field(default_factory=dict)

    @field_validator("model_map", mode="before")
    @classmethod
    def parse_model_map(cls, value: object) -> object:
        if isinstance(value, str) and value.strip():
            return json.loads(value)
        return value


settings = Settings()
