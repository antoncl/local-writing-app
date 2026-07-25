# Chat

`POST /api/ai/chat` is the first real model call in the system. It runs a chat completion against the chosen provider and returns the assistant's reply. This is where tokens start being billed.

## Request

```json
{
  "provider": "anthropic",
  "model": "claude-haiku-4-5-20251001",
  "system_prompt": "You are a brainstorming partner.",
  "messages": [
    { "role": "user", "content": "Give me three ideas for an opening scene." },
    { "role": "assistant", "content": "1. The reactor scram…" },
    { "role": "user", "content": "More tension in option 1." }
  ],
  "max_tokens": 1024
}
```

| Field | Required | Default | Meaning |
| --- | --- | --- | --- |
| `provider` | no | machine settings `default_provider` | `anthropic`, `openai`, `openrouter`, or `ollama`. |
| `model` | no | machine settings `default_models[provider]` | Model name passed straight to the provider. |
| `system_prompt` | no | `""` | Anthropic: set on its dedicated param. OpenAI-compatible: prepended as a system message. Empty string means no system prompt. |
| `messages` | yes | — | Chat history. Each `{role, content}`, role is `user` or `assistant`. Must not be empty. Must alternate convention is enforced by the provider, not by us. |
| `max_tokens` | no | `1024` | Cap on the response. |

## Response

```json
{
  "role": "assistant",
  "content": "Sure — here are three sharper variants…",
  "provider": "anthropic",
  "model": "claude-haiku-4-5-20251001",
  "latency_ms": 1473,
  "policy": "cloud-allowed",
  "ok": true,
  "error": null
}
```

| Field | Meaning |
| --- | --- |
| `role` | Always `"assistant"`. |
| `content` | The reply text. Empty when `ok: false`. |
| `provider`, `model` | Echoed so the UI can show what was used. |
| `latency_ms` | Wall-clock from request issued to response received. Includes network. |
| `policy` | The project's current AI policy at the moment of the call. |
| `ok` | `true` on success. `false` for any error — policy rejection, missing key, provider error, network error. |
| `error` | Human-readable error string when `ok: false`. |

**The endpoint returns HTTP 200 even for errors** — the `ok` field is the success flag. This is so the frontend can render the error inline in the chat history without elaborate error handling. The only non-200 paths are 400 (no project open) and FastAPI validation errors.

## Policy enforcement

The endpoint reads `ai_policy` — resolved over the project's declared layer
chain, not from its own `project.yaml` alone (#312) — and applies it:

| Policy | Behavior |
| --- | --- |
| `off` | All calls fail with `policy: off`. Provider drivers are never invoked. |
| `local-only` | Cloud providers (`anthropic`, `openai`, `openrouter`) are rejected. `ollama` runs as normal. |
| `cloud-allowed` | All providers are permitted. |

Resolution is **nearest explicit statement wins**: a layer that states no
`settings.ai.policy` has no opinion and defers outward, so a universe set to
`cloud-allowed` covers every book that declares it, and a book stating `off` is
off regardless of what sits above it. A chain that states nothing anywhere is
`off`, and so is a value the reader does not recognise.

Policy is checked **before** any API key is sent anywhere. A misconfigured key won't leak even briefly when policy says no.

## Multi-turn pattern

The endpoint is stateless. The caller owns the conversation history:

1. **First turn**: send `messages: [{role: "user", content: "..."}]`.
2. **Receive reply**: append the response's `content` as `{role: "assistant", content: "..."}` to the local history.
3. **Next turn**: send the full accumulated history with one more user message at the end.

No conversation IDs, no server-side state. Restarting the backend doesn't lose history because there isn't any to lose.

## A worked curl example

```bash
curl -X POST http://127.0.0.1:8787/api/ai/chat \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "anthropic",
    "model": "claude-haiku-4-5-20251001",
    "system_prompt": "You are a brainstorming partner for fiction writers.",
    "messages": [
      {"role": "user", "content": "Give me three opening lines for a heist story."}
    ]
  }'
```

Provided the project is open with `ai_policy: cloud-allowed` and the Anthropic key is configured in machine settings, this returns a JSON body with `ok: true` and `content` containing the reply.

For Ollama, swap `provider` to `"ollama"` and `model` to a locally pulled model name (e.g., `"llama3.2"`). The Ollama host comes from machine settings.

## What this endpoint is NOT yet

- **No streaming.** The response is returned all at once. Streaming is a planned addition (M3+).
- **No template rendering.** The system prompt and messages are passed verbatim. Prose-generation tasks that need `relevant_lore`, `scenes_before`, etc., will use a different endpoint that wraps the template engine (M4).
- **No persistence.** Chats live only in the UI's memory. Saving conversations as `chat` node files is planned but not yet implemented.
- **No conversation tools / function calling.** Plain text in, plain text out.

## Implementation reference

- Endpoint: `POST /api/ai/chat` in [`backend/app/main.py`](../../backend/app/main.py)
- Provider dispatch: [`backend/app/services/ai/providers.py`](../../backend/app/services/ai/providers.py) — `chat()` plus `_anthropic_chat()` and `_openai_compatible_chat()`
- Tests: [`backend/tests/test_ai_chat.py`](../../backend/tests/test_ai_chat.py) (SDK calls mocked; no network in CI)
