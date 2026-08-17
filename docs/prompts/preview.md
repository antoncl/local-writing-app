# Preview

`POST /api/ai/preview` renders a template against a target scene and returns the structured messages that would be sent to a model. It does **not** call any model — preview is the surface for staring at the assembled prompt before paying tokens for it.

## Request

```json
{
  "template_source": "{% role \"system\" %}…{% endrole %}",
  "target_scene_id": "scene_xxxxx",
  "session_id": "optional-session-key",
  "inputs": { "words": 300, "message": "What happens here?" },
  "text_before": "She walked into",
  "text_after": "the storm.",
  "commit": false
}
```

| Field | Required | Default | Meaning |
| --- | --- | --- | --- |
| `template_source` | yes | — | Jinja2 template body. See [template-language.md](template-language.md). |
| `target_scene_id` | yes | — | The scene the template will render against. Available in the template as `{{ scene }}`. |
| `session_id` | no | `null` | Cache-continuity key. Reusing the same key across calls lets the backend keep the stable prefix warm; the template author manages nothing here. |
| `inputs` | no | `{}` | Surfaced in the template as `{{ inputs.foo }}`. |
| `text_before` | no | `""` | Body markdown before the cursor in the editor. |
| `text_after` | no | `""` | Body markdown after the cursor. |
| `commit` | no | `false` | If `true`, this render's selected-node revisions become the session's cache baseline for the next call. |

## Response

```json
{
  "messages": [
    {
      "role": "system",
      "blocks": [ { "text": "You are an expert fiction writer." } ]
    },
    {
      "role": "user",
      "blocks": [ { "text": "Write 300 words…" } ]
    }
  ],
  "warnings": [],
  "char_count": 234,
  "estimated_tokens": 61,
  "cache_blocks": [
    { "label": "system",        "role": "system", "tier": "stable",   "tokens": 12, "text": "You are an expert fiction writer." },
    { "label": "volatile lore", "role": "system", "tier": "volatile", "tokens": 18, "text": "<lore name=\"Honor Harrington\">Captain of the Fearless.</lore>" },
    { "label": "user",          "role": "user",   "tier": null,       "tokens": 8,  "text": "Write 300 words…" }
  ],
  "lore_enabled": true,
  "used_node_ids": [],
  "used_node_hints": {},
  "session_id": "session-key-supplied",
  "rendered": true,
  "error": null
}
```

| Field | Meaning |
| --- | --- |
| `messages` | Role-tagged messages, each broken into content blocks. A block is **just text** — the author does not mark caching, so blocks carry no cache flag. |
| `warnings` | Author errors that didn't block rendering (unknown role names, nested roles). |
| `char_count` / `estimated_tokens` | Size of the rendered prompt. `estimated_tokens` sums `cache_blocks`, so it includes the backend-placed lore. |
| `cache_blocks` | The **send-path composition**, in volatility order — the cache strip. Each block has a `label` (`system`, `stable lore`, `volatile lore`, or a role), a `role`, a `tier` (`"stable"`, `"volatile"`, or `null` for an uncached conversation turn), a `tokens` count, and its `text`. This is where the tiered lore the backend selected appears (made visible again), badged by tier. See [The cache strip](#the-cache-strip). |
| `lore_enabled` | `true` when the template called `use_lore()` / `use()`. |
| `used_node_ids` / `used_node_hints` | Ids the template selected with `use()`, and any `use(node, "stable"\|"volatile")` cache-tier hints. |
| `session_id` | Echo of the supplied session id (or `null`). |
| `rendered` | `true` if rendering succeeded. |
| `error` | `null` on success; otherwise a render-error object (see below) — the response is still `200`. |

## Errors

Preview is exploratory — the editor auto-fires it before required inputs are filled — so a **render failure returns `200` with `error` populated**, not a thrown status. `error` is an object with a coarse `kind` the UI keys on:

| `error.kind` | Cause |
| --- | --- |
| `undefined` | An undefined variable / attribute. `undefined_name` (and `undefined_namespace` for an attribute miss like `project.language`) are set when derivable. |
| `syntax` | Template syntax error (e.g. an unknown tag); `line` is set. |
| `scene_not_found` | `target_scene_id` didn't resolve to a scene in the open project. |
| `other` | Anything else. |

A genuine HTTP error (no project open, a 5xx) is still thrown normally.

## The cache strip

`cache_blocks` is what makes preview cache-aware. It is the composition the send path will actually build, in the order the backend lays it down:

1. the **system prefix** (persona and other stable authored system content),
2. the **tiered lore** the backend selected from the template's `use()` / `use_lore()` calls — placed here on the send path even though the template emitted nothing for it, so preview shows it *again* where it really lands,
3. the **conversation turns** (the per-call user/assistant material).

Each block is badged with its `tier` — `stable` first, then `volatile`, then the uncached turns (`tier: null`). Stare at this strip to see exactly what will be cached and what will re-send on the next call; you tune it by choosing what to `use()`, not by placing breakpoints.

## Sessions

`session_id` is a cache-continuity key, not an author-facing control. Reusing it across calls lets the backend keep the stable prefix warm; `commit: true` promotes this render's selected-node revisions to the baseline the next call diffs against. Set `commit: false` to preview without disturbing that baseline. Sessions live in process memory only — restarting the backend clears them. The template author never touches any of this.

## Worked example: minimal continue-scene

```jinja
{% role "system" %}
You are an expert fiction writer.
{% if 'tense' in project.metadata %}Always write in {{ project.tense }} tense.{% endif %}
{% endrole %}

{% role "user" %}
{{ use_lore() }}
{% if story_so_far(scene) %}
The story so far:
{{ story_so_far(scene) }}
{% endif %}
{% endrole %}

{% role "assistant" %}
{{ text_before }}
{% endrole %}

{% role "user" %}
Write {{ inputs.words }} words that continue the story:

{{ inputs.message }}
{% endrole %}
```

POST this against a scene, supply `inputs: {"words": 300, "message": "Honor decides to break the engagement."}`, `text_before` from the editor, and a `session_id`. Inspect the response: `messages` holds the rendered turns (the `use_lore()` call emits nothing into them), while `cache_blocks` shows the backend-selected lore placed and tier-badged in the send-path composition.

## Worked example: bare role round-trip (sanity check)

```jinja
{% role "system" %}You write fiction.{% endrole %}
{% role "user" %}Scene: {{ scene.title }}{% endrole %}
```

Useful for verifying the wiring before any helpers are involved.

## Implementation reference

- Endpoint: `POST /api/ai/preview` in [`backend/app/main.py`](../../backend/app/main.py)
- Dispatch: [`backend/app/services/ai/preview.py`](../../backend/app/services/ai/preview.py)
- Tests: [`backend/tests/test_ai_preview.py`](../../backend/tests/test_ai_preview.py)
