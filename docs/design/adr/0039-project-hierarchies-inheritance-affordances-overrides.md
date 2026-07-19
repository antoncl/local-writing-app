# ADR-0039: Project hierarchies — inheritance is virtual membership; three edit affordances; per-field layer overrides

- Status: **Accepted** — 0.7.0, 2026-07-19 (PR #319) · rewritten 2026-07-19 after two rounds of
  adversarial review · **Amendment 1: inheritance is declared, not inferred**
- Feature: #7 (epic) full project hierarchies
- Companion: ADR-0040 (the index — which *materializes* the chain, not merely caches it)
- Amends: ADR-0013 (see its Amendment 1) · Gesture UX: **ADR-0042** (co-designed with mutation
  edit-in-place) · Provenance mark: **#304**
- Governed by: files-are-truth; the layered metadata schema already shipped

## Context

The layering machinery largely exists. `_project_layer_folders` (`schema.py:887-900`) walks the
ancestor chain, and `_build_node_index` (`references.py:46-72`) already collects lore, prompts,
assistants, mutation sets, views and research across every layer — descendant winning on id collision
(`references.py:216-230`) — while scenes stay book-scoped (`references.py:70-72`). What is missing is
navigation, the edit story for an inherited node, and settings resolution.

An earlier draft of this ADR framed per-field overrides as a new tier inside the `effective_state`
resolver, "one level up" from scene mutations, and claimed to redeem a deferred slot from ADR-0005.
That framing was wrong in a way worth recording, because it drove several downstream errors: see
*Why / rejected alternatives*.

## Decision

**A project is any folder containing `project.yaml`** (the manifest). Projects nest by filesystem
placement — no `children/` wrapper — though *which* ancestors a project inherits from is **declared**,
not inferred from that placement (Amendment 1). `project.md` is a *separate* thing: the singleton **project
node** (kind `project`, the level's own metadata + blurb). A flat project is a chain of length one.
*(This corrects the pre-1.0 design memo, which conflated the two as `project.md`.)*

> **⚠ Superseded by Amendment 1 below.** This ADR originally made `project.yaml` the *layering*
> marker, inferring the chain from folder placement. Amendment 1 replaces that with an explicit
> declaration. `project.yaml` still marks an **openable project**; it no longer decides what is
> inherited.

**Inheritance runs up the declared ancestry, N levels, with no hardcoded tier names.** "Universe /
series / book" are *conventions the user expresses by nesting depth*, never types the app knows. Lore, prompts,
assistants, mutation sets, views and research notes are collected across every ancestor layer,
descendant overriding ancestor on id collision. Scenes stay **book-scoped** (see below).

**Visibility is ancestor-only.** A descendant sees its ancestor chain; it never sees siblings. Opening
Book 12 pulls its universe + series canon, not the *other* universes on the shelf. This bounds a
session's working set to one root-to-leaf chain regardless of total shelf size.

**Scenes stay book-scoped** (not inherited) — the one kind that does not layer. The reason, so a later
pass does not "unify" it: a scene's identity is its position in *one* manuscript
(`manuscript.structure.yaml` is per-book, and `effective_state` resolves against that book's
`scene_order`), so an inherited scene would have no defined position in the inheriting book. A shared
prologue or series-level interlude is therefore not merely unimplemented — it needs a manuscript model
that admits a scene appearing at a position in more than one book.

**Opening is level-agnostic.** A **leaf** (book) opens to merged canon + its manuscript; a **non-leaf**
(universe/series) opens to merged canon + a **child-project roster**, with **no manuscript pane**
(manuscript is book-scoped). Same session shell in both cases — a universe is just a project whose
scenes folder is empty. A breadcrumb / level switcher walks the chain.

### Inheritance is virtual membership

An ancestor-owned node is **pulled into the open project as a member** — materialized through the
node index (ADR-0040), which resolves the chain into the member set this project sees. Inheritance is
not a lookup that happens later; it is what the index *produces*.

This is the load-bearing frame, and three things follow from it:

- **A layer override is not a resolution tier.** It is the consuming layer's sparse delta on a
  pulled-in node, applied **at materialization**. The result *is* the base that the open project sees.
- **Scene mutations are untouched.** They run on that base exactly as they always have, keyed by
  manuscript position. Resolution is `materialize(chain) → base`, then `base → mutations → effective`.
- **There is exactly one layer scope per open project** — the project you have open. "Which scope does
  this surface resolve for?" has one answer, so it is not an open question (see *Consequences*).

> **Terminology.** This ADR says **layer override** (or *layer delta*), never bare "field override".
> `field_overrides` is already taken: `models/schema.py:252` uses it for ADR-0029's per-entry-type
> `{label, hidden}` *presentation* overrides, an unrelated concept. Grepping the wrong one wires layer
> deltas into the schema machinery.

**Where the fold happens — concretely.** The index does *not* hold field values (`NodeIndexEntry` is
`(path, kind, entry_type, title, layer rank)`; ADR-0040 keeps it that way, and a metadata-carrying
index would break its change-gate and turn the snapshot into a field store). So the fold applies in
two places, from one shared helper:

- **Values** fold on read — `read_lore_entry` / `list_lore_entries` gather the target's overrides
  across the chain and apply them.
- **Edges** fold during index build — `_forward_refs_for_entry` already re-reads front matter to
  extract refs; it applies the same delta *before* extracting. So the index holds **effective** edges
  without holding metadata, and backlinks / `References` / Nest need no scope parameter and no
  query-time delta.

A consequence for the change-gate (ADR-0040): a write to an override file must be gated against its
**target**, not against itself.

### Three edit affordances

For a shared (ancestor-owned) node, matched to three genuinely different author intents:

1. **Direct edit** → writes the *owning layer's* file; visible everywhere downstream. The common case:
   correcting or enriching canon. One canon.
2. **Per-field override** → a sparse, layer-scoped delta on specific fields; the base entry is
   untouched, and **un-overridden fields keep resolving against the live ancestor**, so later canon
   corrections still flow down. Solves cross-book continuity (Honor is Commodore in the series base, a
   Captain by Book 12) without forking or walking prior books.
3. **Fork** → copy the whole node down to the current level and **stop inheriting** from here. For
   alternate-timeline / what-if books. Explicit, coarse, rare.

Override and fork are distinguished by *inheritance*, not by granularity: an override stays linked to
its ancestor; a fork severs the link. That is why whole-node override is rejected as an *override*
granularity while fork — which is a whole-node copy — remains a distinct, useful affordance.

**A fork keeps the node's id.** For an alternate-timeline book it is the same entity rendered
differently, so inbound references from ancestor entries must resolve to the fork *within the forking
project*. ADR-0040's `id → [candidates by layer]` provides exactly that, with the ancestor still
reachable as a shadowed candidate. Front matter carries `forked_from`, which is what declares the
severance and what suppresses the index's existing shadow warning (`references.py:216-230`) — the
warning stays loud for *accidental* collisions.

`forked_from` records the **relative path from the base folder** to the owning layer, not a layer id.
The only layer identity in code is `sha256(str(folder.resolve()))[:16]` (`schema.py:912-913`), which
is machine- and location-dependent — persisting it into front matter breaks the moment the shelf is
moved, renamed, or opened on another machine, and "layer rank" is an ordinal within one chain, not a
durable identifier. A relative path survives all three.

**Glyph: unresolved, not settled.** `⧉` is in the lexicon as *"duplicate — fork the item into a new
editable copy"*, and the lexicon's governing rule is that a glyph earns its place *"only by meaning
the same thing everywhere"*. A fork here **keeps the id**, so it is not a duplicate — reusing `⧉`
would make it mean two things. Folded into **#304** with the other marks rather than asserted away.

### An override is a delta, built on the mutation structure

A layer override is a **body-less Node** under `overrides/`, carrying the **same op vocabulary as a
scene mutation** — set / add / remove — over the target's fields. One file per (layer, target).

**It reuses the mutation ops rather than inventing a second dialect**, and that is the point:
`_resolve_collection` (`lore_mutations.py:727-740`) already resolves multi-valued fields as
`(base ∪ adds) ∖ removes`. Without ops, an override could only *replace* a list — so adding one alias
would mean restating the whole list, after which later ancestor additions to that field silently stop
arriving. One collection rule in the codebase, and an author who already knows the vocabulary from
mid-scene mutations.

**Rejected: a sparse lore entry with the same id in the layer's own `lore/`.** Tempting — it needs no
new kind, no folder, and the shadow chain is already the fold input. But it makes a *delta*
impersonate a *node*: it cannot be read standalone, it fails `_validate_lore_entry_metadata` (which
validates a complete metadata dict), its sparseness is invisible without an out-of-band marker, and it
still cannot express add/remove on a multi-valued field. A delta should look like a delta.

**The join key is `target: <node-id>` in front matter — not the filename.** Filenames track the
*title*: `_filepath_for_new_node` sanitizes it, `_maybe_rename_node_file` renames on every title
change, and collisions get a `Name (2).md` suffix — so the same entity can have different filenames at
different layers even without a rename. `project_service.py:367` states the invariant: *"the on-disk
filename is cosmetic — the front-matter `id` is the canonical identity."* A filename join orphans
silently the first time an author retitles an entry.

**The override node's own id is `sha256(layer_id + target_id)`** — deterministic, distinct per layer
(so a series override and a book override of the same entry do not collide in the index), stable
across sessions, and needing no uniqueness registry. Overrides are filtered out of reference pickers
and view results; they are deltas, not pickable nodes.

**Composition across layers is descendant-wins per item** — deliberately *diverging* from the
mutation rule it otherwise copies. Mutations use remove-wins because two mutations at the same
manuscript position are genuinely unordered; layers are **totally ordered by rank**, so last-writer-
wins is available and is the intuitive reading — a book that re-adds an alias its series removed
should get it. Under remove-wins that case is inexpressible, and there is no migration between the two
rules once files exist. (ADR-0042 may still overturn this; it is the one override semantic that the
gesture work could reasonably revisit.)

### Provenance is first-class and must be visible

Every resolved node carries its **owning layer** (and, for a fork, its shadow stack). This supplies
the override resolution keys, the fork target, and the navigation surface — it rides the index's layer
rank (ADR-0040).

**An author must be able to see that a value is an override rather than authored canon**, and to tell
that apart from a *mutation*. Two surfaces carry it — a **level pill on the NodeRow** in lists, and a
**layer treatment on the metadata fields rail** when an entry is open, since the rail is where an edit
that reaches an ancestor most needs to be visible. The **form of the mark** — mutation glyph in another
colour, a different glyph, or a non-glyph treatment — is deliberately not settled here: the existing
mutation marker `⤳` is itself outside the closed glyph lexicon, so both marks enter it together under
**#304**. This ADR requires only that the tell exist and be distinct.

## Amendment 1 — inheritance is *declared*, over a filesystem-enumerated candidate list (2026-07-19)

The original decision inferred the chain from folder placement: walk to the base folder, and (per the
now-superseded blockquote above) treat every ancestor carrying a `project.yaml` as a layer. Review of
slice **A** showed that inference cannot answer two questions without guessing at author intent —
whether the marker also gates the *metadata-schema* walk, and whether a non-project ancestor
**breaks** the chain or is **skipped**. Both have defensible answers and opposite failure modes; under
"break", inserting an organizational folder mid-shelf silently removes a user's universe canon.

**The user declares it instead.** Two steps, in this order, and the order is the whole point:

1. **Enumerate candidates by walking the filesystem to the base folder.** Unchanged from today, and
   **finite by construction** — directory traversal terminates, so the candidate list is complete and
   cycle-free before anyone declares anything.
2. **The project records which of those enumerated ancestors it inherits from.** A declaration naming
   anything outside the enumeration is ignored with a warning; it cannot extend the walk.

Gaps are now legitimate rather than ambiguous — skipping `Shelf/Weber/` is a recorded choice, not an
inference the app has to make. This is the same principle the ADR already applies to node edits:
divergence must be explicit. Inferring an inheritance structure from where a folder happens to sit is
exactly the implicit magic that auto-shadow-on-edit is rejected for.

**Rejected: a `parent:` link resolved transitively.** Superficially cleaner — one field, chain by
transitivity, gaps free. But a link is *data in a user-editable file*, so `A → B → C → A` is reachable
by hand-editing `project.yaml`, and the app would need cycle detection on every chain resolution to
defend against a problem it introduced. Enumerate-then-declare cannot cycle, because the enumeration
is a directory walk. **Do not reintroduce transitive links to "simplify" the declaration** — the
finiteness is the feature.

**The change is contained.** `_project_layer_folders` still returns an ordered `list[Path]`; only its
body changes, from "every ancestor" to "the declared subset of every ancestor". Both consumers —
`_metadata_schema_layer_paths` and `_build_node_index` — enumerate that list and are untouched, as are
layer rank, candidate lists, and the ADR-0040 manifest. It also resolves the schema-walk question by
construction: one declared chain serves node inheritance *and* schema layering, so they cannot diverge.

**Where the declaration is made:** the create-project wizard, which presents the enumerated ancestors
and lets the author tick the ones to inherit from. Editable afterwards in project settings.

## Why / rejected alternatives

- **Overrides as a tier inside `effective_state`** (the earlier draft's central claim: an added layer
  `universe base → series → book-start → mutations`, "not a resolver rework"). **Rejected — the code
  contradicts it.** `effective_state(entity_id, scene_id, position, …)`
  (`lore_mutations.py:610-678`) keys on manuscript position exclusively and returns `{}` when the
  scene is not in `scene_order` (`:651-654`); its override corpus is built solely by scanning
  manuscript scene bodies (`:470-497`), ordered by `(manuscript position, prose offset)`. A layer
  override has no scene and no position, and a universe level has no manuscript at all — there is no
  coherent way for it to enter that ordering. Implementing it there would mean rewriting
  `_entity_base_values`, inventing a non-positional rank, and fixing up `_resolve_collection` /
  `_resolve_text_append` — precisely the resolver rework the claim denied. Folding at materialization
  keeps `effective_state` untouched.
- **Fixed three-tier types (universe/series/book).** Rejected: David Weber — the stated worst case —
  has *multiple* universes (Honorverse, Safehold, …) with an author grouping above them; depth is
  open-ended. Folder depth already expresses any shape, and the code layers by depth, not named tier.
- **Auto-shadow on edit** (silently write a per-book copy whenever you edit a shared entry). Rejected:
  it forks canon into N drifting versions on every casual edit — the exact consistency bug nesting
  exists to prevent. Divergence must be *explicit*.
- **Whole-node override granularity.** Rejected in favour of per-field: it keeps overrides *sparse* —
  a book overrides the handful of fields that actually diverge. At Weber scale, coarse copy-down would
  duplicate thousands of canonical entries; sparse overrides keep the ancestor layer single-sourced
  (and, per `memory/strategy_ai_integration.md`, the most cache-stable prompt block). Copy-down remains available
  deliberately, as **fork**.
- **A single `overrides.yaml` per layer.** Rejected: fewer files, but it needs bespoke merge, indexing
  and provenance code, against a Node-shaped alternative that needs none.

## Consequences

- **ADR-0005 is untouched — this ADR does not amend it.** 0005 decided *scoping*: the book is the
  resolution boundary, base is the lore file at book-start, cross-book walking is out of scope. All of
  that holds verbatim; the layer fold simply produces that book-start base. 0005's parenthetical guess
  at a future shape (`base → book_start_overrides → mutations`, storage on `project.md
  starting_state`) is **not adopted** — it predates hierarchies, puts overrides inside the resolver,
  and is the origin of the rejected framing above. `starting_state` exists nowhere in code and is not
  introduced.
- **ADR-0013 gains an amendment.** Its scrubber, discrete stops, stop-0-editability and total scope
  are unaffected — the layer axis has one value per open project and therefore does not scrub. What
  changes is that "base" at stop 0 is now a *resolved* state, so *which file* an edit at stop 0 writes
  to is no longer self-evident. That is the gesture question (ADR-0042). Recorded as Amendment 1 there.
- **The "which scope is effective?" question is dissolved, not deferred.** Because materialization
  yields one member set for the open project, effective **edges** for layer overrides are baked into
  that member set by the index — there is no scope parameter to thread through consumers, and no
  query-time delta for backlinks / `References` / Nest to apply. The split is clean: **layer overrides
  are position-independent and can be materialized; scene mutations are position-dependent and cannot**
  (they stay resolved at query time, as today).
- **Settings / AI-policy resolution must extend to the chain.** Today AI settings read only the open
  project's own `project.yaml`; they must resolve `system → …chain… → prompt` over the same layer walk.
- **`revision` must span the fold.** `read_lore_entry` returns `revision=self._revision(path)` — a hash
  of *one* file (`lore.py:116`). Once an entry is folded, editing an override leaves the ancestor's
  hash unchanged, so optimistic concurrency (`lore.py:129`) accepts a stale buffer **and** the AI
  prompt cache, which partitions stable/volatile blocks on `entry.revision`
  (`services/ai/helpers.py:746-767`), keeps serving pre-override canon. The revision must be composite
  over the ancestor file plus every override in the chain. Slice E owns it.
- **Saving an inherited entry must not write the fold upstream.** `save_lore_entry` resolves its path
  through `by_id[id].path` — the *ancestor's* file (`lore.py:125`). Left alone, opening an inherited-
  and-overridden entry and pressing save promotes every override into ancestor canon, downstream to
  every other book: the auto-shadow failure this ADR rejects, reached by not deciding. What a stop-0
  edit writes to is exactly the gesture question — **ADR-0042 (#308)** — which is why slice E is
  blocked rather than merely unscheduled. Until it lands, saving an inherited entry must fail loudly
  rather than silently choose a target.
- **ADR-0040 is a prerequisite** — on materialization grounds, not only latency. It is the mechanism
  this ADR's inheritance *is*. Its backend implementation is #305 → #306 → #307 (the last being the
  backend half #200 never landed, having closed 2026-07-19 with only the frontend change-gate).
- **The `project` node stays a per-folder singleton** but now participates in navigation (the child
  roster) and must be indexed — its id is the constant `"project"`, so it collides at every level of
  any chain unless identity is layer-qualified (ADR-0040). Same `ProjectNode` model represents
  universe/series/book by field values — no new kind.
- **Slices for #7**, cut to issues:

  | | slice | issue | status |
  |---|---|---|---|
  | **A** | declared inheritance (Amendment 1) + discover ancestor chain and children on `ProjectInfo` | #309 | after #306 |
  | **B** | open a non-leaf level (canon + child roster, no manuscript) | #310 | after A |
  | **C** | frontend breadcrumb / level switcher | #311 | after B |
  | **F** | settings / AI-policy chain resolution | #312 | ready, independent |
  | **D** | provenance surfacing (level pill + rail treatment) + fork-to-here | #313 | blocked |
  | **E** | layer overrides (`overrides/` deltas on the mutation structure) | #314 | blocked |

  **A** needs #306 first — the project node's id is the constant `"project"`, so it collides at every
  layer until identity is layer-qualified. **D** and **E** additionally need ADR-0042 (the gesture,
  #308) and the mark decision (#304). Index prerequisites: #305 (single-pass) → #306 (snapshot) →
  #307 (incremental + change-gate).
- **Explicitly deferred:**
  - **Promote-upward** — move a node to an ancestor level (symmetric to fork-down).
  - **Layer-scrubbing** — "show me this entry as the *series* sees it". Genuinely useful for provenance
    debugging, and ADR-0013's scrubber is the precedent, but it is the resolution-position-dimension-
    on-views item and belongs with Views 2.0.
  - **Series/cross-book mutation collation** — auto-rolling a book's accumulated mutations into the
    next book's opening override set. 0.7.0 authors overrides explicitly. *(0005 scoped cross-book
    walking out of v1 for lack of payoff; this is the deferred convenience on top, not a permanent
    rejection.)*
- **Overriding a `body` field.** ADR-0013's scope is deliberately total — title, body and every field
  travel. Overrides are per-field and body is a field, so a layer-level body override is expressible
  and lands on 0013's buffer-safe read-only body overlay. Permitted; slice E states the interaction.
