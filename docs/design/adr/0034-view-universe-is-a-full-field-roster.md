# ADR-0034: The view universe is a full-field roster

- Status: Accepted — 0.7.0, 2026-07-09 (design agreed; **Draft roster path resolved to (a) enrich**);
  accepted 2026-07-10 (5 context-blind gates)
- Feature: #184 Parameterized views — a **prerequisite** for the forward model · relates #182
  (render wrapper), #112 (Draft presentation)
- Follows: ADR-0025 (views evaluate frontend-side, over an in-memory roster), ADR-0031 (forward
  `Filter`/`field_of` presuppose the field is in the roster)
- Governed by: `memory/decisions_view_render_pipeline_ownership.md`

## Context
The evaluator is **roster-relative**: it never fetches, it operates on the `EvalNode[]` roster the
call site hands it (ADR-0025), and it can only reference **fields present in that roster**
(`fieldValue` reads `node.metadata[key]` / the node top-level for intrinsics).

The **Draft / manuscript** pane hands it a **deliberately thin** roster. `structureToEvalNodes`
builds each node as `{ id, entry_type, title, metadata: computed_metadata, ancestry }`, and
`computed_metadata` on a structure node is **only computed counter fields** — `status`/`color` are
surfaced onto separate top-level fields for stripe rendering, explicitly *"without per-row file
reads."* So at the Draft call site an `entity_ref` field like `pov_ref` **is absent entirely**, and
even `status` is not where the predicate looks.

The forward model (ADR-0031) predicates and projects on fields; on the thin Draft roster there is
nothing to predicate. So a Draft membership view ("scenes where Bob is POV and status is draft")
cannot be expressed — **not because the grammar lacks it, but because the universe lacks the data.**
This is a data-availability decision, and it is the gate under all of #184's Draft-facing value.

## Decision
**A view evaluates against a full-field roster** — every node in the universe carries its **complete
resolved field set** (stored + intrinsic + computed, including `entity_ref` fields), not a
presentation-thinned projection. `All` over such a roster is a universe the forward model can
actually filter and project.

**For the manuscript/Draft pane specifically — DECIDED (2026-07-09): (a) enrich the structure
roster.** Inject the full resolved metadata into each structure node, so the Draft view evaluates in
**one pass** over one roster carrying *both* ancestry (for tree presentation) and full metadata (for
POV/status predicates) → a single `ViewResult` (membership + presentation) for the #182 wrapper. This
also **solves #112** (the view drives flat/grouped/tree). Perf is **bounded**: the structure build
already reads each scene's front-matter for status/color (`manuscript.py`), so widening that to full
metadata is incremental — not a new per-row read pass. (Build note: `status` is stored top-level on a
scene, but the evaluator reads non-intrinsic fields from `metadata`, so enrichment must land it at
`metadata.status`.)

- **Rejected: (b) two rosters, evaluate-rich / project-thin** — evaluate membership over the full
  node index → an id-set → tint/prune the thin structure tree. It keeps the structure roster thin,
  but **splits** membership from presentation into two evals + a recombine, fighting the single
  `ViewResult` that #181/#182 just unified. The enrichment (a) pays is bounded and largely already
  incurred; the split (b) adds is permanent.

**Roster completeness — full membership per referenced kind, not just full fields per node.**
Kind-relative complement (ADR-0031 §I) needs *all* nodes of the complemented kind, and cross-kind
projection (`field_of(scenes, pov)`) needs both source and target kinds present — so a roster must be
**complete within every kind the view references**, or a complement silently under-counts. By pane
type:
- **Anchored (`$self`) pane** (an editor): the roster must contain the **complete set of `$self`'s
  kind K** (so self-relative queries — "other characters", complement against `$self` — are
  well-defined), plus any kind a `field_of` **projects into** directly. **Reference traversal
  (`references`/backlinks) does NOT go through this roster** — it uses the **shared cross-kind
  reference index** (`views-and-filters.md` §14.4), so the pane need not roster every kind that might
  reference `$self`. The (a)/(b) choice does not apply to anchored panes.
- **Roster pane, full-index kinds** (lore, assistants, prompts — no `$self`): these evaluate directly
  against their kind's **full node index**, which already carries complete metadata — no enrichment
  needed. *(There is no separate scenes-roster pane — scenes live in the Draft/manuscript Tree below.)*
- **The Draft/manuscript Tree** is the `kind: scene` surface (acts/chapters/scenes by entry_type,
  until the #86 kind rename). Its thin structure roster is **enriched to full metadata (path (a),
  decided above)**, so **scene POV/status filtering ships in this release** — one eval over the
  enriched roster, presentation-driven (#112 / #182).

## Why / rejected alternatives
- **Keeping the thin structure roster as the view's universe — rejected.** It cannot carry the
  fields the forward model matches on; membership views over the Draft become inexpressible.
- **Fetching fields on demand during eval — rejected.** Per-field round-trips break the
  frontend-side, in-memory purity of ADR-0025 and couple evaluation to network latency.

## Consequences
- **The forward model becomes expressible on the Draft pane** — the last gate under #184's
  Draft-facing use.
- **The `references` reverse index (ADR-0031 §G)** is a shared frontend structure built from a
  **load-time cross-kind reference-graph payload** (ids + forward ref-target-ids — *not* the per-pane
  filtering rosters), the same inversion Nest performs; **specified in `views-and-filters.md` §14.4**
  (in scope for this release).
- **The #182 wrapper takes one enriched roster** for the Draft pane — a single membership+presentation
  `ViewResult`; no two-roster split (that was the rejected (b)).
- **Enrichment cost is bounded** — the structure build already reads scene front-matter for
  status/color; widening it to full metadata is incremental, and should stay well within the
  evaluator's ample frame budget (§2.1). Confirm with a measurement during build.
- **Out of scope**: the concrete wire shape of the (a) enrichment (an implementation detail). The
  `references` reverse index is sketched in `views-and-filters.md` §14.4.
