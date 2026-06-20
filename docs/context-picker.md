# Context Picker — Design Note

## Problem

The current chat composer has a single global "+ Context" button that lets
the user attach scenes / lore / snippets / presets (full outline, full
text) to the active chat session. The picker is unconstrained — the
prompt author has no way to say "this prompt expects only character
refs" or "this prompt should only see scene summaries." Two costs:

- **Author intent is invisible.** A prompt designed to operate on
  characters has to validate or coerce in the template (or just hope).
- **Runtime UX is generic.** Every prompt sees the same multi-step
  Presets → Browse → Scenes/Lore/Snippets menu, regardless of what it
  actually needs.

Inspiration: Novel Crafter's per-prompt "Context selection" panel lets
the author check the allowed kinds + sub-types + treatment, and the
runtime picker reflects that constraint.

## Scope (v1)

In scope:

- A new prompt input type `context_pick`, sitting alongside `text`,
  `long_text`, `select`, `entity_ref`, `entity_ref_list`, etc. in
  `PromptInputDefinition`.
- Per-input author config: which kinds are pickable, which sub-types
  per kind, which presets are pickable, multiplicity, button label.
- Runtime surfaces: a composer button (`+ <label>`) per `context_pick`
  input on the active prompt, AND an entry in the initial inputs
  dialog (so the user can pre-pick before sending the first message).
- Template binding via the existing inputs namespace: `{{ input.<name> }}`
  exposes a list of `EntryRef`-like objects.
- The legacy chat-level freeform `+ Context` button **goes away**.
  Existing chat sessions with `chatContextItems` still render their
  items (read-only), but the only way to add new context is via a
  prompt-declared `context_pick` input.
- Extraction of the picker UI into its own Svelte component, freeing
  ~200 lines from `App.svelte`.

Out of scope (v2 or later):

- **Treatment toggles per type.** "Full text vs Summary" is a
  render-time concern; the template author chooses via existing
  helpers (`scene.body_markdown` vs `scene.summary`). No picker-side
  default in v1.
- **Per-item treatment at pick time.** Same reasoning.
- **Cross-prompt context inheritance** (e.g. a snippet that brings its
  own context picker when included via Jinja).
