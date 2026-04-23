import json
import os
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin

import httpx
from loguru import logger


if __name__ == "__main__":
    logger.add("log{}.log".format(os.path.basename(os.path.abspath(__file__))), rotation="1 MB", retention="3 days", level="INFO")

logger.info(f'start with file {os.path.basename(os.path.abspath(__file__))} pid {os.getpid()}@ filetime {datetime.fromtimestamp(os.path.getctime(os.path.abspath(__file__))).strftime("%Y-%m-%d, %H:%M:%S")}')

from config import settings
from schemas import ProxyTarget


class UpstreamProxy:
    def __init__(self) -> None:
        self._timeout = httpx.Timeout(settings.request_timeout_seconds)

    def resolve_target(self, path: str, payload: dict[str, Any]) -> ProxyTarget:
        incoming_model = payload.get("model")
        mapped_model = settings.model_map.get(incoming_model)
        if mapped_model is not None:
            final_model = mapped_model
        elif settings.default_upstream_model is not None:
            final_model = settings.default_upstream_model
        else:
            final_model = incoming_model
        return ProxyTarget(path=path, model=final_model)

    def normalize_payload(self, payload: dict[str, Any], target: ProxyTarget) -> dict[str, Any]:
        forwarded = dict(payload)
        if target.model is not None:
            forwarded["model"] = target.model
        return forwarded

    def build_url(self, path: str) -> str:
        return urljoin(f"{settings.upstream_base_url.rstrip('/')}/", path.lstrip('/'))

    def build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.upstream_api_key}",
            "Content-Type": "application/json",
        }

    def build_timeout_error(self, *, url: str, path: str, model: str | None, stream: bool) -> dict[str, Any]:
        return {
            "error": {
                "message": f"upstream timeout after {settings.request_timeout_seconds}s",
                "type": "upstream_timeout",
                "upstream_url": url,
                "upstream_path": path,
                "upstream_model": model,
                "stream": stream,
            }
        }

    def anthropic_block_to_text(self, block: Any) -> str:
        if isinstance(block, str):
            return block
        if isinstance(block, dict):
            if block.get("type") == "text":
                return str(block.get("text", ""))
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):
                    return "\n".join(self.anthropic_block_to_text(item) for item in content)
                return str(content)
        return ""

    def anthropic_content_to_responses_content(self, content: Any) -> list[dict[str, str]]:
        if isinstance(content, str):
            return [{"type": "input_text", "text": content}]
        if isinstance(content, list):
            parts: list[dict[str, str]] = []
            for block in content:
                text = self.anthropic_block_to_text(block)
                if text:
                    parts.append({"type": "input_text", "text": text})
            return parts or [{"type": "input_text", "text": ""}]
        return [{"type": "input_text", "text": str(content)}]

    def anthropic_to_responses_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        target = self.resolve_target(settings.responses_path, payload)
        translated: dict[str, Any] = {
            "model": target.model,
            "stream": bool(payload.get("stream")),
            "input": [],
        }
        system = payload.get("system")
        if system:
            translated["input"].append(
                {
                    "role": "system",
                    "content": self.anthropic_content_to_responses_content(system),
                }
            )
        for message in payload.get("messages", []):
            translated["input"].append(
                {
                    "role": message.get("role", "user"),
                    "content": self.anthropic_content_to_responses_content(message.get("content", "")),
                }
            )
        if payload.get("max_tokens") is not None:
            translated["max_output_tokens"] = payload["max_tokens"]
        if payload.get("temperature") is not None:
            translated["temperature"] = payload["temperature"]
        if payload.get("tools") is not None:
            translated["tools"] = payload["tools"]
        if payload.get("tool_choice") is not None:
            translated["tool_choice"] = payload["tool_choice"]
        if payload.get("stop_sequences") is not None:
            translated["stop"] = payload["stop_sequences"]
        effort_level = payload.get("effortLevel") or payload.get("thinking", {}).get("effort")
        #print(f"effort_level {effort_level}, effortLevel={payload.get('effortLevel')}, thinking={payload.get('thinking')} payload {payload}")
        if 1 or effort_level:
            translated["reasoning"] = {"effort": "xhigh"}
        return translated

    def extract_text_from_responses(self, body: dict[str, Any]) -> str:
        if isinstance(body.get("output_text"), str) and body["output_text"]:
            return body["output_text"]
        texts: list[str] = []
        for item in body.get("output", []):
            for content in item.get("content", []):
                if isinstance(content, dict):
                    if content.get("type") in {"output_text", "text"}:
                        texts.append(str(content.get("text", "")))
        return "".join(texts)

    def responses_to_anthropic(self, original_payload: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        text = self.extract_text_from_responses(body)
        usage = body.get("usage", {}) if isinstance(body.get("usage"), dict) else {}
        return {
            "id": body.get("id", "msg_liteproxyllm"),
            "type": "message",
            "role": "assistant",
            "model": original_payload.get("model") or body.get("model") or settings.default_upstream_model,
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
        }

    async def forward_json(self, path: str, payload: dict[str, Any]) -> tuple[Any, int, dict[str, str]]:
        target = self.resolve_target(path, payload)
        forwarded_payload = self.normalize_payload(payload, target)
        url = self.build_url(target.path)
        headers = self.build_headers()
        stream = bool(forwarded_payload.get("stream"))
        logger.info("forwarding request path={} upstream_url={} upstream_model={} stream={}", target.path, url, target.model, stream)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=forwarded_payload, headers=headers)
        except httpx.ReadTimeout:
            logger.exception("upstream read timeout path={} upstream_url={} upstream_model={} stream={}", target.path, url, target.model, stream)
            return self.build_timeout_error(url=url, path=target.path, model=target.model, stream=stream), 504, {"content-type": "application/json"}
        except httpx.HTTPError as exc:
            logger.exception("upstream request failed path={} upstream_url={} upstream_model={} stream={}", target.path, url, target.model, stream)
            return {
                "error": {
                    "message": str(exc),
                    "type": "upstream_connection_error",
                    "upstream_url": url,
                    "upstream_path": target.path,
                    "upstream_model": target.model,
                    "stream": stream,
                }
            }, 502, {"content-type": "application/json"}

        content_type = response.headers.get("content-type", "application/json")
        try:
            body: Any = response.json()
        except ValueError:
            body = {"raw_text": response.text}
        return body, response.status_code, {"content-type": content_type}

    async def forward_anthropic_messages(self, payload: dict[str, Any]) -> tuple[Any, int, dict[str, str]]:
        translated = self.anthropic_to_responses_payload(payload)
        body, status_code, headers = await self.forward_json(settings.responses_path, translated)
        if status_code >= 400:
            return body, status_code, headers
        if not isinstance(body, dict):
            return {"error": {"message": "invalid upstream response", "type": "proxy_error"}}, 502, {"content-type": "application/json"}
        return self.responses_to_anthropic(payload, body), status_code, {"content-type": "application/json"}

    async def stream_bytes(self, path: str, payload: dict[str, Any]):
        target = self.resolve_target(path, payload)
        forwarded_payload = self.normalize_payload(payload, target)
        url = self.build_url(target.path)
        headers = self.build_headers()
        logger.info("streaming request path={} upstream_url={} upstream_model={}", target.path, url, target.model)
        client = httpx.AsyncClient(timeout=self._timeout)
        try:
            async with client.stream("POST", url, json=forwarded_payload, headers=headers) as response:
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.ReadTimeout:
            logger.exception("upstream streaming read timeout path={} upstream_url={} upstream_model={}", target.path, url, target.model)
            yield json.dumps(self.build_timeout_error(url=url, path=target.path, model=target.model, stream=True)).encode("utf-8")
        except httpx.HTTPError as exc:
            logger.exception("upstream streaming request failed path={} upstream_url={} upstream_model={}", target.path, url, target.model)
            yield json.dumps({
                "error": {
                    "message": str(exc),
                    "type": "upstream_connection_error",
                    "upstream_url": url,
                    "upstream_path": target.path,
                    "upstream_model": target.model,
                    "stream": True,
                }
            }).encode("utf-8")
        finally:
            await client.aclose()

    async def stream_anthropic_messages(self, payload: dict[str, Any]):
        translated = self.anthropic_to_responses_payload(payload)
        url = self.build_url(settings.responses_path)
        headers = self.build_headers()
        logger.info("streaming anthropic messages upstream_url={} upstream_model={} effortLevel={}", url, translated.get("model"), payload.get("effortLevel"))
        client = httpx.AsyncClient(timeout=self._timeout)
        try:
            yield b"event: message_start\ndata: {\"type\":\"message_start\",\"message\":{\"id\":\"msg_liteproxyllm\",\"type\":\"message\",\"role\":\"assistant\",\"model\":\"liteproxyllm\",\"content\":[],\"stop_reason\":null,\"stop_sequence\":null,\"usage\":{\"input_tokens\":0,\"output_tokens\":0}}}\n\n"
            yield b"event: content_block_start\ndata: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"text\",\"text\":\"\"}}\n\n"
            async with client.stream("POST", url, json=translated, headers=headers) as response:
                if response.status_code >= 400:
                    error_text = await response.aread()
                    yield b"event: error\ndata: " + json.dumps({"type": "error", "error": error_text.decode("utf-8", errors="ignore")}).encode("utf-8") + b"\n\n"
                    return
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    text_delta = ""
                    event_type = event.get("type", "")
                    if event_type in {"response.output_text.delta", "output_text.delta"}:
                        text_delta = event.get("delta", "")
                    elif event_type in {"response.output_text.done", "output_text.done"}:
                        text_delta = ""
                    if text_delta:
                        yield b"event: content_block_delta\ndata: " + json.dumps({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text_delta}}).encode("utf-8") + b"\n\n"
            yield b"event: content_block_stop\ndata: {\"type\":\"content_block_stop\",\"index\":0}\n\n"
            yield b"event: message_delta\ndata: {\"type\":\"message_delta\",\"delta\":{\"stop_reason\":\"end_turn\",\"stop_sequence\":null},\"usage\":{\"output_tokens\":0}}\n\n"
            yield b"event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n"
        except httpx.ReadTimeout:
            logger.exception("upstream anthropic streaming read timeout upstream_url={} upstream_model={}", url, translated.get("model"))
            yield b"event: error\ndata: " + json.dumps({"type": "error", "error": self.build_timeout_error(url=url, path=settings.responses_path, model=translated.get("model"), stream=True)}).encode("utf-8") + b"\n\n"
        except httpx.HTTPError as exc:
            logger.exception("upstream anthropic streaming request failed upstream_url={} upstream_model={}", url, translated.get("model"))
            yield b"event: error\ndata: " + json.dumps({
                "type": "error",
                "error": {
                    "message": str(exc),
                    "type": "upstream_connection_error",
                    "upstream_url": url,
                    "upstream_path": settings.responses_path,
                    "upstream_model": translated.get("model"),
                    "stream": True,
                },
            }).encode("utf-8") + b"\n\n"
        finally:
            await client.aclose()


proxy = UpstreamProxy()
