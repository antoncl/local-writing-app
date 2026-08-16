# ADR-0059: The body is an intrinsic field, and a field says whether the AI may write it

- Status: Accepted — 0.9.0, 2026-08-16 (Anton, PR #1056)
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
("Body"), a single `long_text` (markdown) type, and a **description** — so it
appears in the resolved field catalog (`_field_catalog`,
`services/ai/helpers.py:211`) exactly like `title` already does. That definition
lives in the shared built-in `fields` registry in `default_schema.py`, beside the
identity intrinsics (`default_schema.py:691`) — the one place an injected
membership key resolves against. It is a *single* shared definition: `body`'s type
does not vary with the type's `body_editor`/`body_shape` (those stay per-type
attributes governing the editor, not the field's type).

### B. `body` is injected only into types that have a body

This is the one way `body` differs from the identity triple. The intrinsics
`title`/`entry_type`/`id` are injected into **every** type's field membership
unconditionally (`_build_entry_type_membership`,
`services/project/schema_inheritance.py:137`). `body` is injected **only when the
resolved type's `has_body` is true** (`mutation_set`, `assistant`, `plot:board`,
and `view` ship `has_body: false`). A bodiless type gets no body field — injecting
one would create a field with no editor and no value.

Two ordering facts the implementer must not miss, or the body field silently
vanishes for the common case:

- **`has_body` is not resolved at injection time.** In `_resolve_one_entry_type`
  the membership build (`_build_entry_type_membership`, `schema_inheritance.py:88`)
  runs **before** attribute inheritance (`_inherit_entry_type_attributes`,
  `:89`), and `has_body` is an *inherited* attribute (`:157-166`). A subtype that
  inherits its body-ness from `lore:character` rather than declaring `has_body`
  itself has no `has_body` on the working dict when injection runs, so a naive
  `if next_entry_type.get("has_body")` guard at injection would omit the body field
  from every inheriting subtype. The body injection must therefore resolve
  `has_body` against the parent chain first (reorder the two steps, or resolve
  `has_body` inline before injecting `body`).
- **`body` is a *conditional* intrinsic, so it cannot join `INTRINSIC_FIELD_KEYS`**
  (`default_schema.py:24`) — that tuple drives the *unconditional* injection
  (`[k for k in INTRINSIC_FIELD_KEYS if k not in existing_fields]`,
  `schema_inheritance.py:138`), which would put a body field on every type. `body`
  gets its own `has_body`-gated injection step, **in the leading intrinsic block**
  (after `title`, the other author-content intrinsic — so the resolved order reads
  `title`, `body`, `entry_type`, `id`, then the stored fields), not appended among
  the stored fields. It is one of the intrinsics, listed with them. Separately, the category stamp
  (`_stamp_field_categories`, `schema_inheritance.py:260`) iterates the **global**
  resolved `fields` registry and stamps each definition once; `body` is marked
  intrinsic there by an added `field_key == "body"` clause alongside the
  `field_key in INTRINSIC_FIELD_KEYS` check — not per-injection.