- **Free-form text fallback** (NC's "Custom content" radio).

## Data model

`PromptInputDefinition` (in [models.py](../backend/app/models.py:140))
gets a new `type` literal value and uses the existing `target` slot
to carry the picker config:

```python
class PromptInputDefinition(BaseModel):
    name: str
    type: Literal[
        "text", "long_text", "number", "boolean", "select",
        "entity_ref", "entity_ref_list",
        "context_pick",                    # NEW
    ]
    label: str | None = None
    default: Any = None
    options: list[str] = []
    required: bool = False
    target: dict[str, Any] | None = None   # see ContextPickConfig below


# Shape carried in `target` when type == "context_pick".
class ContextPickConfig(BaseModel):
    kinds: list[Literal["scene", "lore", "snippet", "assistant"]] = []
    entry_types: dict[str, list[str]] = {}   # kind -> list of sub-type ids
    presets: list[Literal["full_outline", "full_text"]] = []
    multiple: bool = True
```

Why `target` instead of a new field: it's already the rich-config slot
on `PromptInputDefinition`, currently used by `entity_ref` /
`entity_ref_list` to carry `{kind, entry_type}`. Reusing it keeps the
schema flat and avoids a Pydantic union dance.

**Validation rules**:

- At least one of `kinds` or `presets` must be non-empty (a picker
  with nothing pickable is a bug, not a configuration).
- `entry_types[kind]` is only meaningful when `kind` is in `kinds`.
- Sub-type ids in `entry_types[kind]` must exist in the project's
  schema (validated at save time, soft-warned at runtime since project
  schema may have changed since the prompt was authored).

## Runtime behaviour

Two surfaces in the chat panel:

**1. Initial inputs dialog** (when the user picks a prompt).
The existing inputs dialog ([App.svelte:1385+](../frontend/src/App.svelte:1385))
already iterates declared inputs and renders a `PromptInputField` per
row. For `context_pick`, the field renders as a button (`+ <label>`)
plus chips for any already-picked items. Clicking the button opens
the constrained picker menu.

**2. Composer buttons** (any time after the chat starts).
For each `context_pick` input on the active prompt, render one button
in the composer strip with the input's label. Clicking it opens the
same picker. Picked items render as chips above the message textarea
(reusing the existing `.chat-context-chips` styling).

Both surfaces read from and write to the same storage: the input's
value, which is a list of `EntryRef`s. Editing in one surface is
visible in the other.

**Storage**: chat sessions persist input values exactly the way the
inputs dialog already does. No new storage layer.

## Picker menu

When a `context_pick` button is clicked, the menu shows:

- **Presets** section (if `presets` is non-empty): one button per
  allowed preset, labelled by the preset's display name.
- **Browse** section: one expandable group per allowed `kind`, listing
  the project's entries of that kind, filtered by `entry_types[kind]`
  when set. Search box if the group has > 20 items.

If `multiple: false`, the menu closes after one pick and any prior
pick is replaced.

Picked items can be removed from the chip strip via an "×" button
(matching current behaviour).

## Template binding

Picked items expose as `{{ input.<name> }}` — a list of refs the
template iterates and renders as it sees fit:

```jinja2
{% for item in input.reference_scenes %}
  Scene {{ item.title }}:
  {{ item.summary }}
{% endfor %}

{% for char in input.characters_involved %}
  - {{ char.title }} ({{ char.aliases | join(", ") }})
{% endfor %}
```

Presets remain functions on the template helpers — picking the
"Full Outline" preset is equivalent to the template calling
`{{ full_outline() }}` itself. To avoid double-rendering, the picker
exposes presets as `{type: "preset", id: "full_outline"}` refs; the
template can either iterate via `input.<name>` and dispatch, or call
the helpers directly. **Recommendation**: presets are rendered by the
input loop (`{% for item in input.x %}{% if item.type == "preset" %}{{ render_preset(item.id) }}{% else %}…{% endif %}`),
not by the template author calling helpers separately. Keeps the user's
pick reflected in the render.

**Memory note**: refs carry `{kind, id, type, title}` — no body
content. Materialization happens server-side at render time via
existing helpers. Picking "Full Novel Text" doesn't pull every scene's
body into the chat session; it stores one preset ref, and
`full_text()` iterates scene files when the template renders.

## Author UI (config row)

The Inputs editor in DocumentEditorPane currently renders one row per
declared input with type dropdown, label, default, etc. For
`context_pick` the row expands to show:

- **Kinds**: checkbox list (Scene / Lore / Snippet / Assistant).
- **Sub-types**: nested under each checked kind, a sub-checkbox per
  sub-type from the project schema. Default = all sub-types allowed.
- **Presets**: checkbox list (Full Outline / Full Novel Text).
- **Allow multiple picks**: checkbox (default true).

Display label and required flag come from the standard input row
fields (already there).

## Component extraction

Two new Svelte components, extracted from `App.svelte`:

- `frontend/src/ContextPicker.svelte` — the runtime button + menu.
  Takes a `ContextPickConfig` + current value, emits change. Replaces
  the ~200-line inline `.chat-context-menu` block at
  [App.svelte:4701-4756](../frontend/src/App.svelte:4701).
- `frontend/src/ContextPickConfigEditor.svelte` — the author-time
  config row, used inside the Inputs editor when type ===
  "context_pick". New surface.

`App.svelte` keeps the composer-level wiring (rendering one
`ContextPicker` per `context_pick` input on the active prompt) but
sheds the menu internals.

## Migration

**Existing chat sessions** with legacy `chatContextItems` (the flat
session-level context list): keep the items visible in the chat
context chip strip; render them in the template via a synthetic
fallback (`{{ chat.legacy_context }}` or similar — TBD whether worth
the complexity). If we drop legacy rendering entirely, surface a
one-time warning per session: "Legacy context items are no longer
sent — re-attach via a prompt's context picker."

**Existing prompts**: no schema change — `PromptInputDefinition.target`
already accepts a dict. New prompts opt into `context_pick`; old
prompts are unaffected.

**Existing entity_ref / entity_ref_list inputs**: stay as-is.
`context_pick` is additive. The two have different intent:

- `entity_ref` = "this is the specific protagonist for this prompt"
  (named, often required, single ref).
- `entity_ref_list` = "these are the named allies" (named list of
  refs of one kind).
- `context_pick` = "stuff the model should know about" (heterogeneous,
  optional, includes presets).

## Files touched (estimated)

New:

- `frontend/src/ContextPicker.svelte` — runtime
- `frontend/src/ContextPickConfigEditor.svelte` — author-time

Modified:

- `backend/app/models.py` — add `context_pick` to `PromptInputType`;
  optionally add `ContextPickConfig` validation
- `backend/app/services/ai/preview.py` (or sibling) — when rendering,
  ensure `input.<name>` for `context_pick` deserializes to a list of
  refs that the template can iterate
- `frontend/src/types.ts` — `PromptInputType` add `context_pick`
- `frontend/src/PromptInputField.svelte` — dispatch to
  `ContextPicker` for the new type
- `frontend/src/DocumentEditorPane.svelte` — Inputs editor surfaces
  the new config row when type is `context_pick`
- `frontend/src/App.svelte` — strip the legacy `+ Context` menu;
  render one `ContextPicker` per `context_pick` input on the active
  prompt in the composer

## Open questions for v2

- **Treatment defaults per type** (NC's toggle). Add to
  `ContextPickConfig` as `treatment_defaults: dict[str, str]`. Picker
  config carries hints; template helpers consult them. Defer until
  template authors ask.
- **Per-item treatment at pick time.** Probably never — author + helper
  combo covers it.
- **Cross-prompt context inheritance** via snippet inclusion. If
  snippet S declares a `context_pick` input and prompt P
  `{% include S %}`s it, do P's runtime composers get S's picker?
  Would need a render-time scan for included snippets to extract their
  inputs.
- **Free-form text fallback** (NC's "Custom content" radio). Could
  layer on as a `context_pick` config option `allow_custom: true` that
  adds a "Type custom content…" item at the bottom of the picker
  menu. Defer.
