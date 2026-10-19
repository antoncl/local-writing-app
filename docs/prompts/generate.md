# Generate

`POST /api/ai/generate` runs a prompt **one-shot**. It renders the template (as
[preview](preview.md) does), turns the rendered messages into a chat payload, calls
the provider and returns the reply. `POST /api/ai/generate/stream` does the same and
streams the reply, using the line protocol in
[chat.md § Streaming line protocol](chat.md#streaming-line-protocol). The frontend
only uses the streaming route, because only a stream's disconnect can cancel the
provider call (#2464).

The request and response fields are in the generated schema (`/docs` on the running
backend; models `AIGenerateRequest` / `AIGenerateResponse` in
`backend/app/models/ai.py`). The request is preview's render fields plus the call
fields from [chat](chat.md) (`assistant_id`, `provider`, `model`, `max_tokens`).
This page covers the behaviour the schema can't show.

## From template to payload

`build_chat_payload` (`services/ai/preview.py`) converts the rendered messages:

1. **Every `system` message** is joined (blank-line separated) into one system prompt.
   Text outside any `{% role %}` block is already a `system` message — the send
   path renders with `system` as the default role.
2. **`user` and `assistant` messages** pass through in order. Whitespace-only
   messages are dropped. Consecutive same-role messages are merged, because
   Anthropic rejects two `user` turns in a row.
3. Other roles are dropped. The renderer has already warned about them.

So this template:

```jinja
You write fiction.
{% role "user" %}Plan the scene.{% endrole %}
{% role "assistant" %}Here's a plan…{% endrole %}
{% role "user" %}Now write it.{% endrole %}
```

sends the system prompt "You write fiction." and three alternating messages. If
nothing is left in `user` / `assistant` turns, there is nothing to send, and the
route answers **400**.

## What lore a one-shot run carries

A one-shot run sends the **declared** lore: the template's `use()` picks, plus the
entries marked *always include* (unless the prompt calls `no_lore()`). These are
placed as stable/volatile system blocks after the system prompt
(`one_shot_system_blocks`, `services/ai/chat.py`). It sends **no automatic lore**,
even if the template calls `auto_lore()` — the generate routes render with
`automatic_lore=False` (ADR-0092 Amendment 1 §5). Automatic lore is a chat-turn
feature.

## Response formats

`response_format` selects what the model is asked to return:

| Value | Reply | Route |
| --- | --- | --- |
| `text` (default) | Prose in `content`. | both |
| `line_edits` | A list of find/replace edits, parsed into `edits`. A reply that doesn't parse comes back as `ok: false`. | both |
| `notes` | Lore-check notes. | streaming only — the plain route answers 422 |

## Errors

| Response | Cause |
| --- | --- |
| `400` | The template rendered no `user` / `assistant` content. |
| `404` | `target_scene_id` doesn't resolve. |
| `422` | The template failed to render — an undefined name, a syntax error, an `{% include %}` that doesn't resolve, a sandbox violation, or a `stop()` call. `detail` is the message, or `{message, line, col}` when Jinja gave a location. |
| `200`, `ok: false` | The provider call failed or was refused — bad key, network error, AI policy. See `error`. |

The streaming route renders before it starts streaming, so render errors arrive as
the same HTTP errors. Only provider events go through the stream.

## Sessions

`session_id` and `commit` work as on [preview](preview.md#sessions): with
`commit: true`, this render's selected-node revisions become the baseline the next
call is compared against.

## Implementation reference

- Routes: [`backend/app/routers/ai.py`](../../backend/app/routers/ai.py) — `ai_generate`, `ai_generate_stream`
- Render + payload: [`backend/app/services/ai/preview.py`](../../backend/app/services/ai/preview.py) — `build_preview`, `build_chat_payload`
- Tests: `backend/tests/test_ai_generate.py`, `test_ai_generate_lore.py`
