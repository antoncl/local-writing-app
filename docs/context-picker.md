# Context Picker — Howto

Give a prompt its own **+ Reference** button (or several) that opens a constrained menu of the kinds of nodes the author allows. The author decides what's pickable; the writer just picks. Each `context_pick` input is addressed in the template the same way every other input is — `{{ input.<name> }}` — so one prompt can have a "characters to remember" picker, a "scenes to summarize" picker, and a "preset to attach" picker side by side.

## What it gives you

- A new input type **`context_pick`** that sits alongside `text`, `long_text`, `select`, `entity_ref`, etc. in the prompt's Inputs editor.
- **Constraint at the source** — the author checks which kinds (Scene, Lore, Snippet, Assistant) and which sub-types per kind, plus optional presets (Full Outline / Full Novel Text), and the runtime picker offers exactly that.
- The **same picker UI is reused for `entity_ref` metadata fields**, with the same config shape. One vocabulary for both surfaces.
- Picked items render as **chips** in the composer. Click `×` to drop one. Reopen the picker to add more (unless `multiple: false`).
- Optional **★ target marking** — when enabled, the author can pick several scenes then iterate with ★ moving between them across invocations. Same prompt, N runs against N scenes.

## When to use it

- **`text` / `long_text` / `select`** — free-form or fixed-vocabulary values the user types or picks. Good for inputs the prompt treats as **strings**.
- **`entity_ref` / `entity_ref_list`** — one specific named ref ("the protagonist of this prompt"). Good for inputs the prompt treats as **a single named entity** (or list of one kind).
- **`context_pick`** — a heterogeneous pile of refs ("stuff the model should know about"). Good for **author-constrained, runtime-chosen context bundles** — possibly mixing scenes + lore + presets in one button.

Rule of thumb: if you want one named character → `entity_ref`. If you want "let me toss in whatever's relevant" → `context_pick`.

## Set up a prompt with a context picker

1. Open **Prompts** in the top bar and edit (or create) a prompt.
2. In the **Inputs** editor, click **+ Input**.
3. Set the input's **Label** (e.g. "Reference scenes"), **Id** (e.g. `reference_scenes` — the template will say `input.reference_scenes`), and **Type** to **context_pick**.
4. The row expands. Configure:
   - **Kinds** — check Scene / Lore / Snippet / Assistant. At least one is required (a picker with nothing pickable is a bug, not a config).
   - **Sub-types** — under each checked kind, optionally restrict to specific sub-types (e.g. Lore → only Character + Location). Leave all checked to allow any sub-type of that kind.
   - **Presets** — check Full Outline / Full Novel Text if the picker should offer them as one-click attachments.
   - **Multiple** — leave on for "pick several" (the default). Turn off for single-pick.
   - **Allow target marking** — only available when scenes are pickable. See [Scene binding](#scene-binding-target-marking) below.
5. **Required** — if checked, the runtime won't fire the prompt until something is picked.
6. Save.

## How it appears to the user

When the prompt is bound to a chat:

- **Composer strip** — one **+ <Label>** button per `context_pick` input on the active prompt. Click to open the constrained menu.
- **Picker menu** —
  - **Presets** section (if any allowed): one button per preset.
  - **Browse** section: one expandable group per allowed kind, with a search box if the group has more than ~20 items.
- **Chips** — each picked item shows above the message textarea. Click `×` to drop one.
- **Initial inputs dialog** — if the user picks the prompt fresh (vs invoking via `/slash` with positional args), the dialog renders one row per declared input, including the button-and-chips row for each `context_pick`. Picked values seed the chat — no need to reopen the picker after the first turn.

If you set **Multiple** to off, the menu closes after one pick and any prior pick is replaced.

## Use it in your template

Picked items expose as a list under `{{ input.<name> }}`. The template iterates:

```jinja
{% for item in input.reference_scenes %}
## {{ item.title }}
{{ scene(item.id).body_markdown }}

{% endfor %}
```

For mixed pickers (scenes + lore + presets), each item carries `kind` + `type` you can dispatch on:

```jinja
{% for item in input.references %}
  {% if item.kind == "preset" and item.id == "full_outline" %}
{{ full_outline() }}
  {% elif item.kind == "lore" %}
### {{ item.title }}
{{ lore(item.id).body_markdown }}
  {% elif item.kind == "scene" %}
{{ scene(item.id).body_markdown }}
  {% endif %}
{% endfor %}
```

**Memory note**: picked refs carry only `{kind, id, type, title}` — no body content. Materialization happens server-side when the template renders, via the existing helpers (`scene()`, `lore()`, `full_outline()`, `full_text()`). Picking "Full Novel Text" stores one preset ref, not the prose — the helper iterates scene files at render time.

## Scene binding (target marking)

Enable **Allow target marking** in the input config — only available when scenes are pickable. When on:

- Picked scene chips show **☆ / ★** indicators.
- The user marks one scene as the **target** by clicking ★. Clicking ★ on another scene moves the mark (single ★ per input).
- The marked scene wins over the caller's default scene (the editor's open scene). The template sees it as `{{ scene }}` — `scene.body_markdown`, `scene.title`, and the scene helpers all resolve to the marked one.

