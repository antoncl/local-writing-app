# Generate

`POST /api/ai/generate` runs the full pipeline: render a template against a target scene, convert the rendered role-tagged messages into a chat-API payload, call the provider, return the generated text. This is the first endpoint that ties M2 (preview engine), M2.2 (helpers), M2.3 (sessions), and M3 (provider chat) together.

It's the surface that editor integrations (`continue_scene`, `revise_selection` — coming in M4.1+) will call.

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
    { "role": "system", "blocks": [ { "text": "…", "cache_break_after": true } ] },
    { "role": "user",   "blocks": [ { "text": "…", "cache_break_after": false } ] }
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
  "session_id": "optional-session-key"
}
```

`content` is the generated text. `rendered_messages` echoes the prompt that was sent (so the UI can show provenance). `char_count` is the input size in characters — a rough token estimate (~4 chars/token).

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

Identical to preview. With `session_id` set and `commit: true`, the call partitions stable/volatile lore for cache coherence on the next call. Without a session, the partition parameter on `relevant_lore` is ignored.

## What this endpoint is NOT yet

- **No streaming.** Full response returned at once.
- **No `n` parameter.** Single response per call. N-variant generation lands in a later slice.
- **No diff overlay.** The endpoint returns text; how it lands in the editor is the caller's problem.

## Implementation reference

- Endpoint: `POST /api/ai/generate` in [`backend/app/main.py`](../../backend/app/main.py)
- Dispatch helpers: [`backend/app/services/ai/preview.py`](../../backend/app/services/ai/preview.py) — `build_preview` and `build_chat_payload`
- Tests: [`backend/tests/test_ai_generate.py`](../../backend/tests/test_ai_generate.py)
