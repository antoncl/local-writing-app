# Metadata Strategy

This document records the planned metadata model for primary project entities.

Primary entities include Scenes, Lore Entries, and Prompt Entries. The same
metadata approach should eventually apply to Manuscript Structure entities such
as Acts, Chapters, Sequences, and Arcs.

## Goals

- Keep prose and creative text clean in the editor.
- Keep project files ordinary and inspectable.
- Avoid a second canonical store for entry-owned data.
- Support project-specific metadata fields and entry types.
- Make metadata searchable and eventually filterable.
- Handle malformed user-edited files without silent data loss.

## Entity Model

The long-term model is node-oriented. The current implementation still uses
Scene and Lore Entry terminology at storage/API boundaries, but metadata
definitions are moving toward node types and subtypes:

- `id`: stable identity.
- `kind`: broad system category. Today: `scene`, `lore`, or `prompt`.
- `entry_type`: schema-defined subtype with optional `parent` for single-inheritance
  (e.g. `character` → `lore:base`; `continuation` → `prompt`; `bob` → `general` →
  `prompt`).
- `title`: display title.
- `metadata`: schema-defined values.
- `body`: optional Markdown body for entities that carry prose or text.
- `computed_metadata`: derived values exposed by the app but not stored as
  canonical entry data.

### Class–instance model

In object-oriented language: `kind` is a top-level class, an `entry_type`
declaration is a sub-class with optional single-inheritance, and an actual
entry file (e.g. `scenes/Day 2.md`) is an instance. The schema editor edits
classes; instance editors edit objects.

| OO concept | This codebase |
|---|---|
| Top-level class | `kind` (`scene`, `lore`, `prompt`) |
| Sub-class | An entry-type declaration with `kind: <X>` and optional `parent: <Y>` |
| Abstract base | `abstract: true` on a sub-class (cannot be instantiated, only inherited) |
| Class hierarchy editor | The Custom Data / Node Type pane, scoped to one `kind` |
| Instance list | The pane that lists entries of that `kind` (Manuscript Outline, Lore, Prompts) |
| Instance editor | The document editor opened on a single entry file |
| Inheritance resolution | Backend merges `fields`, `display_template`, `has_body`, `body_editor`, `body_language`, and `prompt` extras up the `parent` chain (see `_resolve_metadata_schema_inheritance`) |

The four kinds today are **scene**, **lore**, **prompt**, and **assistant**. Scenes are book-scoped; lore, prompts, and assistants are layered. Assistants additionally have the machine config dir (`~/.config/local-writing-app/assistants/` or `%APPDATA%/local-writing-app/assistants/`) prepended as a base layer so each user has a per-machine roster that follows them across projects. See [docs/prompts/README.md](prompts/README.md) for the mental model framing.

Each `kind` gets one folder (`scenes/`, `lore/`, `prompts/`), one CRUD endpoint
family (`/api/scenes`, `/api/lore`, `/api/prompts`), and one instance pane in
the UI. The schema editor is contextual: opened from a lore editor it shows
lore sub-classes, from a scene editor it shows scene sub-classes, from a prompt
editor it shows prompt sub-classes.

### Invariants — don't introduce a new `kind` to express:

