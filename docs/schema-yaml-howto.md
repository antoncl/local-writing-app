# Editing `metadata.schema.yaml` by hand

The schema editor in the app handles the common cases — adding fields,
renaming, attaching to entry types. A few advanced things don't have UI
yet and have to be done by editing the project's `metadata.schema.yaml`
directly. This file is the canonical reference for those edits until the
schema editor catches up.

The project layer file lives at `<project root>/metadata.schema.yaml`.
Anything you put there overrides the built-in defaults for that one
project. After editing, restart `uvicorn` (or wait for the auto-reload)
and hard-refresh the browser. The schema layering does a structural
merge with the built-ins — you only have to write the keys you're
changing, not a complete entry type.

---

## Global chapter numbering — "Chapter 1, 2, 3" across the whole manuscript

Default is sibling-scoped, so chapters restart inside each act. To get a
single global sequence, override the `number` field at the project layer:

```yaml
version: 1
fields:
  number:
    name: "Number"
    type: computed
    computed:
      function: counter
      scope: manuscript
```

`scope: siblings` (default) resets the counter under each parent of the
same type. `scope: manuscript` counts in depth-first order across the
whole tree, so the third Chapter — wherever it lives — is always
`Chapter 3`.

Both scopes count only nodes whose `entry_type` matches the target's
own. So switching to `manuscript` for `number` gives global Act
numbering, global Chapter numbering, and global Scene numbering at the
same time (siblings reset within each chapter still produced the per-
parent variant).

---

## Localised outline titles — "Akt 1", "Kapitel 3"

`display_template` is a string with `{field}` placeholders. It lives on
the entry type and is inherited from the parent, so the simplest
localisation override is on `manuscript_structure` (it cascades to act,
chapter, scene, plus anything you subclass from it later):

```yaml
version: 1
entry_types:
  manuscript_structure:
    display_template: "{number}. {title}"   # default English
  act:
    display_template: "Akt {number}: {title}"
  chapter:
    display_template: "Kapitel {number}: {title}"
  scene:
    display_template: "Szene {number}: {title}"
```

Available placeholders inside a template:

- `{title}` — the node's title field
- any computed field id on the entry type — currently `{number}` and
  `{word_count}`, plus anything you add later
- (planned) any metadata field id

If a referenced field is missing on a node, it substitutes to an empty
string. The template is purely display — it doesn't affect the title
stored in the file or in search results.

---

## Subclassing a manuscript container type — "Prologue", "Part"

The schema editor lets you subclass via the "+ type" affordance, but you
can also do it by hand. A custom container type just needs `kind: scene`
and `parent: manuscript_structure` (or any other type you want to
inherit from). Inheritance brings the `number`, `summary`, and
`display_template` along automatically.

```yaml
version: 1
entry_types:
  prologue:
    name: "Prologue"
    kind: scene
    parent: chapter            # inherits chapter's fields + display
  part:
    name: "Part"
    kind: scene
    parent: manuscript_structure
    display_template: "Part {number}: {title}"
```

A subclass with its own `display_template` overrides the parent's; one
without inherits. A subclass that adds fields concatenates onto the
parent's field list.

---

## File naming

Scene, container, and lore entry files are named by their **title**, not
by an internal id. So a chapter called *The Departure* lives at
`scenes/The Departure.md`, and a character *Seren* lives at
`lore/Seren.md`. The canonical identity is still the `id:` field in the
front matter; the filename is just an alias for it.

This means you can open `scenes/` or `lore/` in Explorer or Finder and
the contents are immediately legible. Renaming a node in the app
renames the underlying file. Renaming a file by hand outside the app
is also safe — the app finds it by front-matter id on the next load.

Title sanitisation:

- Forbidden filesystem characters (`< > : " / \ | ? *` and control
  chars) are replaced with `_`
- Trailing dots and spaces are trimmed
- Names are capped at 100 characters
- Empty titles fall back to `Untitled`
- Windows reserved names (`CON`, `PRN`, `COM1`, etc.) get a leading `_`

Collisions get a `(2)`, `(3)`, … suffix. Two scenes called *Chapter 1*
land at `Chapter 1.md` and `Chapter 1 (2).md`.

---

## Other tweakable knobs

| Field on entry type | Meaning | Default |
|---|---|---|
| `name` | Display name shown in the schema editor | type id |
| `kind` | `scene` for manuscript nodes, `lore` for lore | (required) |
| `parent` | Parent entry type id (for inheritance) | none |
| `abstract` | If true, can't be instantiated; only inherited from | false |
| `display_template` | Outline title template, see above | `{title}` |
| `has_body` | If false, hide the body markdown editor when this type is open. Inherited. | true |
| `fields` | List of field ids to attach (concatenates with parent's) | `[]` |

Anything not listed here either has no override yet or hasn't been
documented because the UI covers it.
