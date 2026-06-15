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
- `kind`: broad system category, currently `scene` or `lore`.
- `entry_type`: schema-defined subtype, such as `scene`, `scene_sequel`,
  `scene_mckee`, `character`, `place`, `item`, or `lore_note`.
- `title`: display title.
- `metadata`: schema-defined values.
- `body_markdown`: optional Markdown body for entities that carry prose or text.
- `computed_metadata`: derived values exposed by the app but not stored as
  canonical entry data.

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
- Ancestor folder schemas: every `metadata.schema.yaml` from
  `settings.projects_base_folder` down to the project folder.
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

  lore_entry:
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
    parent: lore_entry
    fields:
      - gender
      - pronouns
      - story_role

  place:
    name: Location
    kind: lore
    parent: lore_entry
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
      entry_type: lore_character

  location:
    name: Location
    type: entity_ref
    target:
      entry_type: lore_location

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
