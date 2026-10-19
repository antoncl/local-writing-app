# Preview

`POST /api/ai/preview` renders a template and returns what would be sent, **without
calling a model**. The prompt editor's preview pane, the invocation dialog and the
chat's cost estimate are built on it. [Generate](generate.md) runs the same render (`build_preview`) before it
calls the provider.

The request and response fields are in the generated schema (`/docs` on the running
backend; models `AIPreviewRequest` / `AIPreviewResponse` in
`backend/app/models/ai.py`). This page covers the behaviour the schema can't show.

## What the render sees

- `target_scene_id` is the scene the prompt runs on (`scene`). It may be empty — a
  chat-routed prompt has no scene, and `scene` is then `None`.
  `resolution_scene_id` (a `scene_ref` input's value) overrides it as the scene the
  story is read *as of*. `subject`, a bound chat's subject, is the fallback scene
  when neither is set.
- `inputs`, `selection`, `text_before` and `text_after` become the template variables
  of the same names. [reference.md § Variables](reference.md#variables) lists every
  variable.
- Text outside any `{% role %}` block becomes a `system` message — the same default
  the send path uses.

## Errors are data

Preview is exploratory — the editor fires it before required inputs are filled — so
a **render failure returns HTTP 200** with `rendered: false` and `error` set. `error`
carries `message`, the `line` / `col` where Jinja gave one, and a coarse `kind` the
UI keys its message on:

| `error.kind` | Cause |
| --- | --- |
| `undefined` | An undefined name. `undefined_name` is set when it can be derived, and `undefined_namespace` too when the miss was an attribute on a real object (`project` for `project.language`). |
| `syntax` | A template syntax error, such as an unknown tag. `line` is set. |
| `include` | An `{% include %}` name resolved to no snippet, or to more than one in the nearest layer. |
| `stopped` | The template called `stop(message)`. `message` is the author's text, verbatim. |
| `scene_not_found` | `target_scene_id` doesn't resolve. |
| `other` | Anything else, sandbox violations included. |

A request that can't be served at all (no project in scope, a server fault) is still
an HTTP error.

## The cache strip

`cache_blocks` is the **send-path composition**, in the order the backend lays it
down:

1. the **system prefix** — the rendered system content,
2. the **lore** the backend placed for the template's `use()` / `auto_lore()` calls
   and the *always include* entries, split into `stable` and `volatile` tiers. The
   template printed nothing for these, so this is the only place a preview shows
   them,
3. the **conversation turns** — the uncached `user` / `assistant` material.

Each block has its `tier` (`"stable"`, `"volatile"`, or `null` for an uncached turn),
a token count and its `text`. A lore block also lists its `entry_ids`. `cached` and
`ttl_seconds` are the resolved provider's own projection: whether it expects to
serve the block from cache, and for how long (ADR-0084). `estimated_tokens` and the
cost estimates are summed over this strip, so they include the placed lore.

`lore_fit` reports what the assistant's lore budget left out. `lore_enabled` is
`true` when the template called `auto_lore()`, and `lore_free` when it called
`no_lore()`. `used_node_ids`, `used_node_hints` and `used_snapshots` echo the
template's `use()` calls. `field_contract_stored` is the fields the template
registered with `field_contract.store()`.

The HTTP preview always renders the way a chat turn does. A template that calls
`auto_lore()` therefore shows automatic lore here, even though a one-shot
[generate](generate.md#what-lore-a-one-shot-run-carries) run doesn't send it.

## Effective inputs

With `resolve_effective_inputs: true` and the author's `own_inputs`, the response
also carries the prompt's **effective inputs**: its own, plus those of every snippet
it includes, transitively (ADR-0061). It also carries `input_conflicts` (same name,
different type) and `input_provenance` (which snippet each inherited input came
from). These are resolved before the render, so they come back even when the render
fails on an input that isn't filled in yet.

## Sessions

`session_id` is a cache-continuity key, not an author control. Reusing it across
calls lets the backend compare this render's selected nodes against the previous
one, and keep a settled node in the stable tier. `commit: true` makes this render's
revisions the new baseline. `commit: false` previews without moving it. Sessions
live in process memory, so restarting the backend clears them.

## Implementation reference

- Route: [`backend/app/routers/ai.py`](../../backend/app/routers/ai.py) — `ai_preview`
- Render: [`backend/app/services/ai/preview.py`](../../backend/app/services/ai/preview.py) — `build_preview`
- Sessions: [`backend/app/services/ai/sessions.py`](../../backend/app/services/ai/sessions.py)
- Tests: `backend/tests/test_ai_preview.py`, `test_ai_preview_cost.py`
