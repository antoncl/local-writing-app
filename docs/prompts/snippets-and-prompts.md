# Snippets and prompts

Two node kinds underpin the AI feature.

## `snippet` — reusable text the user wrote once

A snippet is a piece of prose the user authored to be **included** verbatim into one or more prompts. Examples:

- A "house voice" style note repeated across every prose-generation prompt
- A boilerplate persona block ("You are an expert thriller writer with a clipped, declarative style")
- A standing instruction the user wants applied everywhere ("avoid adverbs")

### Properties

- **Kind:** `snippet`
- **Has body:** yes (the body markdown *is* the snippet)
- **Stored at:** `<project>/snippets/<title>.md`
- **Front matter:** `id`, `title`, `entry_type`, and any user-defined fields from the schema

Snippets live in their own folder so they're easy to browse and back up separately. The filename is the title (sanitized), matching the convention used for scenes and lore.

### Including a snippet in a template

Inside a prompt template, snippets are pulled in by node ID. Filenames give you readable IDs:

```jinja
{% include "snippet_house_voice" %}
```

See [Template language](template-language.md) for the full include syntax.

### Inheritance across nested projects

In a recursive project layout (e.g., Honorverse → series → book), snippets inherit downward: a snippet at the universe level is visible inside any descendant book without copying. Editing such a snippet edits the universe-level file, affecting every project beneath. To localize, fork it down to the active project explicitly (see project nesting in the architecture docs, forthcoming).

## `prompt` — an AI invocation, modeled as a node

A prompt is everything required to invoke the AI for one specific task. It pairs:

- An **instruction template** (the body — Jinja2)
- A **context strategy** (what to pull into the envelope before sending)
- **Inputs** the user fills in at dispatch time (e.g., "how many words?")
- Optional overrides for model class, provider policy, etc.

### Abstract parent + concrete sub-types

`prompt` is an **abstract** entry type. Concrete bases under it ship seeded:
`continuation`, `revise`, `general`, and `snippet`. Users may instantiate the
bases directly, or sub-type one to declare the behavior for a specific task.
Roleplay remains a concrete subtype because it changes continuation invocation
behavior. Plot prompts ship as system-provided `general` prompt entries because
they still output to the chat panel.

| Planned sub-type | What it does |
| --- | --- |
| `prompt.continue_scene` | Generate prose from cursor + beat instructions (output: insert at cursor, visual diff) |
| `prompt.revise_selection` | Rewrite a marked selection (output: replace selection, visual diff) |
| `prompt.freeform` | Sparring / brainstorming / research (output: chat panel) |
| `prompt.summarize` | Body → summary field (output: replace field, auto-apply + undo) |
| `prompt.lore_query` | Research over lore canon (output: chat panel) |
| `prompt.character_query` | Roleplay as a character at the current scene's effective state — used to verify mutable-metadata timelines (output: chat panel) |

These sub-types ship seeded with the system schema. Users can fork them or add
their own via the schema editor (M5). System-provided prompt entries can be
duplicated when the user wants a custom editable copy.

### Properties

- **Kind:** `prompt`
- **Has body:** yes (the body markdown is the Jinja2 template; see [Template language](template-language.md))
- **Stored at:** `<project>/prompts/<title>.md`
- **Front matter:** `id`, `title`, `entry_type`, `model_class`, `provider_policy`, `inputs`, `context_strategy`

### Entry-type behavior vs. entry inputs

These belong on the sub-type (`prompt.continue_scene`, etc.), not on individual prompt nodes:

- `context_strategy` — declares the target, scan surface, and output handler

Prompt inputs live on the prompt entry itself. The input declarations and the
Jinja body that reads `input.<name>` are edited together, so duplicating a
system prompt gives the user a local copy of both the inputs and the template.
A user authoring a custom prompt picks (or forks) a sub-type, declares the
inputs, then writes the body template.

### Input types

The `inputs` list on a prompt entry declares the dispatch form. Each entry is:

```yaml
- name: words
  type: number
  label: Words
  default: 300
  required: true
```

Supported `type` values:

| `type` | Renders as | Template value |
| --- | --- | --- |
| `text` | single-line text input | string |
| `long_text` | textarea | string |
| `number` | number input | number |
| `boolean` | checkbox | `True` / `False` |
| `select` | dropdown (uses `options`) | string |
| `entity_ref` | `ReferencePicker` (single) | string id |
| `entity_ref_list` | `ReferencePicker` (multi) | list of string ids |
| `context_pick` | `NodePicker` over scenes, lore, prompts, research, assistants, presets, or plot nodes | JSON string of picked node refs |
| `scene_ref` | single scene picker | string scene id |
| `color` | color swatch picker | string color id |

For `entity_ref` and `entity_ref_list`, an optional `target` carries a `NodePickerConfig` that constrains the picker — same shape as `context_pick` inputs and `entity_ref` metadata fields' `picker_config`:

```yaml
- name: character
  type: entity_ref
  label: Speaking character
  target:
    kinds: [lore]
    entry_types:
      lore: [character]
  required: true
```

Cardinality is implied by the type literal (`entity_ref` → single, `entity_ref_list` → multi); any `multiple` field on `target` is ignored for these types.

Inside the template the value is the raw id (or list of ids). Wrap with `entry()` to walk into fields:

```jinja
{{ entry(input.character).title }}
{% for r in input.related %}- {{ entry(r).title }}{% endfor %}
```

### Picking plot boards for prompt context

Use `context_pick` when the prompt needs to choose one or more nodes as context rather than store a bare lore id. Plot prompts usually declare a single `context_pick` input constrained to the relevant plot objects, then pass that value to `plot_context(...)`. A prompt can render the default XML with `context_xml(...)`, or a snippet can iterate the returned structure and choose its own fields.

```yaml
- name: plot
  type: context_pick
  label: Plot context
  target:
    sources:
      - kind: plot
        expr:
          union:
            - type: plot:board
            - type: plot:template_instance
    multiple: false
  required: true
```

```jinja
{% role "user" %}
Use the active plot board while evaluating the current scene.

{{ context_xml(plot_context(input.plot, as_of=scene)) }}

Scene:
{{ scene.body }}
{% endrole %}
```

`context_pick` values are serialized picked refs, not prose. Helpers decide what to materialize. For plot boards, `plot_context(input.plot)` expands the selected board into cards, claims, template guidance, beat notes, and relationships. For plot template instances, it resolves the board that uses the instance and filters the context down to that template line. Supplying `as_of=scene` filters future manuscript-positioned cards and claims. Template-instance plot beats are returned in template order, so snippets can iterate `plot.template_instances` and `instance.plot_points` directly.

### Seeded plot prompts

New projects include read-only system prompt entries for using a plot board as
AI context without asking the model to write the book. They use
`entry_type: prompt:general`, so they appear with other chat-panel prompts.
Duplicate one to customize its inputs or Jinja body.

`Plot Brainstorm` declares:

- `plot`: a required `context_pick` constrained to plot boards and template instances
- `focus`: a long-text note for the current brainstorming question

The starter body calls `context_xml(plot_context(input.plot))` and frames the
model as a brainstorming partner. It asks for options, tradeoffs, weak claims,
and next questions; it explicitly tells the model not to draft the novel or
treat templates as mandatory rules.

`Plot Claim Audit` declares:

- `plot`: a required `context_pick` constrained to plot boards and template instances
- `focus`: a long-text note for the audit question

The starter body renders an audit-oriented XML-like structure from
`plot_context(input.plot)`. It groups card-local function badges under their
plot beats, includes each claim's rationale/evidence/AI notes when present, and
lists untagged cards. The model is asked to judge whether the claimed cards
collectively earn each beat and to identify weak, missing, duplicated, or
overloaded story work. It also asks for an optional `<plot_suggestions>` block
with target card, claim, template-instance, and plot-beat ids so suggestions can
be copied manually today and turned into explicit apply actions later. The
prompt tells the model to omit placeholder suggestions and only return concrete
draft changes.

## File layout

A fresh M2-era project has:

```
<project>/
  prompts/          (already present pre-M2)
  snippets/         (added by migration v1→v2)
  ...
```

The migration framework (see [strategy_migration](../../README.md)) creates `snippets/` on open for any project that doesn't yet have it.

## See also

- [Template language](template-language.md) — how the body markdown is rendered
- [Helpers](helpers.md) — functions callable from a template