**Canonical use case** — the McKee-style evaluator: one prompt with a single `context_pick` input, **Multiple: on** + **Allow target marking: on**. Pick 8 scenes you want to evaluate, then iterate: ★ scene 1 → render → notes; move ★ to scene 2 → render → notes; etc. One prompt, eight runs, no leaving the picker.

For Continuation / Revise prompts the editor's open scene is the default `scene` binding — marking via context_pick is purely an override. For General prompts (no implicit scene), marking is the only way to bind a scene at all.

## Same widget for metadata fields

`entity_ref` and `entity_ref_list` **metadata fields** use the exact same picker — same kinds + sub-types + multiple config. In the schema editor, opening an entity_ref field reveals the same picker config UI (just without the row-level chrome: no label / required toggle / type select, since the field already owns those).

The wire-format field name differs by surface:

- On `PromptInputDefinition` (prompts) the config sits on `target`.
- On `MetadataFieldDefinition` (metadata) the config sits on `picker_config`.

Same `NodePickerConfig` shape underneath; the UI handles both.

## Inputs reference

The wire shape of a `context_pick` input as stored in the prompt's YAML:

```yaml
- name: reference_scenes              # macro key: {{ input.reference_scenes }}
  type: context_pick
  label: "Reference scenes"
  required: true
  target:
    kinds: ["scene"]                  # at least one required
    entry_types:                      # optional, per kind
      lore: ["character", "place"]
    presets: ["full_outline"]         # optional
    multiple: true                    # default true
    allow_target_marking: true        # default false; only when scenes pickable
```

Picked-item shape (what the template iterates):

```yaml
- kind: scene
  id: scene_abc
  type: scene                         # the sub-type (e.g. "scene", "chapter")
  title: "The Causeway"
- kind: preset
  type: preset
  id: full_outline
  title: "Full Outline"
- target: true                        # marked-target flag, when target-marking on
  kind: scene
  id: scene_xyz
  type: scene
  title: "The Reckoning"
```

## Caveats

- **Legacy chat-level `+ Context` is gone.** Old chat sessions with pre-`context_pick` `chatContextItems` still render their items (read-only). Add new context by binding a prompt that declares a `context_pick` input.
- **Sub-types reference the project schema by id.** If you rename a sub-type after authoring a prompt that whitelisted it, the picker silently drops it from the allowed set. Re-open the input config and re-check.
- **Presets are server-side helpers.** Picking "Full Novel Text" doesn't pull every scene into the chat session — it stores one preset ref, and `full_text()` iterates at render time. No memory cost.
- **Per-item treatment ("full text vs summary") is not in the picker** — that's a render-time concern. The template author picks via the helpers (`scene.body_markdown` vs `scene.summary`).
- **Group related kinds into one picker** rather than declaring three separate `context_pick` inputs if they conceptually pick "the same kind of thing" — three pickers = three composer buttons.
