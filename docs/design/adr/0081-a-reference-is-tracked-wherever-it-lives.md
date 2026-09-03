# ADR-0081: A reference is tracked wherever it lives in the metadata

- Status: **Accepted** — 2026-09-02, Anton, PR #1761. Shaped with Anton, who reframed the
  restriction from "a missing feature" to a **data-model inconsistency the user must remember**,
  and named the fix as *one traversal, not six*. Approval settled `tags` **in** (§4) and edges
  staying **field-keyed** (member-level backlinks deferred).
- Verified against `16c3b9fd` (2026-09-02).
- Resolves: #1711 (entity_ref / entity_ref_list / tags barred from metadata group item shapes — a
  v1 restriction that lived only in a code comment).
- Relates: **ADR-0048** (introduced list/group item shapes, #698 — the ADR that should have
  recorded this restriction and did not); **ADR-0029** (the field model — stored/intrinsic/computed
  by authorship); **ADR-0079 §2** (narration deliberately *sidestepped* this restriction by keeping
  `pov` top-level — this ADR is the "revisit on its own merits" that §2 promised). Builds on the
  reference machinery (`references.py`, `NodeIndex`) and the read-side healers
  (`services/project/metadata_values.py`).
- Supersedes: nothing.

## Problem

A metadata **group** is the item shape of a `list` field (an `item_group`): it lets a user record a
repeatable *structured* value on a node — a list of `{target, kind}` objects, a list of
`{place, role}` objects. That is the point of a group: to record compound information, and the most
valuable compound information a fiction writer records is **relational** — a character's
relationships, a location's connections, a scene's participants, a faction's members. Those are
`entity_ref`s by nature.

Today a group **cannot** contain an `entity_ref`, `entity_ref_list`, or `tags` member. A group can
hold `text`, `number`, `select`, `color` — and nothing that points at another node. The enforcement
is `_list_field_schema_errors` (`schema_definition_validation.py`), the type catalog is
`LIST_ITEM_SCALAR_TYPES` (`schema.py`), and the whole rationale is a **code comment** (`schema.py`,
the "v1 keeps entity_ref … OUT of item shapes" note) that never went through a design decision.