**This amends ADR-0029 §D** ("the intrinsic key set lives in exactly one place,
`INTRINSIC_FIELD_KEYS`, applied by the resolver"): with a conditional intrinsic
the single set splits into an *unconditional-injection* tuple (`title`,
`entry_type`, `id`) and a *category-stamp* set that additionally includes `body`.
The stamp remains the single source of the `category` a field carries; only the
injection gains a second, gated entry point.

### C. `body` presents through the body editor, not a rail row

Extend ADR-0029 §J's identity routing with a fourth destination: `title` → the
editor header, `entry_type` → the type selector, `id` → nowhere, **`body` → the
body editor** (`ProseBodyView`/`CodeBodyView`, chosen by `body_editor`). Like the
other intrinsics, `body` is **relabel-only** per type ("Body" → "Description" /
"Notes") and is never a metadata-rail row, so it takes no `hide`/`reorder`
(§J's rule: those act on a rail row that does not exist). Body's immovability is
therefore **not a restriction peculiar to body** — it is the standard intrinsic
treatment (`id`/`entry_type`/`title` are equally un-reorderable in the rail).
Accordingly, the schema type editor **lists `body` with the other intrinsics** —
`title`, `entry_type`, `id` — as a pinned, rename-only row in that group, not among
the stored fields. The `MetadataPanel` rail is unaffected; body's field-ness is a
catalog/schema/AI concept, authored in the schema type editor alongside `title`'s
relabel.

### D. Body's description drives the commit contract; the hardcoded body prose is retired

The dump is a *guidance* failure: the contract asks for "the complete revised
markdown body" and says nothing about what belongs there versus in the fields.
Because `body` is now a field, it carries a built-in **description** — text to the
effect of *"Free-form prose for what the structured fields do not capture; do not
restate field values here."* The contract's body clause
(`DEFAULT_EXTRACTION_TEMPLATE`, `services/ai/extraction.py:73`) renders that
description in place of the hardcoded prose. Mechanically, `render_extraction_contract`
(`extraction.py:87`) already resolves the schema for the target `entry_type` to
build the field loop; it resolves body's description the same way and passes it as
a template input, so no new Jinja lookup is needed. This is the fix for the dump —
the model is told what the body is *for*.

The description is a single shared built-in, **overridable per layer** (a layer
redefines the `body` field with its own description) — the same reach every field
description has. It is **not** per-*type* overridable: `FieldOverride` carries only
`label` and `hidden` (`models/schema.py:303`), not `description`, so a
`lore:character` body and a `lore:location` body share one description. Per-type
body guidance would require extending `FieldOverride` with a `description` aspect;
that is a possible follow-up, deliberately **out of scope** here — the single
built-in description already fixes the dump.

### E. A field declares whether the AI may author it: `ai_proposable`

Add one property to the field definition (`MetadataFieldDefinition`,
`models/schema.py:24`): `ai_proposable: bool`, **default `true`**, set per layer by
redefining the field (same reach as `description`). A plain boolean — not an enum
(create-only, propose-but-flag, …): the author-facing question is exactly
"may the AI write this field," and the flag mirrors the existing boolean predicate.

For every field that reaches the model through the `"fields"` object — all
**stored** fields and `title` — it becomes an additional input to
`is_proposable_field` (`services/ai/entry_patch.py:36`), the *single* place that
already decides AI-writability, so it gates both the extraction contract's field
loop and the validate-time filter (`validate_ai_entry_patch_for_type`,
`services/project/metadata_values.py:418`) through one predicate, not a parallel
one. It **ANDs** with `commit.fields` (ADR-0054 §2): a field is proposed only when
allow-listed (or the allow-list is absent) **and** `ai_proposable`.

`body` is the exception, because it does not travel through `"fields"` — it is a
top-level `"body"` key taken verbatim when present (`metadata_values.py:406`) and
described by a dedicated contract clause, not the gated loop. So body's
`ai_proposable` is enforced at those two body-specific sites (the clause is omitted
when body is not proposable; the verbatim adopt drops `body` likewise), not through
`is_proposable_field`. This is a real seam in the "single predicate" story and is
called out, not hidden; its blast radius is nil today (`body` ships `true`), but a
layer that sets body `ai_proposable: false` depends on those two sites honoring it.
Default `true` preserves today's behavior; the flag is an opt-out for author-owned
fields, not a re-permissioning of the schema.

### F. The built-in schema ships `context_policy` as `ai_proposable: false`

`context_policy` (`default_schema.py:830`) is the motivating case: an author-owned
knob that governs whether an entry is *read* into AI context (ADR-0057) — orthogonal
to whether the AI may *write* the field. A commit should never set it. This is the
one built-in field this ADR flips. Other author-owned fields get the flag as they
are observed to need it; the ADR does not sweep a set it cannot enumerate.

### G. The output JSON shape and the save path are unchanged

This ADR changes what *guidance* the contract carries, not its wire contract. In
the emitted JSON, `body` stays a top-level `"body"` key and `title` stays under
`"fields"`, exactly as today — both route through the node's ordinary layered save
(there is no AI-specific body writer: the backend only *validates*,
`metadata_values.py:393`, and the frontend adopts via the normal save path,
`frontend/src/lib/stores/chatCommit.svelte.ts:90`). The required change is only
§D's: body's dedicated clause renders body's description. `body` does **not** join
the generic field loop — it is not enumerated there today (it is not a field yet),
and it stays a top-level key, so nothing in the loop changes for the fix.

**One pre-existing wart, and why cleaning it is optional here.** `title` is already
a proposable intrinsic, so `field_catalog` yields it and the generic loop lists it
*in addition* to its bare `"ALWAYS include title"` clause (`extraction.py:74`) — the
model sees `title` twice today. Collapsing that (and, symmetrically, keeping `body`
out) would mean excluding the proposable intrinsics from the loop, which needs a
filter axis the loop does not currently have: the `_field_catalog` descriptor
exposes `id/label/type/options/description` but **not** `category`
(`helpers.py:255-282`), so the loop cannot say "skip intrinsics" without either
stamping `category` onto the descriptor or hardcoding the `{title, body}` id set.
That cleanup is **out of scope** for the dump fix and is left as a follow-up
(tracked as #1058, filed YAGNI); this ADR neither requires nor blocks it. It is
named so a reader does not mistake the existing `title` redundancy for something
this change introduced.

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
  failure. Guidance that lives in the field definition is authorable (a layer can
  refine it) and reuses the description the field model already carries — one
  mechanism, not a body special case. Hardening the prose in the template would fix
  the dump but leave the guidance un-authorable and permanently body-specific.
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

- **Backend.** `body` gains a built-in `long_text` field definition (label,
  the delineating description, `ai_proposable: true`) in the shared `fields`
  registry beside the identity intrinsics (`default_schema.py:691`). The injection
  gains a **`has_body`-gated** body step — resolving `has_body` against the parent
  chain *before* injecting (attribute inheritance currently runs after membership,
  `schema_inheritance.py:88`→`89`; see §B), and **not** by adding `body` to
  `INTRINSIC_FIELD_KEYS` (that tuple's injection is unconditional). The global
  category stamp (`_stamp_field_categories`, `schema_inheritance.py:260`) gains a
  `field_key == "body"` clause so body stamps `intrinsic`.
  `MetadataFieldDefinition` (`models/schema.py:24`) gains `ai_proposable: bool =
  True`; `is_proposable_field` (`entry_patch.py:36`) reads it (this gates all
  stored fields + `title`). The body clause of `DEFAULT_EXTRACTION_TEMPLATE`
  (`extraction.py:73`) renders body's resolved description (passed in by
  `render_extraction_contract`, `extraction.py:87`) in place of the hardcoded
  prose, and is omitted when body is not `ai_proposable`; the verbatim body adopt
  (`metadata_values.py:406`) drops `body` likewise. `context_policy`
  (`default_schema.py:830`) ships `ai_proposable: false`. The schema-definition
  validator (`_validate_metadata_schema_definition`,
  `services/project/schema_definition_validation.py:158`) needs no clause to
  *store* the boolean (the model has no `extra="forbid"`); add a value check only if
  the property is ever constrained. The generic-loop `title` de-duplication is a
  separate, optional follow-up (§G).
- **Frontend.** The schema type editor already classifies rows by
  `category === "intrinsic"` and renders them rename-only/pinned
  (`SchemaTypeEditor.svelte:546`), so once the backend injects and stamps `body`
  the intrinsic body row appears with no new enumeration code — the same treatment
  `title` gets. The genuinely new UI is the `ai_proposable` toggle on field rows
  (slice 3). The `MetadataPanel` rail is unchanged. The commit adopt path
  (`chatCommit.svelte.ts`) is unchanged beyond honoring whatever the contract emits.
- **The dump fix is body's description; the rest is optional.** The one change that
  stops the dump is §D — body's dedicated clause renders body's description instead
  of the hardcoded "complete markdown body." The pre-existing `title` double-mention
  and any collapse of the special clauses into the generic loop are a separate
  follow-up (§G), neither required nor blocked here.
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
