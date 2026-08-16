# ADR-0059: The body is an intrinsic field, and a field says whether the AI may write it

- Status: Proposed — 0.9.0, 2026-08-16
- Feature: stems from a commit-pollution bug (a committed lore entry's `body`
  became a verbatim dump of every structured field) plus the adjacent observation
  that a brainstorm set an author-owned cost knob (`context_policy: always`) it
  did not understand. Implementation issues to be filed on acceptance.
- Extends: ADR-0029 (the field model — categories cut by authorship; intrinsic
  fields route to identity controls, not rail rows)
- Interacts with: ADR-0046 (AI lore editing is a reviewable patch), ADR-0054 §2
  (`commit.fields` allow-list), ADR-0056 (single choke points), ADR-0057
  (`context_policy` governs whether an entry is *read* into context)
- Governed by: `memory/decisions_intrinsic_fields_and_overrides.md`,
  `docs/metadata-strategy.md`

> **Verified against `2a3a6806` (2026-08-16).**

## Context

A brainstorm-committed lore entry's `body` comes back as a verbatim re-statement
of the entry's structured fields. A real example (a `lore:character`): the front
matter holds `aliases`, `tags`, `voice`, `physical_appearance` correctly, and the
markdown body then repeats each one as `**aliases:** …`, `**voice:** …` — the two
long prose fields copied whole. It is not prose a person would write; it is a
serialized field listing. And it goes stale on the first field edit: the author
later changed `context_policy` from `always` to `auto` on the field, and the
body's copy still reads `always`. So the body is a redundant *and* drifting mirror
of the metadata — and, because a lore entry's body is injected into AI context
(`EntryRef.body`, `services/ai/entry_ref.py:128`; `_effective_body`,
`services/ai/helpers.py:1041`), the duplication inflates and contradicts every
context assembly that includes the entry.

Two root causes, both the same shape ADR-0029 named — a field concept handled
ad-hoc, off to the side of the field model:

1. **`body` is not a field.** It is a top-level node attribute with no definition,
   no label, and — decisively — no **description**. The commit's extraction
   contract asks the model for `"<the complete revised markdown body>"`
   (`DEFAULT_EXTRACTION_TEMPLATE`, `services/ai/extraction.py:71`, `:73`) with
   nothing that says what belongs in the body versus in the structured fields. For
   a character, "the complete body" is a natural invitation to write a full
   profile — i.e. every field, again. The contract already renders each *field's*
   `description` in its enumeration loop (`extraction.py:78`), but `body`, not
   being a field, never gets that treatment.

2. **A field cannot say the AI must not write it.** AI-writability is decided by a
   single blanket predicate, `is_proposable_field(field_id, field)`
   (`services/ai/entry_patch.py:36`), keyed on id/type/`hidden` — there is no
   per-field way for an author to mark a field off-limits to a commit. So nothing
   could stop the brainstorm from setting `context_policy` — an author-owned
   cost/visibility knob (`services/project/default_schema.py:830`) — to its most
   expensive value.

Both are resolved inside the field model rather than beside it.

## Decision

### A. `body` is an intrinsic field

Extend ADR-0029 §B: `body` joins `title`/`entry_type`/`id` as an **intrinsic**
field — value produced by the user, living in a top-level node property
(`node.body`), never in `metadata`. This is a virtual/intrinsic field, not a
stored `metadata.body` key: the body stays the markdown body on disk, so the file
format, the atomic prose writes, and `ProseBodyView`/`CodeBodyView` are untouched.
What changes is that `body` gains a built-in field **definition** — a label
("Body"), a long-text/markdown type aligned with the type's `body_editor` /
`body_shape`, and a **description** — so it appears in the resolved field catalog
(`_field_catalog`, `services/ai/helpers.py:211`) exactly like `title` already does.

### B. `body` is injected only into types that have a body

This is the one way `body` differs from the identity triple. The intrinsics
`title`/`entry_type`/`id` are injected into **every** type's field membership
unconditionally (`_resolve_field_membership`,
`services/project/schema_inheritance.py:137`). `body` is injected **only when the
resolved type's `has_body` is true** (`has_body` is a per-type attribute inherited
at `_inherit_entry_type_attributes`, `schema_inheritance.py:159`; `mutation_set`,
`assistant`, `plot:board`, and `view` ship `has_body: false`). A bodiless type
gets no body field — injecting one would create a field with no editor and no
value. The category stamp (`_stamp_field_categories`,
`schema_inheritance.py:260`) marks `body` intrinsic wherever it was injected.

