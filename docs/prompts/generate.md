# Generate

`POST /api/ai/generate` runs the full pipeline: render a template against a target scene, convert the rendered role-tagged messages into a chat-API payload, call the provider, return the generated text. It ties the render engine, the helpers, the cache-continuity session, and the provider chat call together.

It's the surface that editor integrations (`continue_scene`, `revise_selection`) call.

## Request

```json
{
  "template_source": "{% role \"system\" %}…{% endrole %}{% role \"user\" %}…{% endrole %}",
  "target_scene_id": "scene_xxxxx",
  "session_id": "optional-session-key",
  "inputs": { "words": 300, "message": "What happens next?" },
  "text_before": "She walked into",
  "text_after": "the storm.",
  "commit": false,
  "provider": "anthropic",
  "model": "claude-haiku-4-5-20251001",
  "max_tokens": 4096
}
```

Same fields as `/api/ai/preview` (see [preview.md](preview.md)) plus the provider routing fields from `/api/ai/chat` (see [chat.md](chat.md)).

## Response

```json
{
  "content": "the storm without hesitation…",
  "rendered_messages": [
    { "role": "system", "blocks": [ { "text": "…" } ] },
    { "role": "user",   "blocks": [ { "text": "…" } ] }
  ],
  "rendered_warnings": [],
  "char_count": 1247,
  "provider": "anthropic",
  "model": "claude-haiku-4-5-20251001",
  "latency_ms": 2843,
  "policy": "cloud-allowed",
  "ok": true,
  "error": null,
  "stop_reason": "end_turn",
  "truncated": false,
  "session_id": "optional-session-key",
  "usage": { "input_tokens": 1180, "output_tokens": 340 },
  "cost_usd": 0.0042
}
```

`content` is the generated text. `rendered_messages` echoes the prompt that was sent (so the UI can show provenance) — each block is just text, since the author never marks caching. `char_count` is the input size in characters — a rough token estimate (~4 chars/token). `usage` and `cost_usd` report actual token spend for the call.

`ok`, `error`, `stop_reason`, `truncated`, `policy` behave identically to `/api/ai/chat`.

## How the template becomes a chat payload

The template renders to a list of role-tagged messages. The handler converts that into the chat-API shape:

1. **All `{% role "system" %}` blocks** are concatenated (newline-separated) into a single `system_prompt`.
2. **`{% role "user" %}` and `{% role "assistant" %}` blocks** pass through in order as the chat messages array.
3. Other roles are silently dropped (warnings from the renderer already flag them).

So this template:
```jinja
{% role "system" %}You write fiction.{% endrole %}
{% role "user" %}Plan the scene.{% endrole %}
{% role "assistant" %}Here's a plan…{% endrole %}
{% role "user" %}Now write it.{% endrole %}
```
becomes:
- `system_prompt` = "You write fiction."
- `messages` = `[{role:"user","Plan the scene."}, {role:"assistant","Here's a plan…"}, {role:"user","Now write it."}]`

## Errors

| Status | Cause |
| --- | --- |
| `400` | Template rendered no user/assistant messages — nothing to send. |
| `404` | `target_scene_id` doesn't resolve. |
| `422` | Template error — undefined variable, syntax error, sandbox violation. |
| `200, ok:false` | Provider call failed — bad key, network error, policy refused. See `error`. |

## Session and cache behavior

Identical to preview. `session_id` is the cache-continuity key; with `commit: true` this render's selected-node revisions become the baseline the next call diffs against, so the backend can keep the stable prefix warm. The template author manages none of it — caching is the backend's volatility ordering (see [preview.md#the-cache-strip](preview.md#the-cache-strip)).

## What this endpoint is NOT yet

- **No streaming.** Full response returned at once.
- **No `n` parameter.** Single response per call. N-variant generation lands in a later slice.
- **No diff overlay.** The endpoint returns text; how it lands in the editor is the caller's problem.

## Implementation reference

- Endpoint: `POST /api/ai/generate` in [`backend/app/main.py`](../../backend/app/main.py)
- Dispatch helpers: [`backend/app/services/ai/preview.py`](../../backend/app/services/ai/preview.py) — `build_preview` and `build_chat_payload`
- Tests: [`backend/tests/test_ai_generate.py`](../../backend/tests/test_ai_generate.py)
