# Snippets and prompts

Prompts and snippets share one node kind: `prompt`. A *snippet* is not a
separate kind — it is a prompt entry type (`prompt:snippet`) whose role is to be
included into other prompts rather than invoked itself.

## The entry-type taxonomy

`prompt:base` is an **abstract** entry type; two concrete types ship under it:

| Entry type | Role |
| --- | --- |
| `prompt:general` | An invocable prompt — everything from a continue-at-cursor rewrite to a brainstorm chat. What it does is declared per-instance (see below), not by its type. |
| `prompt:snippet` | Import-only reusable text, `{% include %}`d into other prompts by id. Never invocable, whatever its configuration. |

Users may instantiate these directly or sub-type them in the schema editor.
Classification follows the parent chain: a user-defined sub-type of
`prompt:snippet` is itself a snippet — import-only, shelved with the snippets.

## Behavior is on the instance, not the type

A prompt node pairs:

- An **instruction template** — the body markdown, rendered as Jinja2 (see
  [Template language](template-language.md))
- A **context strategy** (`context_strategy` front matter) — what to pull into
  the envelope, and the **output** contract: which handler runs the result
  (inline at cursor / inline over a selection / a conversation, optionally with a
  commit that extracts the result to a node as a reviewable patch)
- **Inputs** (`inputs` front matter) — typed declarations the dispatch UI
  renders as a form
- An optional **offer allow-list** (`offer_on`) — the subject entry types this
  prompt is offered on as a "＋New" conversation

All of these live in the node's own front matter. The entry-type definition
carries none of them: a new prompt starts with no `context_strategy` and behaves
as a plain conversation until its author picks an output in the editor's Setup
tab. (Earlier versions declared `context_strategy` on the sub-type; that was
inverted — behavior is instance-only.)

### Properties

- **Kind:** `prompt`
- **Has body:** yes (the body markdown is the Jinja2 template)
- **Stored at:** `<project>/prompts/<title>.md` — snippets and invocable prompts
  side by side; the entry type in front matter is what separates them
- **Front matter:** `id`, `title`, `entry_type`, plus `inputs`,
  `context_strategy`, `offer_on` as applicable

## Snippets

A snippet is a piece of prose authored once and **included** verbatim into one
or more prompts. Examples:

- A "house voice" style note repeated across every prose-generation prompt
- A boilerplate persona block ("You are an expert thriller writer with a clipped, declarative style")
- A standing instruction applied everywhere ("avoid adverbs")

Inside a prompt template, snippets are pulled in by the **title** you see in the
Library — the name is the handle:

```jinja
{% include "House voice" %}
```

Resolution is layer-aware: your own project's snippet shadows an inherited or
built-in one of the same title, so overriding a shipped snippet is just making one
with the same name. A title that matches two snippets *in the same project* is
ambiguous and does not resolve — the same rule a programming language applies to a
duplicate name; the editor flags it, and running the prompt reports which include
failed. (An id still resolves too, for the rare template that wants to pin an exact
entry, but titles are what the shipped prompts use.)

See [Template language](template-language.md) for the full include syntax.

A snippet may declare `inputs` of its own; a prompt's **effective inputs** are
its own plus the transitive union of every snippet it includes, so a snippet's
fields surface on every invocation form that renders it without hand-copying.

### Inheritance across nested projects

In a nested project layout (e.g., universe → series → book), prompts — snippets
included — inherit downward like other nodes: a snippet at the universe level is
visible inside any descendant book without copying. Editing such a snippet edits
the ancestor-level file, affecting every project beneath; clone it into the
active project to localize. Built-in Library prompts behave the same way
(clone to edit).

## Input types

The `inputs` list on a prompt declares the dispatch form. Each entry is:

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
| `long_text` | multi-line text editor | string |
| `number` | number input | number |
| `boolean` | tri-state select (Unset / True / False) | `True` / `False`; Unset stays undefined, guard with `is defined` |
| `select` | dropdown (uses `options`) | string |
| `multi_select` | multi-select (uses `options`) | list of strings |
| `tags` | tag editor | list of strings |
| `list` | repeatable text rows | list of strings |
| `entity_ref` | `ReferencePicker` (single) | string id |
| `entity_ref_list` | `ReferencePicker` (multi) | list of string ids |
| `color` | color swatch picker | string token |
| `context_pick` | node picker (adds picked nodes to context) | list of nodes; `entry(inputs.pick)` for the first |
| `scene_ref` | scene picker (mutation resolution scene) | string id |

For `entity_ref`, `entity_ref_list`, and `context_pick`, an optional `target`
carries a `NodePickerConfig` that constrains the picker — the same shape
`entity_ref` metadata fields use in `picker_config`. (`scene_ref` ignores
`target`: its picker is always constrained to scenes.)

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

For `entity_ref` and `entity_ref_list`, cardinality is implied by the type
literal (single vs. multi) and any `multiple` field on `target` is ignored. A
`context_pick` is the exception: it is multi-pick unless its `target` sets
`multiple: false` (the shipped Roleplay prompt relies on this for its
single-character pick).

Inside the template the value is the raw id (or list of ids). Wrap with
`entry()` to walk into fields:

```jinja
{{ entry(inputs.character).title }}
{% for r in inputs.related %}- {{ entry(r).title }}{% endfor %}
```

## See also

- [Template language](template-language.md) — how the body markdown is rendered
- [Helpers](helpers.md) — functions callable from a template
- [Reference](reference.md) — the registered prompt vocabulary