**This is a data-model inconsistency, not a feature gap.** A field type is a field type; a group is
a container of fields; a container that silently rejects three of them makes the model non-uniform,
and a user modelling their world has to carry an arbitrary exception in their head — *groups hold
anything, except references and tags*. That is exactly the wart this codebase's uniformity
principles exist to prevent (the same instinct as "the same widget per type across
default/options/value", "every tree node is a real Node", one walker for every hierarchy).

**And the restriction is a *defense*, not an *invariant*.** It guards a single recurring shape: four
backend passes each iterate a node's `metadata.items()`, dispatch on the field's declared type, and
handle references **only at the top level** — never descending into a `list`/`item_group` item. So a
ref nested in a group would be:

- **invisible to the reference index and backlinks** — `_edges_from_field` (`references.py`) treats a
  `list`-typed field as yielding no edges, so a nested ref never becomes a `ReferenceEdge`;
- **never scrubbed on delete** — `_purge_metadata_refs` (`metadata_values.py`) rewrites only
  top-level `entity_ref`/`entity_ref_list` values, so a nested ref to a deleted node **silently
  mis-links** (the exact failure the comment names);
- **never hidden when dangling** on read — `_strip_dangling_references` (`metadata_values.py`) walks
  top-level values only;
- **shown as a raw id** instead of a title — `_resolve_reference_titles` (`search.py`) resolves only
  top-level refs.

v1 forbade the case rather than teach those passes to descend. The honest repair is not to enshrine
the carve-out in an ADR — that would be *recording an inconsistency as if it were a decision* — but
to make the real invariant hold and drop the defense.

## Decision

**Every `entity_ref` / `entity_ref_list` / `tags` value in a node's metadata — at any depth the
schema permits, including inside a `list`-of-`item_group` value — is discovered and rewritten
through one canonical traversal that the reference lifecycle consumes; once that invariant holds, a
group holds any field type, with no carve-out.**

The traversal is the fix and the safety. The passes stopped at the top level precisely *because*
each re-derived its own "walk metadata, dispatch on field type" loop; consolidating that walk into
one place defines "at any depth" **once**, so no pass can forget to descend.

### 1 — One canonical metadata-reference traversal

A single walker — call it the metadata-ref visitor — takes a node's metadata `dict` and its
resolved entry schema and yields every reference-or-tag **occurrence**: the field, the member (for a
group), the value, and enough **location** to rewrite it in place. It knows the two shapes the model
actually has (it is not open-ended recursion):

- a **top-level** ref/tag field (`entity_ref` scalar, `entity_ref_list` list-of-ids, `tags` list);
- a **`list`-of-`item_group`** field, whose value is a sequence of maps keyed by member key, where a
  member may be `entity_ref` (a bare id), `entity_ref_list` (a list of ids nested inside the map), or
  `tags`.

Groups do not nest inside groups (a `GroupMember` is a scalar/ref/tag field, never another
list/group), so the traversal is exactly **one level** deep — bounded, not arbitrary. The visitor
exposes a **read** form (yield occurrences, for indexing and title resolution) and a
**rewrite-in-place** form (map each occurrence's value, for purge and healing), so a caller never
re-implements the descent to mutate.

### 2 — The four lifecycle passes consume the one traversal

Each pass keeps *what it does with an occurrence* and gives up *how it finds one*:

- **Index / backlinks** — `_edges_from_field` / `_reference_edges_for_entry` (`references.py`) emit a
  `ReferenceEdge` for every occurrence the read visitor yields, nested included.
- **Delete purge** — `_purge_metadata_refs` (`metadata_values.py`) uses the rewrite visitor to drop a
  scalar `entity_ref` / filter an `entity_ref_list` wherever it lives — the pass that closes the
  silent-mis-link.
- **Read-side dangling strip** — `_strip_dangling_references` (`metadata_values.py`) hides a nested
  dangling ref on read via the same rewrite visitor.
- **Title resolution** — `_resolve_reference_titles` (`search.py`) swaps a nested id for its title.

Id → node resolution is already shape-agnostic (`NodeIndex.by_id`), so a nested ref resolves fine
**once it is indexed** (§2's first bullet); no resolver change beyond that.

### 3 — The gate opens, but only after §1–§2

With every occurrence tracked, the container no longer needs the carve-out. Widen, in lock-step:

- `LIST_ITEM_SCALAR_TYPES` / the member-type check in `_list_field_schema_errors`
  (`schema_definition_validation.py`) to admit `entity_ref` / `entity_ref_list` / `tags` members;
- the `ListItemScalarType` Literal (`schema.py`) **only if** we also want the scalar-sugar
  `item_type: entity_ref` path (a single-ref list without a named member) — otherwise leave the
  scalar-sugar catalog alone and admit refs through the `item_group` path only;
- the TS mirror `LIST_ITEM_SCALAR_TYPES` (`types.ts`) and the schema-authoring UI filter
  `shapeableGroups` (`SchemaFieldInlineEditor.svelte`), which hides ref-member groups from the
  item-shape picker today.

Opening the gate before §1–§2 land would reintroduce the mis-link; the gate is the **last** step.

### 4 — "Any field" includes tags, and uniformity is finished, not half-done

Consistency is the whole argument, so the carve-out lifts for **all three** barred types, not just
the `entity_ref` pair. `tags` members pull in two more top-level-only walkers that must descend for
tags to behave inside a group as they do outside: tag **canonicalise/register**
(`_canonicalise_metadata_tags`, `metadata_values.py`) and tag **rename**
(`_rename_tag_in_documents`, `tags.py`; the assistant-tag paths similarly). *(Decided **in** at
approval: the model keeps no remaining exception. This is the one place where scope buys the least
per unit of surface, so the tag-path descent is the natural descope line if implementation finds its
surface outsized — recorded as the fallback, not the plan.)*

Full uniformity also means the **adjacency** passes that walk metadata the same top-level way stop
mis-handling a nested ref/tag: the AI context envelope (`ai/entry_ref.py`, `ai/lore_block.py`),
promotion's ref/tag partitioning across layers (`project/promotion.py`), and lore-mutation
collection handling (`project/lore_mutations.py`). These are not the delete/index/heal *integrity*
core, but leaving them top-level-only would make a nested ref real everywhere except the AI context
and promotion — a new, quieter inconsistency. They consume the same read visitor.

### 5 — What is already uniform, and therefore free

The encouraging half: the container's **authoring and validation** side already treats refs as
first-class; only the **lifecycle** lagged.

- **References are stored by stable `id`, never by title**, so a retitle needs *no* propagation into
  referring nodes — the new title surfaces at read time. There is **no rename-propagation problem**
  to solve for nested refs.
- **Save-time validation already recurses.** `_validate_list_field_value` builds each member as a
  plain field (`_group_member_as_field`, carrying `type` **and** `picker_config`) and recurses, so a
  nested `entity_ref` member is *already* validated against the index and the picker — reachable the
  moment §3 admits it.
- **The value editor already renders the ref picker inside a group row.** `ListValueEditor` →
  `FieldValueEditor` already dispatches `entity_ref` to the NodePicker/ReferencePicker. No
  value-editing UI change (a density tweak to `INLINE_MEMBER_TYPES` is cosmetic at most).
- **IO / normalization is already recursive** (`_normalise_metadata_value`), so a list-of-dict value
  round-trips to disk untouched.

### 6 — Additive: no migration

Existing projects have **no** nested refs (the schema forbade authoring one), so nothing on disk
changes shape and there is nothing to back-fill. This is a code-only change under ADR-0071's rule
(*migrate only when a missing migration breaks something*). A group that gains a ref member from here
on stores it in the shape §1 already reads.

## Scope

**In scope, sliced:**

1. **The traversal + the integrity core.** The metadata-ref visitor (read + rewrite forms), and the
   three integrity passes retrofitted onto it: index/backlinks, delete-purge, read-side dangling
   strip. Acceptance is the integrity traps (Acceptance) — this slice is what makes a nested ref
   *safe*, independent of whether the gate is open.
2. **Title resolution + open the gate.** `_resolve_reference_titles` onto the visitor; widen the
   backend/TS type catalogs, validation, and the `shapeableGroups` UI filter. After this slice a
   user can author a group with a ref member and see it resolve, backlink, and scrub.
3. **Tags + adjacency parity (§4).** Tag canonicalise/rename descend; the AI-context, promotion, and
   lore-mutation walkers consume the read visitor. Finishes the uniformity so no pass is an
   exception.

**Out of scope — deferred with the reason:**

- **Member-level backlink granularity.** A `ReferenceEdge` is keyed `(src, dst, field_id)`; a nested
  ref collapses onto the list field's `field_id`. Distinguishing *which member* of *which item*
  backlinks is a richer graph than the "does A reference B?" the graph answers today — deferred
  until a consumer needs it, so the edge stays field-keyed.
- **A typed Pydantic model for group values.** Node metadata stays `dict[str, Any]`; the visitor
  interprets it against the schema. Introducing a typed model is a separate, larger change and not
  needed for the invariant.
- **Groups nested in groups / deeper shapes.** The model permits one level (list-of-item_group); the
  traversal handles exactly that. Arbitrary nesting is neither supported today nor added here.

## Alternatives considered

- **Keep the restriction and document it in an ADR** (the "record the decision properly" reading of
  #1711). Rejected, and it is the load-bearing rejection: the restriction is not a sound boundary to
  record — it is an inconsistency in the user-facing model (a container that rejects three field
  types) standing in for an incomplete implementation (healers that only walk top-level). Writing it
  into ADR-0048 would enshrine a wart the user must remember. *Invariants, not defenses*: fix the
  invariant, delete the defense.
- **Teach each of the passes to descend, independently.** The obvious implementation, and the wrong
  one. It is six-plus parallel edits (index, purge, heal, resolve-title, tag-canon, tag-rename, AI
  context, promotion…), and each is a fresh chance to forget the nested case — which re-creates the
  precise silent-mis-link the restriction was avoiding, now spread across passes instead of blocked
  at the gate. *One traversal, not six*: define "at any depth" once and let every pass inherit it.
- **Admit only `entity_ref`/`entity_ref_list`, keep `tags` barred.** Smaller (skips the tag
  canonicalise/rename descent, §4). Rejected as the primary path because it leaves *a* carve-out —
  the user still has to remember "groups hold refs now, but not tags", which is the same class of
  inconsistency in a smaller box. Kept as the explicit fallback line if the tag-path surface proves
  larger than its worth at implementation.
- **A restricted "reference group" that only the reference lifecycle knows about.** A special group
  subtype carrying refs, distinct from ordinary groups. Rejected: it re-introduces the exception as a
  *type* instead of a *rule*, and it is the "special-case to hide a general gap" smell — the general
  mechanism (any group holds any field) is simpler and is what a user would expect.

## Consequences

- One new shared traversal becomes the single definition of "where references live in metadata";
  the four integrity passes (and the adjacency passes) shrink to *what to do per occurrence*,
  removing four-plus re-derivations of the same top-level walk. Net: less code, one invariant.
- Groups become a uniform container — any field type, no exception the user must remember. A
  "relationship" group `{target: entity_ref, kind: select}` and similar relational shapes become
  authorable through the ordinary public schema surface ("could a user author this" → yes).
- The reference graph gains edges it did not have (nested refs), keyed at field granularity;
  backlinks, dangling-scrub, and delete-purge all cover them.
- No migration; no storage-shape change; the value-editor UI and save-validation are already ready
  (§5). The surface is concentrated in the backend lifecycle passes and the type-catalog widening.
- ADR-0079 §2's deferral is discharged: narration stayed top-level for independence, and if a future
  change wants an atomic `narration: {mode, character}` group, this ADR is the precondition it named.

## Acceptance

Service-level tests against a project with a character kind and a node whose schema has a
`list`-of-`item_group` field with an `entity_ref` member (and, for slice 3, a `tags` member).
Red-first; ★ marks the traps a plausible wrong implementation slips through.

**Slice 1 — the integrity core:**

1. **★ Delete scrubs a nested ref.** A group member references character C; deleting C removes/blanks
   that nested ref on every referring node. A top-level-only purge leaves it — a silent mis-link —
   so this is the mutation-critical test.
2. **★ Backlinks find a nested ref.** C's backlinks include the node whose *group member* references
   it; the reference graph has the edge. (A top-level-only index yields no edge.)
3. **Read heals a nested dangling ref.** With the index rebuilt to exclude a since-deleted target, a
   read hides the nested dangling ref exactly as it hides a top-level one.
4. **Rewrite is in place and total.** After purge/heal, the group's *other* members and the *other*
   items in the list are byte-for-byte unchanged; only the matched ref value changed.

**Slice 2 — resolve + gate:**

5. A nested ref resolves to its target's **title**, not a raw id, wherever top-level refs do.
6. **The gate is open and still validates.** A schema defining a group with an `entity_ref` member
   saves without the item-shape error; a group member referencing a **non-existent** node still fails
   validation (the recursion §5 notes reaches the nested member).
7. The schema-authoring UI offers a ref-member group as an item shape (the `shapeableGroups` filter
   admits it).

**Slice 3 — tags + parity:**

8. A `tags` member inside a group is canonicalised/registered on save and rewritten on a tag rename,
   as a top-level `tags` field is.
9. A nested ref reaches the **AI context** and survives **promotion** (the adjacency passes descend).

## To verify / build at implementation

- **The occurrence/location representation.** Decide what the rewrite visitor yields so a caller
  mutates in place without re-walking — most naturally `(container, key)` for a scalar member and the
  list object itself for an `entity_ref_list` member — and confirm it round-trips through
  `_normalise_metadata_value` and disk IO unchanged.
- **`entity_ref_list` nesting.** The value is a *list of ids inside a map inside a list*; the visitor
  and both purge/heal rewrites must handle the doubly-nested shape, not just the scalar member.
- **Edge keying.** Confirm collapsing nested edges onto the list field's `field_id` is acceptable for
  every current `edges_by_src`/`edges_by_dst` consumer (backlinks UI, dangling detection); if any
  needs member granularity, that is the deferred richer graph, not this ADR.
- **Tags scope decision (§4).** Settle include-vs-defer `tags` at approval; if included, enumerate the
  canonicalise/register and rename (document + assistant-tag) paths that must descend.
- **The scalar-sugar `item_type` question (§3).** Decide whether `item_type: entity_ref` (a bare
  single-ref list, no named member) is in scope or whether refs enter only through named `item_group`
  members — the former also widens the `ListItemScalarType` Literal.
- **Adjacency inventory.** Before slice 3, re-list the top-level ref/tag walkers against the pinned
  commit (the AI-context and promotion sites drift), so parity is measured, not assumed.
