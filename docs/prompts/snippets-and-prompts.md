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

`prompt` is an **abstract** entry type. Four concrete bases under it ship seeded:
`continuation`, `revise`, `general`, `snippet`. Users may instantiate the bases
directly, or sub-type one to declare the behavior for a specific task:

| Planned sub-type | What it does |
| --- | --- |
| `prompt.continue_scene` | Generate prose from cursor + beat instructions (output: insert at cursor, visual diff) |
| `prompt.revise_selection` | Rewrite a marked selection (output: replace selection, visual diff) |
| `prompt.freeform` | Sparring / brainstorming / research (output: chat panel) |
| `prompt.summarize` | Body → summary field (output: replace field, auto-apply + undo) |
| `prompt.lore_query` | Research over lore canon (output: chat panel) |
| `prompt.character_query` | Roleplay as a character at the current scene's effective state — used to verify mutable-metadata timelines (output: chat panel) |

These sub-types ship seeded with the system schema. Users can fork them or add their own via the schema editor (M5).

### Properties

- **Kind:** `prompt`
- **Has body:** yes (the body markdown is the Jinja2 template; see [Template language](template-language.md))
- **Stored at:** `<project>/prompts/<title>.md`
- **Front matter:** `id`, `title`, `entry_type`, `model_class`, `provider_policy`, `inputs`, `context_strategy`

### Properties on the entry-type definition (not on the node)

These belong on the sub-type (`prompt.continue_scene`, etc.), not on individual prompt nodes:

- `context_strategy` — declares the target, scan surface, and output handler
- `inputs` — typed input declarations the dispatch UI renders as a form

A user authoring a custom prompt picks (or forks) a sub-type, then writes the body template.

### Input types

The `inputs` list on a sub-type declares the dispatch form. Each entry is:

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

For `entity_ref` and `entity_ref_list`, an optional `target` filters the picker:

```yaml
- name: character
  type: entity_ref
  label: Speaking character
  target: { kind: lore, entry_type: character }
  required: true
```

Inside the template the value is the raw id (or list of ids). Wrap with `entry()` to walk into fields:

```jinja
{{ entry(input.character).title }}
{% for r in input.related %}- {{ entry(r).title }}{% endfor %}
```

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
