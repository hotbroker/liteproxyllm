# liteproxyllm

轻量版本地代理：把 Claude Code / Anthropic 风格请求转发到上游 OpenAI-compatible 服务，并支持模型映射。

## 功能

- `POST /v1/messages`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- 支持 Claude / Anthropic 风格流式 SSE
- 支持 `?beta=true`
- 支持 `effortLevel -> reasoning.effort`
- 通过 `MODEL_MAP` 做模型名映射
- `DEFAULT_UPSTREAM_MODEL` 可作为未命中映射时的兜底模型
- 透传请求体，仅修改必要的 `model` 和上游鉴权头

## 使用 uv

```bash
uv sync
```

当前环境用 Python 3.10+ 即可。

## 环境变量

```env
UPSTREAM_BASE_URL=https://your-openai-compatible-host/v1
UPSTREAM_API_KEY=sk-xxx
LISTEN_HOST=0.0.0.0
LISTEN_PORT=8080
CHAT_COMPLETIONS_PATH=/chat/completions
RESPONSES_PATH=/responses
DEFAULT_UPSTREAM_MODEL=gpt-4.1
MODEL_MAP={"claude-sonnet-4-5":"gpt-4.1","claude-opus-4-1":"o3"}
REQUEST_TIMEOUT_SECONDS=120
```

说明：

- `MODEL_MAP` 需要是 JSON 字符串。
- 如果 `UPSTREAM_BASE_URL` 已经带 `/v1`，则路径建议写成 `/responses` 和 `/chat/completions`，避免拼成重复的 `/v1/v1/...`。
- 当前上游会发送：
  - `Authorization: Bearer <UPSTREAM_API_KEY>`
  - `x-api-key: <UPSTREAM_API_KEY>`

## 启动

```bash
uv run python main.py
```

## curl 示例

### Claude / Anthropic messages

```bash
curl -X POST http://127.0.0.1:8080/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: test" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-sonnet-4-5",
    "max_tokens": 128,
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

### Claude / Anthropic messages with beta query

```bash
curl -X POST "http://127.0.0.1:8080/v1/messages?beta=true" \
  -H "Content-Type: application/json" \
  -H "x-api-key: test" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-sonnet-4-5",
    "max_tokens": 128,
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

### Claude / Anthropic stream

```bash
curl -N -X POST http://127.0.0.1:8080/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: test" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-sonnet-4-5",
    "max_tokens": 128,
    "stream": true,
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

### Claude / Anthropic effortLevel

```bash
curl -X POST http://127.0.0.1:8080/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: test" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-sonnet-4-5",
    "max_tokens": 128,
    "effortLevel": "high",
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

### responses

```bash
curl -X POST http://127.0.0.1:8080/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-5",
    "input": "hello"
  }'
```

### chat completions

```bash
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

## Claude Code 接入思路

如果你要让 Claude Code 直接走本地代理，优先使用 Anthropic 风格入口：

- Base URL: `http://127.0.0.1:8080`
- Endpoint: `/v1/messages`

当前代理已经验证支持：

- `POST /v1/messages`
- `POST /v1/messages?beta=true`
- Anthropic 风格 SSE 流式响应
- `effortLevel`

内部转换链路是：

- Claude Code / Anthropic 请求
- `-> /v1/messages`
- `->` 转换成上游 `/responses`
- `->` 再把返回结果转回 Anthropic message 格式

## 注意

当前版本是轻量 MVP：

- 不包含 UI
- 不包含多 provider 管理
- 不包含故障转移
- 目前重点保证 Claude Code 所需的 `/v1/messages` 兼容可用
- Anthropic 请求里的 `metadata` 当前不会向上游透传，因为部分 OpenAI-compatible 供应商会报 `Unsupported parameter: metadata`
