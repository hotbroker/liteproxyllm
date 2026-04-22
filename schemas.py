import os
from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field


if __name__ == "__main__":
    logger.add("log{}.log".format(os.path.basename(os.path.abspath(__file__))), rotation="1 MB", retention="3 days", level="INFO")

logger.info(f'start with file {os.path.basename(os.path.abspath(__file__))} pid {os.getpid()}@ filetime {datetime.fromtimestamp(os.path.getctime(os.path.abspath(__file__))).strftime("%Y-%m-%d, %H:%M:%S")}')


class ProxyRequest(BaseModel):
    model: str | None = Field(default=None)
    stream: bool | None = Field(default=None)
    payload: dict[str, Any]


class ProxyTarget(BaseModel):
    path: str
    model: str | None


class AnthropicMessageRequest(BaseModel):
    model: str
    max_tokens: int | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    system: str | list[dict[str, Any]] | None = None
    stream: bool = False
    temperature: float | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: dict[str, Any] | str | None = None
    metadata: dict[str, Any] | None = None
    stop_sequences: list[str] | None = None
    effortLevel: str | None = None
    thinking: dict[str, Any] | None = None
