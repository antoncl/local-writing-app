# Context Picker — Howto

Give a prompt its own **+ Context** button (or several) that opens a constrained,
drill-in menu of the things the author allows the writer to pull in. The author
decides what's pickable; the writer just picks. Each `context_pick` input is
addressed in the template like every other input — `{{ inputs.<name> }}` — so one
prompt can carry a "characters to remember" picker and a "scenes to summarise"
picker side by side.

The design rationale lives in ADR-0074 (`docs/design/adr/`) and its interactive
mockup (`docs/design/mockups/0074-context-picker-take-two.html`). This is the
howto.

## What it gives you

- A `context_pick` input type alongside `text`, `long_text`, `select`,
  `entity_ref`, etc. in the prompt's Inputs editor.
- **Constraint at the source** — the author checks which kinds (Scenes, Lore,
  Plot) and which sub-types, plus any saved views, and the runtime picker offers
  exactly that.
- **Live refs, not snapshots.** Checking a *container* — the whole manuscript, an
  act, a chapter, a plotline, a tag, or a saved view — stores **one** ref that
  expands to its **current** members at invocation. Add a scene to that chapter
  later and the next run includes it, no re-picking.
- The **same picker is reused for `entity_ref` metadata fields**, with the same
  config shape. One vocabulary for both surfaces.

## When to use it

- **`text` / `long_text` / `select`** — free-form or fixed-vocabulary values the
  writer types or picks. Inputs the prompt treats as **strings**.
- **`entity_ref` / `entity_ref_list`** — one specific named ref ("the protagonist
  of this prompt"). Inputs the prompt treats as **a single named entity**.
- **`context_pick`** — a set of refs ("stuff the model should know about"),
  possibly mixing scenes, lore, and plot in one button. Author-constrained,
  writer-chosen context bundles.

Rule of thumb: one named character → `entity_ref`. "Let me toss in whatever's
relevant" → `context_pick`.

## Set up a prompt with a context picker

1. Open **Prompts** in the top bar and edit (or create) a prompt.
2. In the **Inputs** editor, add an input and set its **Label**, **Id** (the
   template will say `inputs.<id>`), and **Type** to **Context Picker**.
3. Configure the source tree:
   - Check the **kinds** — **Scenes**, **Lore**, **Plot** — and, under each,
     optionally restrict to specific sub-types (Lore → only Character + Location).
     Leave a kind's sub-types all-checked to allow any.
   - Add **saved views** as sources if the picker should offer them.
   - **Multiple** — on for "pick several" (default); off for single-pick.
   - **Allow target marking** — only when scenes are pickable; see
     [Scene binding](#scene-binding-target-marking).
   - **Required** — if checked, the prompt won't fire until something is picked.

   (There is no "presets" option any more — "the whole manuscript" is just
   checking the manuscript root in the tree, and the outline is a rendering the
   template chooses, not a pick.)

## How it appears to the writer

The picker is a **drill-in popover**:

- **Root** — a search box and a list of **axes** with counts: Manuscript, Lore,
  Plot, By tag, Saved views (only the ones the config enables). Tap an axis to
  drill into it. When a config exposes exactly **one** axis, the picker skips the
  list and opens straight into that panel.
- **A panel** — a ← back header, the axis name, and that axis's **tri-state tree**.
  Containers open **collapsed**, so a panel leads with its top level (acts, tags,
  plotlines…) instead of a wall of leaves; the manuscript root stays open so its
  acts show. Every container row (act, chapter, plotline, tag, view) carries an
  expand caret and a checkbox:
  - **Check a container** to absorb it — one live ref covering all its current
    members.
  - **Expand** it and check individual members to pick them explicitly.
  - Check a container, then **uncheck one member** — the live ref *splits* into
    explicit picks of the rest (a deliberate freeze).
  - The **Lore** panel groups entries under their entry-type headers (Character,
    Place…) — a header is a collapsible section, not a pickable container.
- **Search is contextual** — a query at the root cuts across every axis (grouped
  results); a query inside a panel filters just that axis. A plain query matches
  titles, tags, and aliases; a leading `#` narrows to tags.
- Picked refs show as rows in the context bar under the button, each with its
  kind stripe and a live member count for containers. Remove one with its `×`.

## Use it in your template

Picked items expose as a list under `{{ inputs.<name> }}`. Containers and
selectors are **already expanded to their concrete members** by the time the
template renders, so you iterate a flat list of nodes:

```jinja
{% for item in inputs.reference_scenes %}
## {{ item.title }}
{{ scene(item.id).body }}

{% endfor %}
```

For a mixed picker, dispatch on `item.kind`:

```jinja
{% for item in inputs.references %}
  {% if item.kind == "lore" %}
### {{ item.title }}
{{ lore(item.id).body }}
  {% elif item.kind == "manuscript" %}
{{ scene(item.id).body }}
  {% endif %}
{% endfor %}
```

**Memory note**: picked refs carry only identity (`kind`, `id`, `title`), never
body content. Materialisation happens server-side when the template renders, via
the helpers (`scene()`, `lore()`, …). Checking the manuscript root stores one
ref, not the prose — the bind layer expands it to the current scene list at
render time.

## Scene binding (target marking)

Enable **Allow target marking** in the input config — only available when scenes
are pickable. When on:

- Picked scene rows show **☆ / ★**.
- The writer marks one scene as the **target** with ★; marking another moves it
  (single ★ per input).
- The marked scene wins over the caller's default (the editor's open scene). The
  template sees it as `{{ scene }}` — `scene.title`, `scene.body`, and
  the scene helpers resolve to the marked one.

**Canonical use case** — the McKee-style evaluator: one prompt, one `context_pick`
input with **Multiple** and **Allow target marking** on. Pick the scenes to
evaluate, then iterate: ★ scene 1 → render → notes; move ★ to scene 2 → render →
notes. One prompt, N runs, without leaving the picker.

For Continuation / Revise the editor's open scene is the default binding, so
marking is an override; for a General prompt (no implicit scene) it's the only
way to bind one.

## Same widget for metadata fields

`entity_ref` and `entity_ref_list` **metadata fields** use the same picker — same
kinds, sub-types, and multiple config — without the input-row chrome (the field
already owns its label / required). The config lives on `PromptInputDefinition.target`
for prompt inputs and on `MetadataFieldDefinition.picker_config` for metadata
fields; the same `NodePickerConfig` shape underneath.

## The stored config

The wire shape of a `context_pick` input in the prompt's YAML:

```yaml
- name: reference_scenes              # {{ inputs.reference_scenes }}
  type: context_pick
  label: "Reference scenes"
  required: true
  target:
    sources:                          # what's pickable — at least one
      - { kind: manuscript }          # scenes + their containers
      - { kind: lore, expr: { type: "lore:character" } }
      - { view: "arc-tracker" }       # a saved view, by id
    multiple: true                    # default true
    allow_target_marking: true        # default false; only when scenes pickable
```

## Caveats

- **Live refs are live.** A checked container reflects membership at *invocation*,
  not at pick time — that's the point, but it means a run's context can change as
  the project changes. Uncheck a member to freeze the rest into explicit picks.
- **Sub-types reference the project schema by id.** Rename a sub-type after
  whitelisting it and the picker drops it from the allowed set — re-open the
  config and re-check.
- **Legacy chat-level `+ Context` is gone.** Old chats keep their pre-`context_pick`
  items (read-only); add new context by binding a prompt that declares one.
- **Per-item treatment ("full text vs summary") isn't in the picker** — the
  template picks via the helpers (`scene.body` vs `scene.summary`).
