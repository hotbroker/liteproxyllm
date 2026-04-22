import os
from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger


if __name__ == "__main__":
    logger.add("log{}.log".format(os.path.basename(os.path.abspath(__file__))), rotation="1 MB", retention="3 days", level="INFO")

logger.info(f'start with file {os.path.basename(os.path.abspath(__file__))} pid {os.getpid()}@ filetime {datetime.fromtimestamp(os.path.getctime(os.path.abspath(__file__))).strftime("%Y-%m-%d, %H:%M:%S")}')

from config import settings
from proxy import proxy
from schemas import AnthropicMessageRequest


async def _read_json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid json body") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a json object")
    return body


def _stream_requested(payload: dict[str, Any]) -> bool:
    return bool(payload.get("stream"))


def create_app() -> FastAPI:
    app = FastAPI(title="liteproxyllm", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "upstream": settings.upstream_base_url}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        payload = await _read_json(request)
        if _stream_requested(payload):
            return StreamingResponse(proxy.stream_bytes(settings.chat_completions_path, payload), media_type="text/event-stream")
        data, status_code, headers = await proxy.forward_json(settings.chat_completions_path, payload)
        return JSONResponse(content=data, status_code=status_code, headers=headers)

    @app.post("/v1/responses")
    async def responses(request: Request):
        payload = await _read_json(request)
        if _stream_requested(payload):
            return StreamingResponse(proxy.stream_bytes(settings.responses_path, payload), media_type="text/event-stream")
        data, status_code, headers = await proxy.forward_json(settings.responses_path, payload)
        return JSONResponse(content=data, status_code=status_code, headers=headers)

    @app.post("/v1/messages")
    async def messages(request: Request):
        payload = AnthropicMessageRequest.model_validate(await _read_json(request)).model_dump(exclude_none=True)
        if _stream_requested(payload):
            return StreamingResponse(proxy.stream_anthropic_messages(payload), media_type="text/event-stream")
        data, status_code, headers = await proxy.forward_anthropic_messages(payload)
        return JSONResponse(content=data, status_code=status_code, headers=headers)

    @app.post("/v1/messages/")
    async def messages_slash(request: Request):
        return await messages(request)

    return app