Concretely, `body` is a **conditional** intrinsic and therefore cannot simply
join the `INTRINSIC_FIELD_KEYS` tuple (`default_schema.py:24`) — that tuple drives
the *unconditional* injection at `schema_inheritance.py:138`
(`[k for k in INTRINSIC_FIELD_KEYS if k not in existing_fields]`), which would put
a body field on every type including the bodiless ones. `body` needs its own
`has_body`-gated injection step, and inclusion in the *category stamp's* intrinsic
check — the two uses of that tuple pull apart for `body`.

### C. `body` presents through the body editor, not a rail row

Extend ADR-0029 §J's identity routing with a fourth destination: `title` → the
editor header, `entry_type` → the type selector, `id` → nowhere, **`body` → the
body editor** (`ProseBodyView`/`CodeBodyView`, chosen by `body_editor`). Like the
other intrinsics, `body` is **relabel-only** per type ("Body" → "Description" /
"Notes") and is never a metadata-rail row, so it takes no `hide`/`reorder`
(§J's rule: those act on a rail row that does not exist). The `MetadataPanel` is
unaffected; body's field-ness is a catalog/schema/AI concept, authored in the
schema type editor alongside `title`'s relabel.

### D. A field's description drives the commit contract; the hardcoded body prose is retired

Because `body` is now a field with a `description`, the contract stops hardcoding
"the complete revised markdown body" and instead carries body's description —
built-in text to the effect of *"Free-form prose for what the structured fields do
not capture; do not restate field values here"* — per-type overridable like any
field description (a character's body means something different from a location's).
This is the fix for the dump: the model is told what the body is *for*, in the same
description channel every other field already uses.

### E. A field declares whether the AI may author it: `ai_proposable`

Add one property to the field definition (`MetadataFieldDefinition`,
`models/schema.py:24`): `ai_proposable: bool`, **default `true`**, overridable per
layer/type exactly like `description`. It becomes an additional input to the
existing `is_proposable_field` predicate (`services/ai/entry_patch.py:36`) — the
*single* place that already decides AI-writability — so it gates the extraction
contract's field loop and the validate-time filter
(`validate_ai_entry_patch_for_type`, `services/project/metadata_values.py:418`)
through one mechanism, not a parallel one. It **ANDs** with `commit.fields`
(ADR-0054 §2): a field is proposed only when it is allow-listed (or the allow-list
is absent) **and** `ai_proposable`. Default `true` preserves today's behavior; the
flag is an opt-out for author-owned fields, not a re-permissioning of the schema.

### F. The built-in schema ships `context_policy` as `ai_proposable: false`

`context_policy` (`default_schema.py:830`) is the motivating case: an author-owned
knob that governs whether an entry is *read* into AI context (ADR-0057) — orthogonal
to whether the AI may *write* the field. A commit should never set it. This is the
one built-in field this ADR flips. Other author-owned fields get the flag as they
are observed to need it; the ADR does not sweep a set it cannot enumerate.

### G. The output JSON shape and the save path are unchanged

This ADR changes what *guidance* the contract carries, not its wire contract. In
the emitted JSON, `body` stays a top-level `"body"` key and `title` stays under
`"fields"`, exactly as today — both continue to route through the node's ordinary
layered save (there is no AI-specific body writer: the backend only *validates*,
`metadata_values.py:393`, and the frontend adopts via the normal save path,
`frontend/src/lib/stores/chatCommit.svelte.ts:90`). Concretely, the generic
field-catalog loop enumerates only the `stored`/`computed` metadata fields; the two
*proposable intrinsics*, `title` and `body`, keep their dedicated contract clauses,
which now source their label and description from the field definition. This also
removes a pre-existing redundancy: `title` is currently emitted **both** by its
special clause **and** by the field loop (it is a proposable intrinsic, so
`field_catalog` already yields it), so it is double-mentioned to the model today.

## Why / rejected alternatives

- **Why `body` is intrinsic, not stored.** Body is a top-level node attribute
  authored as prose through a dedicated editor — the exact intrinsic shape (a node
  property, a dedicated control, never a rail widget), the same as `title`. Making
  it a stored `metadata.body` key would move prose out of the markdown body,
  breaking the file format, the atomic prose writes, and the body views, for no
  gain. "Virtual field" is precisely the intrinsic model ADR-0029 already runs.
- **Why conditional injection.** `body` is not universal the way identity is;
  `has_body` already models exactly which types have one. Injecting `body` into a
  bodiless type would manufacture a field with no editor and no value — a §C
  routing with no destination.
- **Why a description, not a hardened code clause.** The dump is a *guidance*
  failure. Guidance that lives in the field definition is per-type overridable and
  reuses the contract's existing description rendering — one mechanism, not a body
  special case. Hardening the prose in the template would fix one type's dump while
  leaving the guidance un-authorable and still body-specific.
- **Why `ai_proposable` feeds `is_proposable_field` rather than adding a filter.**
  That predicate is already the one choke point for AI-writability (ADR-0056);
  giving it a per-field input keeps a single decision site. A second gate elsewhere
  could disagree with it — the class of bug ADR-0056 exists to prevent.
- **Why the default is `true`.** The flag is an opt-out for a few author-owned
  fields. Defaulting it `false` would silently stop the AI proposing every
  user-defined field — a schema-wide behavior change disguised as a field property.
- **Rejected: exclude `context_policy` by hardcoding its id** (extend
  `NON_PROPOSABLE_FIELD_IDS`, `entry_patch.py:33`). That pins one field's policy in
  Python. Author-owned-ness is a schema fact a layer should be able to declare
  (a user marking their own `canon_locked` field un-writable by the AI). The
  per-field flag is the general form; the id-list is the special case it subsumes.
- **Rejected: a separate "policy" field category.** `context_policy` is an ordinary
  stored `select`; it differs only in that the author does not want the AI setting
  it — which is one boolean, not a new authorship category. This mirrors ADR-0029's
  rejection of a bespoke `color` category.
- **Rejected: auto-rewrite the already-polluted bodies.** These are live project
  files; a bulk body rewrite is an irreversible mass-edit on the author's prose.
  Fix forward (see Consequences).

## Consequences

- **Backend.** `body` gains a built-in intrinsic field definition (label, a
  long-text/markdown type, the delineating description, `ai_proposable: true`), and
  the injection at `schema_inheritance.py:137` grows a `has_body` guard for it while
  the identity triple stays unconditional; `_stamp_field_categories` stamps it
  intrinsic. `MetadataFieldDefinition` (`models/schema.py:24`) gains
  `ai_proposable: bool = True`; `is_proposable_field` (`entry_patch.py:36`) reads
  it. `DEFAULT_EXTRACTION_TEMPLATE` (`extraction.py:66`) sources the `title`/`body`
  clauses' label and description from the field definition and drops `title`/`body`
  from the generic loop. `context_policy` (`default_schema.py:830`) ships
  `ai_proposable: false`. The schema-definition validator
  (`_validate_metadata_schema_definition`,
  `services/project/schema_definition_validation.py:158`) needs no clause to
  *store* the boolean (the model has no `extra="forbid"`); add a value check only if
  the property is ever constrained.
- **Frontend.** The schema type editor gains an `ai_proposable` toggle on field
  rows and surfaces `body` as an intrinsic row (rename-only, pinned) carrying its
  relabel + description, exactly as it treats `title`. `field_catalog` consumers
  already read `description`, so body's guidance renders with no new plumbing. The
  `MetadataPanel` rail is unchanged. The commit adopt path
  (`chatCommit.svelte.ts`) is unchanged beyond honoring whatever the contract emits.
- **Complying is the cleanup (per ADR-0029).** The special body clause and the
  `title` double-mention collapse into the field model; the dump stops for new
  commits. This is not an optional tidy-up — it *is* the fix.
- **Out of scope / anti-goals.** No bulk rewrite of existing bodies — an author-run,
  per-entry, reviewed one-shot script may be offered separately. `body` never
  becomes a stored `metadata.body` key. `ai_proposable` is generation-only, never a
  read/visibility control (that is `context_policy`). The output JSON shape and the
  save path do not change. Only `context_policy` is flipped in the built-in schema;
  no field set is swept. This ADR does not touch how `context_policy`'s *values* are
  consumed (ADR-0057).

Implementation splits into separable slices, to be filed on acceptance: (1) `body`
as an intrinsic field with a description (backend + schema editor row); (2) the
`ai_proposable` property threaded through `is_proposable_field`, with
`context_policy` shipped `false`; (3) the schema-type-editor toggle UI.
