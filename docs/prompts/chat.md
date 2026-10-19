# Chat

`POST /api/ai/chat` runs one chat turn against the resolved provider and returns
the assistant's reply. `POST /api/ai/chat/stream` runs the same turn and streams it.
Both take the same request body. The chat pane uses the streaming route.

The request and response fields are in the generated schema (`/docs` on the running
backend; models `AIChatRequest` / `AIChatResponse` in `backend/app/models/ai.py`).
This page covers the behaviour the schema can't show.

## What a turn does

1. **Resolve the call.** Provider, model, temperature and `max_tokens` resolve
   request override → `assistant_id` (or the default assistant) → machine-settings
   fallback; see [README § Mental model](README.md#mental-model).
2. **Read the AI policy** (below). A refused call never reaches a provider.
3. **Prepare the bound chat's context**, when `chat_id` is set: the implicit-context
   expander scans the latest user message, records new detections in that chat's
   lore journal (`journal_added` on the response), and the journal is packed into a
   cache-stable system block between `system_prompt` and the history. The lore that
   rides is held to the assistant's lore budget, and what it left out is reported
   as `lore_fit`.
4. **Window the history.** Older rounds that exceed the history budget are dropped
   from what is sent (not from the caller's copy) and reported as `history_fit`.
5. **Call the provider**, then report `stop_reason`, `truncated` (the reply hit
   `max_tokens`), `input_truncated` (Ollama read less prompt than was sent),
   `usage` and `cost_usd`. A successful turn on a bound chat also records an
   invocation row, and `cost_usd_total` is the chat's running total.

`system_prompt` and `messages` are sent as the caller supplies them. Nothing is
rendered as a template on this route — template rendering is
[preview](preview.md) and [generate](generate.md).

## The caller owns the transcript

The endpoint doesn't store messages. The caller sends the whole history every
turn. A chat is persisted separately as a `chat` node under `<project>/chats/`,
through the chat-session endpoints (`/api/chats/{chat_id}`, `PUT` to save). The
`chat_id` on a turn ties it to that node's journal and cost record.

## Errors arrive as data

The non-streaming route returns **HTTP 200 for provider-side failures**: `ok: false`
with `error` set (policy refused, missing key, provider or network error), so the UI
can show the failure inline in the conversation. A request that fails validation, or
that arrives with no project in scope, is rejected before the handler runs.

## AI policy

The turn reads `ai_policy`, resolved over the project's declared layer chain
(#312):

| Policy | Behavior |
| --- | --- |
| `off` | Every call fails with `ok: false`. No provider is invoked. |
| `local-only` | Cloud providers (`anthropic`, `openai`, `openrouter`) are refused; `ollama` runs. |
| `cloud-allowed` | All providers are permitted. |

The **nearest explicit statement wins.** A layer that doesn't state
`settings.ai.policy` defers outward, so a universe set to `cloud-allowed` covers
every book that declares it, and a book stating `off` is off whatever is above it.
A chain that states nothing anywhere resolves to `off`, and so does a value the
reader doesn't recognise. The policy is checked **before** any API key leaves the
machine.

## Streaming line protocol

Both `/stream` routes answer with newline-delimited JSON, one object per line
(`services/ai/streaming.py`):

```text
{"type":"delta","text":"..."}        zero or more — reply text
{"type":"thinking","text":"..."}     zero or more — reasoning, where the model streams it
{"type":"done", ...}                 one, on success — provider, model, latency_ms,
                                     stop_reason, truncated, policy, usage, cost_usd, …
{"type":"error","error":"...", ...}  one, on failure — instead of done
```

On the chat stream, `done` also carries what the non-streaming response reports
about the turn (`journal_added`, `lore_fit`, `history_fit`, cost). Closing the
connection cancels the provider call.

## Implementation reference

- Routes: [`backend/app/routers/ai.py`](../../backend/app/routers/ai.py) — `ai_chat`, `ai_chat_stream`
- Turn orchestration: [`backend/app/services/ai/chat.py`](../../backend/app/services/ai/chat.py) — `run_chat_turn`, `expand_and_prepare_chat_blocks`
- Provider dispatch: [`backend/app/services/ai/providers.py`](../../backend/app/services/ai/providers.py) and `services/ai/profiles/`
- Tests: `backend/tests/test_ai_chat*.py`, `test_ai_stream_cancel.py` (SDK calls mocked; no network in CI)
