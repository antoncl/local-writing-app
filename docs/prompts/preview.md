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
| `session_id` | no | `null` | When set, `relevant_lore`'s `partition="stable"/"volatile"` becomes meaningful. See [helpers.md#sessions](helpers.md#sessions). |
| `inputs` | no | `{}` | Surfaced in the template as `{{ input.foo }}`. |
| `text_before` | no | `""` | Body markdown before the cursor in the editor. |
| `text_after` | no | `""` | Body markdown after the cursor. |
| `commit` | no | `false` | If `true`, the session's touched-entry revisions are promoted to baseline after a successful render. |

## Response

```json
{
  "messages": [
    {
      "role": "system",
      "blocks": [
        { "text": "You are an expert fiction writer.", "cache_break_after": true }
      ]
    },
    {
      "role": "user",
      "blocks": [
        { "text": "## Honor Harrington\nCaptain of the Fearless.", "cache_break_after": true },
        { "text": "Write 300 words…", "cache_break_after": false }
      ]
    }
  ],
  "warnings": [],
  "char_count": 234,
  "session_id": "session-key-supplied",
  "rendered": true
}
```

| Field | Meaning |
| --- | --- |
| `messages` | Role-tagged messages, each broken into content blocks. `cache_break_after: true` on a block means the provider serializer will emit an Anthropic `cache_control` marker just after it. |
| `warnings` | Author errors that didn't block rendering (text outside `{% role %}` blocks, `cache_break` outside a role, unknown role names, nested roles). |
| `char_count` | Total characters across all blocks. Rough token estimate: divide by ~4. |
| `session_id` | Echo of the supplied session id (or `null`). |
| `rendered` | `true` if rendering succeeded. Always `true` in the success path — errors return non-200 with a `detail`. |

## Errors

| Status | Cause |
| --- | --- |
| `404` | `target_scene_id` doesn't resolve to a scene in the open project. |
| `422` | Template error — undefined variable, syntax error, sandbox violation. `detail` contains the underlying class name and message. |
| `400` | No project open. |

## Session lifecycle

Without a session, the partition parameter on `relevant_lore` is ignored — all calls behave as `partition="all"`.

With a session, the typical usage is:

1. **First call** with `session_id` and `commit: true` — every entry returned by `relevant_lore` is recorded as the baseline.
2. **Subsequent calls** with the same `session_id` and `commit: true` — entries whose revision matches the baseline render in the `stable` partition; new or edited entries render in the `volatile` partition. The baseline is updated.
3. **Preview without commit** — set `commit: false` to inspect a partition without polluting the baseline (useful for debugging).
4. **Reset** — drop the session via `default_registry.drop(session_id)` (no HTTP surface yet; M3+).

Sessions live in process memory only. Restarting the backend clears them.

## Worked example: minimal continue-scene

```jinja
{% role "system" %}
You are an expert fiction writer.
Always write in {{ project.tense }} tense.
{% cache_break %}
{% endrole %}

{% role "user" %}
{{ relevant_lore(scene, "implicit", "stable") }}
{% cache_break %}
{{ relevant_lore(scene, "implicit", "volatile") }}

{% if scenes_before(scene) %}
The story so far:
{{ scenes_before(scene) }}
{% endif %}
{% endrole %}

{% role "assistant" %}
{{ text_before }}
{% endrole %}

{% role "user" %}
Write {{ input.words }} words that continue the story:

{{ input.message }}
{% endrole %}
```

POST this against a scene, supply `inputs: {"words": 300, "message": "Honor decides to break the engagement."}`, `text_before` from the editor, and a `session_id`. Inspect the response: the first user message should contain the lore block; the second user message should contain the instruction; the assistant message should contain the prior prose.

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