- **An output disposition.** "I want this prompt to chat vs. append vs. replace"
  is captured by `context_strategy.output.kind` on an entry-type, inherited from
  an abstract base. See [Prompt taxonomy](#prompt-taxonomy) below.
- **A body editor variant.** "I want raw text vs. WYSIWYG vs. code" is captured
  by per-entry-type `body_editor` (`wysiwyg` | `code`) and `body_language`
  (`markdown` | `jinja2` | `plain`), both inherited from the parent chain.
  The seeded `prompt` abstract declares `code` + `jinja2` so all prompt
  sub-types pick it up; everything else defaults to `wysiwyg` + `markdown`.
  A future `research_note` sub-type that wants plain text just declares
  `body_editor: code` + `body_language: plain` — no app code change needed.
- **A user-facing label.** Sub-classes already provide that — `Continuation` and
  `Revise` are sub-classes of `prompt`, not separate kinds.
- **Snippet was wrongly modelled as its own `kind` in an earlier draft.** It is
  a concrete sub-type of `prompt` with no invocation extras. The kind whitelist
  is intentionally short and adding to it must be justified by a genuinely
  different storage shape or routing surface, not by a different user-visible
  affordance.

### Prompt taxonomy

The `prompt` kind has four built-in concrete sub-types. Each captures an
activation surface × output disposition. Users can instantiate them directly,
or sub-type one to add personality (`system_prompt`, the Jinja body) and have
the dispatch behavior inherited automatically.

| Sub-type | Activation surface | Output |
|---|---|---|
| `continuation` | Slash menu in scene editor | Append at cursor (`append_to_body`) |
| `revise` | Selection toolbar | Replace selection (`replace_selection`) |
| `general` | Slash menu / "+ New Chat" | Chat panel (`chat_panel`) |
| `snippet` | None — included by name via `{% include %}` from other prompts | None |

Routing example: a user creates `bob extends general` with the system_prompt
"You are Bob." The dispatcher walks Bob's parent chain to find `general`, sees
the inherited `output.kind: chat_panel`, and surfaces Bob in the prompt picker;
when invoked, the response lands in the chat panel.

The bases used to be abstract — when prompt `inputs` were declared on the type,
abstraction meant "users must create a sub-type to fix the input shape." Once
inputs moved to the instance (the prompt body and its inputs travel together),
the bases had nothing left to parameterize at the type level, so they became
concrete. Users still sub-type them when they want a reusable named role; they
don't have to.

Metadata can describe semantic relationships such as characters, locations, or
parent locations. Manuscript ordering and hierarchy remain in Manuscript
Structure for now. Later, Manuscript Structure can become an ordered view over
entities, but that migration is intentionally separate from the first metadata
slice.

Canonical node identity lives in Markdown front matter, not in the filename.
The app may create machine-generated filenames today, and users may later
rename files to human-readable names. References and Manuscript Structure scene
links should use the stable front-matter `id`. When an older file has no
front-matter `id`, the backend uses the filename stem as a legacy fallback and
validation reports that missing ID.

## Canonical Ownership

- Entry body text is stored in the entry Markdown file.
- Entry metadata values are stored in the entry Markdown file's YAML front matter.
- Entry identity is stored in the entry Markdown file's YAML front matter.
- Metadata field and entry-type definitions are stored in schema files.
- Computed metadata values are derived from canonical files and are not stored as canonical values.
- Search indexes and caches are derived and rebuildable.

## Entry Files

Entry metadata should use standard YAML front matter at the top of the Markdown
file. The prose body follows the front matter.

```markdown
---
title: Day 2
entry_type: scene_mckee
status: draft
metadata:
  summary: "Seren meets the dark-haired boy at the taverna."
  characters:
    - lore:character:seren
  location: lore:location:taverna
---

The dark-haired boy from the taverna leans against the wall...
```

The WYSIWYG editor should show the body text only. Metadata should be edited in
a dedicated metadata UI, not inline in prose.

## Schema Files

Metadata field definitions should be schema-driven. The app should support
layered schema:

- Minimal application defaults: built-in fields and entry types available to all projects.
- Ancestor folder schemas: every `metadata.schema.yaml` from the ancestor
  projects this project declares (`inherits:`, #309) down to the project folder.
  The declaration selects from the folders between the **machine root**
  (`default_projects_folder`, one per machine since #429) and the project; it
  can never reach past that root.
- Project schema: the final project-local `metadata.schema.yaml`.

Ancestor folders are not assigned semantic roles by the app. A user may choose
base, world, series, book, or any other depth; schema files are merged in folder
order, and nearer folders override farther ancestors.

A future project schema may look like this:

```yaml
version: 1

entry_types:
  scene:
    name: Scene
    kind: scene
    fields:
      - status
      - summary
      - characters
      - location
      - word_count

  scene_sequel:
    name: Scene / Sequel
    kind: scene
    fields:
      - status
      - summary
      - scene_phase
      - goal
      - conflict
      - disaster
      - reaction
      - dilemma
      - decision
      - word_count

  scene_mckee:
    name: McKee Scene
    kind: scene
    fields:
      - status
      - summary
      - value_at_start
      - value_at_end
      - value_change
      - turning_point
      - word_count

  lore:base:
    name: Entry
    kind: lore
    abstract: true
    fields:
      - aliases
      - tags
      - related_entries

  character:
    name: Character
    kind: lore
    parent: lore:base
    fields:
      - gender
      - pronouns
      - story_role

  location:
    name: Location
    kind: lore
    parent: lore:base
    fields:
      - parent_location
      - theme

fields:
  status:
    name: Status
    type: select
    options:
      - draft
      - revised
      - complete

  summary:
    name: Summary
    type: long_text

  characters:
    name: Characters
    type: entity_ref_list
    target:
      entry_type: lore:character

  location:
    name: Location
    type: entity_ref
    target:
      entry_type: lore:location

  word_count:
    name: Word Count
    type: computed
    computed:
      source: body
      function: word_count
```

Field IDs should be stable machine-readable keys. Display names can change
without rewriting every entry file.

The effective schema returned by the backend contains inherited `fields` and
derived `own_fields`. Schema files store only local `fields`; `own_fields` is
response-only data used by the UI so each node card can show fields defined
directly on that node while inherited fields remain visible through parent
cards.

## Field Types

Initial field types should stay small:

- `text`
- `long_text`
- `number`
- `boolean`
- `date`
- `select`
- `multi_select`
- `entity_ref`
- `entity_ref_list`
- `tags`
- `computed`

Computed fields are visible to the UI and search layer, but their values are
derived by the app. For example, `word_count` is computed from a scene body and
should not be hand-edited or stored as canonical metadata.

## Search

Metadata should be searchable as first-class entry content.

Free-text search should include title, body, summary, and other text-like
metadata fields. Structured search can later support filters such as:

- `status = draft`
- `characters includes Seren`
- `location = Taverna`
- `entry_type = character`
- `story_role = antagonist`
- `word_count > 1200`

Entity references should be stored by stable ID and displayed by resolved name.
The backend maintains a minimal in-memory identity index while a project is
open:

- file path -> node ID
- node ID -> file path, kind, and entry type

This index is derived by scanning front matter in `scenes/` and `lore/`; it is
not canonical and can be rebuilt at any time. It deliberately does not include
aliases, tags, or search text.

## Malformed Front Matter

Because users can edit project files directly, malformed YAML front matter is an
expected error state.

The app should not silently strip or repair malformed front matter. When loading
an entry with malformed front matter, the backend should report a structured
error containing the path, parse message, and line information when available.

The first recovery options should be:

- Abort loading.
- Open prose only, preserving the file unchanged and disabling save until the
  metadata is repaired.

Project validation should detect malformed front matter across primary entries.

## Export

Manuscript export should parse each scene through the backend, discard front
matter, and concatenate scene bodies in Manuscript Structure order.

Front matter should be excluded from prose export by default. Metadata may later
support export options, such as exporting only scenes with a given status.

## Current Implementation Status

Implemented:

- Generic scene `entry_type` and `metadata` parsing/writing through YAML front
  matter.
- Layered `metadata.schema.yaml` merging from the configured projects base
  folder to the project folder.
- Schema-driven metadata UI for Scenes and Lore Entries.
- Lore Entries with entry subtypes, tags, aliases, references, and Markdown
  bodies.
- Stable front-matter node IDs with filename-stem fallback for older files.
- In-memory identity index for resolving node IDs to files and validating
  reference targets.
- Reference field validation for missing nodes and wrong target kind/entry type.
- Known tags in `tags.yaml`, with case-insensitive matching and backend casing
  as authoritative.
- Custom Data UI that displays node types as a nested tree, with local fields
  collapsed by default on each node card.
- Simple editable field types plus read-only `computed` fields.
- Metadata search across title, body, and metadata values.
- Malformed front matter detection in validation and loading.

Outstanding:

- Generalize the model into a shared base Node concept across Scenes, Lore
  Entries, Prompt Entries, and eventually Manuscript Structure entities.
- Add full field binding management from node cards, including add/remove/delete
  flows and clearer scope controls.
- Add author-friendly reference picker controls that resolve IDs to names in
  the UI.
- Add Prompt Entries.
- Decide how Manuscript Structure nodes become node-backed without disrupting
  ordering and hierarchy.
