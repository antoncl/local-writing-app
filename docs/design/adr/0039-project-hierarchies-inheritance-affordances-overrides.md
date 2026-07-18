# ADR-0039: Project hierarchies — inheritance by folder depth, three edit affordances, per-field cross-layer overrides

- Status: **Proposed** — 0.7.0 planning, 2026-07-16 (under review, not accepted)
- Feature: #7 (epic) full project hierarchies · Companion: ADR-0040 (index/persistence) · Amends: ADR-0005
- Governed by: `memory/project_overview.md` (files-are-truth), the layered-schema pattern already shipped

## Decision

**A project is any folder containing `project.yaml`** (the manifest). Nesting is implicit by
filesystem — no `children/` wrapper. `project.md` is a *separate* thing: the singleton **project
node** (kind `project`, the level's own metadata + blurb). A flat project is a chain of length one.
*(This corrects the pre-1.0 design memo, which conflated the two as `project.md`.)*

**Inheritance is by folder depth, N levels, with no hardcoded tier names.** "Universe / series /
book" are *conventions the user expresses by nesting depth*, never types the app knows. The additive
merge already used for metadata schemas and the node index — lore, prompts, assistants, mutation
sets, views, research notes are collected across every ancestor layer, descendant overriding
ancestor on id collision — **is** the inheritance model. Scenes stay **book-scoped** (not inherited).
Most of this machinery exists (`_project_layer_folders`, `_build_node_index`); #7 completes and
surfaces it.

**Visibility is ancestor-only.** A descendant sees its ancestor chain; it never sees siblings.
Opening Book 12 pulls its universe + series canon, not the *other* universes on the shelf. This
bounds a session's working set to one root-to-leaf chain regardless of total shelf size.

**Opening is level-agnostic.** You can open at any level:
- a **leaf** (book) → merged canon + its manuscript;
- a **non-leaf** (universe/series) → merged canon + a **child-project roster**, and **no manuscript
  pane** (manuscript is book-scoped). Same session shell in both cases — a universe is just a project
  whose scenes folder is empty. A breadcrumb / level switcher walks the chain.

**Three edit affordances** for a shared (ancestor-owned) node, matched to three genuinely different
author intents:

1. **Direct edit** → writes the *owning layer's* file; visible everywhere downstream. The common
   case: correcting or enriching canon. One canon. No guard beyond a provenance tell.
2. **Per-field override** → a sparse, layer-scoped overlay on specific fields; the base entry is
   untouched. This is the **mutation model hoisted one tier**: resolved in the *same* `effective_state`
   engine as scene mutations, one level up. Resolution order:
   `universe base → series override → book-start override → scene mutations → effective`.
   Solves cross-book continuity (Honor is Commodore in the series base, a Captain by Book 12) without
   forking or walking prior books.
3. **Fork** → copy the whole node down to the current level; independent from here. For
   alternate-timeline / what-if books. Explicit, coarse, rare.

**Provenance (owning level) is a first-class attribute** of every resolved node, surfaced on two
complementary surfaces (the app has no per-pane edit/drag bar): a **level pill on the NodeRow** in
lists, and — when an entry is open for editing — a **layer treatment on the metadata fields rail**
(background color + an owning-level indication in the rail's title bar), since the rail is where an
edit that reaches an ancestor most needs to be visible. Provenance also supplies the override
resolution keys and the fork target; it rides the index's `level` field (ADR-0040).

**Unresolved — the fork-vs-direct-edit affordance.** *How* the author chooses between "edit the
ancestor's canon" and "fork a local copy" (and where per-field override sits between them) is **not
settled by this ADR**. It must be designed together with the incoming **mutation edit-in-place** work
— override, fork, and mutating-a-field-in-place are three edits to the same node surface and need one
coherent gesture vocabulary, not three bolted-on controls. Flagged as an open question below.

## Why / rejected alternatives

- **Fixed three-tier types (universe/series/book).** Rejected: David Weber — the stated worst case —
  has *multiple* universes (Honorverse, Safehold, …) with an author grouping above them; depth is
  open-ended. Folder depth + a field-valued `project` node already expresses any shape, and the code
  already layers by depth, not by named tier.
- **Auto-shadow on edit** (silently write a per-book copy whenever you edit a shared entry).
  Rejected: it forks canon into N drifting versions on every casual edit — the exact consistency bug
  nesting exists to prevent. Direct-edit keeps a single canon; divergence must be *explicit* (override
  or fork).
- **Whole-node override granularity.** Rejected in favour of **per-field** (confirmed): it matches
  scene mutations, and it keeps overrides *sparse* — a book overrides the handful of fields that
  actually diverge, not whole entries. At Weber scale, coarse copy-down would duplicate thousands of
  canonical entries; sparse overrides keep the universe layer single-sourced (and, per the AI
  strategy, the most cache-stable prompt block).
- **Cross-book resolution by walking all prior books / implicit carry-forward.** Rejected already in
  ADR-0005 (too expensive / too magical). The book (or series) stays the declared resolution
  boundary; the author states divergence explicitly at that boundary via an override.

## Consequences

- **Amends ADR-0005.** It deferred `book_start_overrides` and promised the slot would return "as an
  additional resolution layer *below* mutations, not a resolver rework." This ADR redeems that: the
  per-field cross-layer override *is* that layer. `base → series → book-start → mutations → effective`
  — an added layer, not a rework. The `effective_state` resolver becomes the shared engine for both
  scene mutations and layer overrides.
- **Settings / AI-policy resolution must extend to the chain.** Today AI settings read only the open
  project's own `project.yaml`; they must resolve `system → universe → series → book → prompt` over
  the same layer walk.
- **Index/persistence is ADR-0040 and is a prerequisite** — cold-open of a deep chain is multi-second
  (measured: 3.5 s / 7.0 s to parse one book's chain at Weber / huge scale), so the persisted
  incremental index must land with, not after, hierarchies.
- **The `project` node stays a per-folder singleton** but now participates in navigation (the child
  roster). Same `ProjectNode` model represents universe/series/book by field values — no new kind.
- **Candidate slices for #7** (issues cut separately, sequencing TBD): **A** discover ancestor chain +
  children in the open flow / `ProjectInfo`; **B** open a non-leaf level (canon + child roster, no
  manuscript); **C** frontend breadcrumb / level switcher; **D** provenance surfacing + direct-edit
  tell + fork-to-here; **E** the per-field override tier on the `effective_state` chain; **F**
  settings/AI-policy chain resolution.
- **Explicitly deferred (future, out of 0.7.0):**
  - **Promote-upward** — move a node to an ancestor level (symmetric to fork-down).
  - **Time/position-sensitive views (à la ADR-0013).** The general answer to "which scope does a
    backlinks/`References`/Nest surface resolve effective edges for" is a resolution-position
    dimension on *views themselves* — a view's effective-overlay analogue of the time-travel-aware
    lore card. 0.7.0 resolves effective edges only through the *existing* resolution-position
    mechanism (manuscript context); a general time-aware view dimension waits.
  - **Series/cross-book mutation collation.** Auto-rolling the prior book's accumulated mutations
    into the next book's opening override set (the "compute end-state of Book 11, seed Book 12"
    affordance). 0.7.0 authors book-start overrides **explicitly** — consistent with ADR-0005's
    book-as-declared-boundary; the roll-up automation is a later convenience on top.
- **Open question — the fork/override/direct-edit gesture.** The *model* (three affordances) is
  decided; the *UX* to select among them is not, and must be co-designed with **mutation
  edit-in-place** so a single node surface offers one coherent way to (a) correct canon, (b) override
  a field for this layer, (c) fork the node — not three unrelated affordances. This is design work
  that gates slices **D** and **E**.
- **The override tier (E) is in scope for 0.7.0.** Mutating an inherited lore entry — per-field,
  layer-scoped — is a release requirement, not a fast-follow.
- **Hard case — overriding a *reference-typed* field.** An override (or scene mutation) on an
  `entity_ref*` field changes the *effective edge graph* for that scope, which the base edge cache
  (ADR-0040) does not model. Direction: the cache stays at base/stored edges; **effective edges =
  base + a resolved override/mutation delta for the active scope**, exactly parallel to
  `effective_state` for values — so a reference override does *not* invalidate the global edge index,
  it layers a sparse delta on top. This is not new to layer overrides (scene mutations can already
  re-point a ref, and today's edge index reflects base values only); overrides make it first-class.
  The open sub-problem is consumer **context** — a backlinks / `References` / Nest surface must know
  *which* resolution scope it renders "effective" for. Needs its own design pass within E.
