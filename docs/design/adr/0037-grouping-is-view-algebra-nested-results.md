# ADR-0037: Grouping is view algebra — `group_by` on the result, a row-preserving pipeline, and the end of `ViewPresentation`

- Status: Proposed — 0.7.0, 2026-07-12
- Feature: #213 (0.7.0 release blocker). Removes the last sibling of the null-view hack: grouping
  imposed pane-side behind a `presentation` switch. Settles the fork ADR-0036 §3 deferred (the
  manuscript tree's spec form) and resolves #112's original ask (strip/flatten manuscript levels) by
  construction. #212 was the visible symptom.
- Follows: ADR-0018 (set algebra), ADR-0019 (annotate dissolves grouping — grouping is structural,
  not annotation), ADR-0027 (**the denormalized set model** — named handles as path segments; §E
  `nodes` = membership / `groups` = presentation), ADR-0028 (Nest — ν by join; diagnostics, guards),
  ADR-0031 (forward model; §D payloads; the computed `References` node-set field — the precedent §4
  reuses), ADR-0034 (full-field roster), ADR-0035 (a view's output is one `ViewResult<T>`),
  ADR-0036 (explicit defaults; empty view = empty set)
- Governed by: `memory/decisions_036_implicit_explicit_views.md`,
  `memory/decisions_views_2_0_flow_model.md` (concat/stacking stays deferred),
  `memory/decisions_view_trees_are_path_denormalization.md` (#101)

## Context

**The hack.** ADR-0036 killed null-*expr* (an unspecified view no longer means "everything"). Its
sibling survives one level up: an unspecified *presentation* still means "the pane decides the
shape." `intrinsicDisplayResult` (`Lore.svelte:115`, `Assistants.svelte:73`) takes a view whose
evaluation produced **no groups** and — unless `presentation === "flat"` — synthesizes buckets the
view never expressed (by `entry_type`; by `source_layer`). Two panes render the *same spec*
differently; the view is not authoritative for its own shape; and the default reaches its grouping
via a **null** presentation — the unspecified case getting special treatment, again. Duplicating a
default view therefore changes its rendering (#212): the copy faithfully renders the stored
`"flat"`, which never matched the grouped original.

**Why it exists.** The grammar has only **static** grouping — `ViewSpec.groups` is a hand-enumerated
list of named handles (ADR-0027 §D). There is no dynamic partition ("one bucket per distinct value
of `entry_type`"), so the dynamic default grouping was synthesized pane-side and gated on an enum,
`ViewPresentation = "tree" | "grouped" | "flat"` (`types.ts:417`, `models_views.py`), that conflates
a genuine layout choice (`"tree"`) with a grouping decision that belongs to the view.

**The lens (RASMUS / NF²).** The view designer's ancestor is RASMUS, a relational language whose
algebra is *closed* over its values. In nested-relational (NF²) terms our machinery is already
half-built: a `ViewGroup` with `children` is a relation-valued attribute (`evaluateView.ts:97`); the
`(node, path)` row (`:87`) is the nested relation in **denormalized** form; `normalize`/`buildLevel`
(`:446`/`:514`) is the physical constructor. Nest is ν by join. What's missing is ν by attribute —
and the discipline of keeping σ inside the algebra instead of leaking shape decisions to panes.

## Decision

### 1. Exactly two nesting operators; the result conforms, never imposes
- **Nest** (pipeline) — ν **by join**: hierarchy from a *relation* (links), recursive form =
  fixpoint. Already shipped (ADR-0028). It remains the only hierarchy-maker.
- **`group_by`** (result) — ν **by attribute**: partition by a *field*. New, on the spec (§2).

`ViewNodeList` renders whatever shape the `ViewResult` carries — flat when `groups: null`, nested
when not. **No renderer or pane ever synthesizes grouping.** `intrinsicDisplayResult` (both panes)
and the #208 `groupBy` helper (`lib/views/viewResult.ts`) are deleted.

> **Amended by [Amendment 1](#amendment-1--organize-is-per-group-2026-07-12): Organize is per-group,
> not result-level.** §2 below describes the single/unnamed-group case, which is unchanged; per-group
> Organize is additive. Read the amendment first.

### 2. `ViewSpec.group_by` — ordered organize levels
```ts
group_by?: Array<{ field: string; order?: "label" }>;
```
Orthogonal to `expr`/`groups` (the XOR at `models_views.py:273` is untouched; handles compose with
levels). Evaluation is one rule: **after the pipeline produces rows, each level appends one path
segment above the leaf, in declared order, beneath every pipeline-produced segment** (handles
prepend outermost as today, `evaluateView.ts:422`; Nest/inherited-`view_ref` segments are inherent
to the rows). Then the existing `normalize` runs unchanged. Placement is **innermost**; a dynamic
*outer* partition of an already-nested result is deferred (§Rejected).

Per-field segment semantics (`segmentForField`, the only genuinely new evaluator logic):

| field kind | bucket | label | `nodeId` |
|---|---|---|---|
| enum / select | one per option value | option label | `null` (synthetic) |
| `entry_type` (intrinsic) | one per type | type display name | `null` |
| **reference field** | one per target node | target title | **target id** — a real-node, openable header (tree-uniformity for free) |
| multi-valued (tags, multi-ref) | row appears under **each** value | per value | as above |
| missing / unset | none — the row stays **bare at that level**, interleaved beside the buckets (`buildLevel` already renders container/leaf siblings in one ordered list) | — | — |

A reference-field level is single-level relational grouping *via dropdown* — Nest is only ever
needed for recursion. Bucket **order** = first-seen in row order (the `buildLevel` rule, `:509`), so
the view's sort also orders buckets; `order: "label"` opts into alphabetical. Membership invariant
unchanged (ADR-0027 §E): `groups` may repeat a node, `nodes` dedupes.

### 3. `ViewPresentation` is eradicated
The enum, the spec field (`types.ts:413`), the node/summary/request fields (`models_views.py:480`,
`:501`, `:521`, `:530`), the storage blob + `_view_presentation` parse, `paneViews.presentationFor`
(`:139`), the panes' `presentation` props, the designer's hidden presentation state
(`ViewBodyView.svelte:95`), and the `spec.presentation === "tree"` branch (`evaluateView.ts:322`)
**all go**. Flat is not a mode; it is the absence of declared or produced grouping. `"tree"`
survives *only* as `NodeList mode="card" | "tree"` — row styling, pane chrome, presentation-only
(functionality uniform across modes, per the standing rule).

### 4. Containment is a relation; the manuscript tree is a Nest
`manuscript.structure.yaml` / research's tree are a **materialized index of a containment
relation** — `(parent, child, rank)` — not a third kind of grouping. Containment is exposed as an
intrinsic **computed reference field** (`parent` / `children`), exactly the ADR-0031 `References`
precedent: the structure file is merely the field's current backing. When the structure files are
later removed (containment stored as real references), the backing swaps and **the spec does not
change shape**. Roots are not magic: `field: parent unset`.

The Draft/Research default becomes `nest(match: contained_in, recursive: true)` — settling the fork
ADR-0036 §3 deferred, *toward* Nest. The evaluator MAY recognize the containment match and evaluate
it via the existing ancestry machinery (`structureToEvalNodes` + path append): that is an
**evaluation strategy**, not a grammar special case — the ancestry pass already produces exactly
this nested relation. A rejected alternative, `group_by: [{structure: true}]`, is recorded in
§Rejected: it would have baked a dying storage artifact into the grammar's public vocabulary.

### 5. The pipeline downstream of a row-producer is **row-preserving**
Today only a *bare* Nest (or union) keeps its rows; an operand buried in the set algebra flattens
through `evalExpr` to its placed id-set (`evalSource`, `evaluateView.ts:364-367`, `:395`). That
discards precisely what the denormalized form is for. **No grammar change** — an evaluation-
semantics change:

- **σ** (Filter lowers to `intersect`/`difference` with a predicate) over rows = **leaf test, path
  carried**. A scene row `(scene, [act, chapter])` passes on its own status; the chapter is
  **revived from the path** by `normalize` (ancestor segments materialize from surviving rows);
  branches no surviving row mentions self-prune. "Keep a match's ancestors, prune empty branches"
  stops being a tree-presentation special case and becomes a theorem of σ∘ν on the denormalized
  form.
- **∩ / −** with a node-set operand = leaf-*membership* σ (same rule).
- **∪** = the path-preserving concat that already exists (`:382`).
- Two row-producing operands in one combinator: the **first** carries structure; others degrade to
  their membership (today's behavior, now stated).

**Wiring is the semantics — no modes.** Filter wired *into* Nest's children participates in the
join (chain-sensitive; occasionally wanted). Filter wired *after* Nest filters members and revives
ancestors (the intuitive reading, and the Draft case: `nest(contained_in) → filter(status)`). The
"context vs member" Nest mode considered during design is **unnecessary** — the distinction is
emergent from evaluation order.

### 6. Segment provenance replaces the `treePresentation` flag
`PathSegment` (`evaluateView.ts:82`) gains an origin: `handle` | `field` (a §2 level) | placed
(Nest-placed real node) | `revived` (an ancestor that did not itself pass selection). Two
formerly-global behaviors become per-segment rules:
- **Membership is σ-passage** *(sharpened while writing the conformance suite)*: a node is a member
  iff **it itself passes the view's selection** — surviving leaf rows, plus placed segments whose
  node passes any downstream σ (vacuously, all of them when there is no σ). A segment node that
  fails σ is demoted to `revived` — **context**: excluded from flat `nodes`, rendered as
  scaffolding. One rule reproduces both current behaviors: an unfiltered Nest's parents are members
  (they pass vacuously, `:463-469`); a status-filtered Draft tree's acts/chapters are context (they
  carry no status). **`field`-origin headers are never members** — a reference-field bucket's
  target arrived as a *value* the algebra surfaced (ADR-0031 §D), not as a member; Paris-the-bucket
  is not in the view just because characters were grouped by it.
- **Collapse-to-flat:** `normalize`'s "lone synthetic bucket → flat" rules (`:484-501`) apply to
  `handle` segments **only**. A declared `group_by` always shows its headers, one bucket included —
  otherwise a Lore project holding only characters silently loses its "Character" header on day one.

### 7. The defaults become honest views (equivalence per ADR-0036 §3's audit discipline)
| default | spec |
|---|---|
| Lore | `descendants_of: lore:base` + `group_by: [{field: entry_type, order: label}]` |
| Assistants | `descendants_of: assistant:assistant` + `group_by: [{field: source_layer}]` (Machine-first falls out of roster order under first-seen) |
| Draft / Research | `nest(match: contained_in, recursive: true)` over the kind roster |

The backend materializer (`views.py:181`, presentation hardcode `:196`) writes these specs.
Duplicating a default now reproduces the original's rendering by construction — #212 closes.
Assistants' in-snippet drag re-keys from `presentation === null` to *manual sort + the default layer
grouping + no handles* (one careful implementation beat, flagged).

### 8. Author surface
> **Amended by [Amendment 1](#amendment-1--organize-is-per-group-2026-07-12):** the Organize controls
> live **inside each group**, not as one section beside the handles.

The designer's **result node** gains an "Organize" section: an ordered list of group-by dropdowns
(add / remove / reorder), offering the kind's groupable fields — populated through the same
input-kind machinery the pickers already use (`inferInputKind`, ADR-0031 §F). It is node *config*,
not graph shape: `group_by` lifts/lowers with the spec, adds no designer node, and therefore cannot
compete with Nest on the canvas. Handles are unchanged (wired named sections). Nest's match options
gain "contained in." The mental model is one sentence: **"Nest builds hierarchies from
relationships — including 'contained in'; group-by organizes by a field."**

## Amendment 1 — Organize is per-group (2026-07-12)

**Status: approved & implemented (2026-07-12).** Raised by Anton after dogfooding the shipped
designer; approved with no red-pen. Landed on branch `feat/0.7.0-213-grouping-view-algebra`.

### The problem
A view with named groups (handles A, B) showed a **single** Organize section *beside* the groups.
That imposed one grouping on every group and read as if the Organize levels somehow paired with the
groups. Two limits, one confusing surface:
1. **You cannot organize groups differently.** Group A's rows and Group B's rows are forced through
   the same Organize. There is no way to say "A grouped by Type, B grouped by Status."
2. **The relationship is unreadable** — Organize floats at the result, not attached to anything.

### The decision
**Organize is owned by a group, not by the result.** Every group carries its *own*, independent
ordered Organize levels.

- **Single / unnamed group** (a view with an `expr`, no named handles): keeps `ViewSpec.group_by`
  exactly as §2 describes — **behavior unchanged.** This is the "one implicit group" and all shipped
  defaults (Lore, Assistants, Draft) are this case, so nothing shipped changes.
- **Named groups** (`ViewSpec.groups` / designer handles): **each group gains its own `group_by`**
  (`ViewGroup.group_by?: ViewGroupByLevel[]`). Group A can organize by Type→Aliases while Group B
  organizes by Status — fully independent.
- **Evaluation:** the level application of §2 runs **per group, with that group's levels**, appended
  innermost within that group's rows. A group with no levels stays flat. (Today's single application
  over the merged result becomes the unnamed-group special case of the same rule.)
- **Designer:** the Organize controls move **inside each group**, shown under that group's handle
  row. The standalone result-level Organize section beside the handles is **removed**. For the
  single-unnamed-group view, Organize appears once, under that group.

### Conformance (amends the normative suite)
Add anchors: (a) two named groups with **different** `group_by` produce independently-organized
subtrees; (b) a group with no levels renders flat beside a sibling group that has them; (c) the
single-unnamed-group view is byte-identical to today (`ViewSpec.group_by` regression-locked). The
existing §2 anchors stay green (they are the unnamed-group case).

### Not in scope / unaffected
- The two ν operators (§1), the row-preserving pipeline (§5), provenance/membership (§6), containment
  Nest (§4), and `ViewPresentation`'s eradication (§3) are all untouched.
- `ViewSpec.group_by` **survives** as the unnamed-group slot, so what shipped in #229 is a
  forward-compatible subset — no stored-format break for the single-group defaults.
- This is a grouping-semantics change and lives **entirely in ADR-0037.** It is *not* related to the
  view-designer-UX pass (ADR-0038).

## Conformance

**`frontend/src/lib/views/adr0037.conformance.test.ts` is normative.** It transcribes §2/§4/§5/§6/§7
into executable assertions, written from the full design context *before* any implementation:
plain `it(...)` tests are **anchors** (behavior that holds today and must survive every stage);
`it.fails(...)` tests are the **spec** (vitest passes them while the behavior is missing and fails
the suite the moment it lands — the implementing commit flips them to `it`). Where this ADR's prose
and the suite disagree, **the suite wins until the ADR is amended** — do not reword an assertion to
make a stage pass; re-read the cited §, and if it is genuinely wrong, amend ADR + suite together as
their own reviewed change. Stage reviews verify the diff against the cited § (the #196 lesson), not
against the diff's own claims.

## Why / rejected alternatives
- **Rejected: `group_by` as a pipeline flow node.** A node with an output competes with Nest — two
  grouping mechanisms whose difference (recursion, joins) is unexplainable to authors. Grouping is a
  property of the *result*; the pipeline's only hierarchy-maker is Nest. (The decisive correction of
  this design's first draft.)
- **Rejected: `{structure: true}` as a group-by level.** Containment is a relation (§4); a
  `structure` level would bake the structure files — slated for removal — into the grammar, and
  would make the manuscript tree a *partition* when it is a *join*. It is Nest's job.
- **Rejected: flip the stored default presentation `"flat"` → `"grouped"`.** Feeds the hack it
  should remove; keeps the pane the author of the shape and the unspecified case special.
- **Rejected: a "context mode" flag on Nest.** Member-vs-context is emergent from evaluation order
  (§5): placed = member, revived = context. A mode would duplicate, as configuration, what wiring
  already expresses.
- **Rejected: an "Ungrouped" bucket for missing values.** Bare-at-level matches the orphan-at-root
  intuition and keeps v1 small; an explicit bucket can become a per-level option later.
- **Deferred: dynamic *outer* placement** (e.g. status buckets *outside* the manuscript tree).
  Innermost covers every current case (defaults; type-within-city); static handles already give
  field-outer. A per-level placement option can be added without breaking §2's rule.
- **Deferred: `ViewResult` concatenation / stacked heterogeneous results.** Union over rows is the
  grammar-level composition and already exists; `concat` stays gated on its first real caller
  (ADR-0035) — the Views-2.0 multi-result designer, not this ADR.

## Consequences
- **Deleted:** `ViewPresentation` in both stacks + storage + API (§3); `intrinsicDisplayResult` ×2;
  the #208 `groupBy` helper; the `treePresentation` flag (§6); the panes' presentation plumbing.
  Pre-1.0: **no migration** — stored `presentation` keys are ignored on read, defaults regenerate,
  test projects are recreated (`feedback_no_pre_1_0_migrations`).
- **New:** `ViewSpec.group_by` (both stacks, storage); `segmentForField` + level application;
  row-preserving σ/∩/− in `evalSource` (§5); `PathSegment.origin` + the two per-origin rules (§6);
  the containment computed field + Nest match (§4); the designer Organize section (§8); updated
  default materializer + `defaultView(kind)`.
- **Sub-issues to file:** Nest `orphans: keep` (unmatched children stay at root — the
  who-lives-where pattern; today they are dropped, `evaluateView.ts:848`); containment as a
  computed→stored reference field with eventual structure-file removal (its own, later milestone).
- **#112's original ask lands by construction:** a Draft view *without* the containment Nest is a
  flat scene list. "Strip the acts" (flatten specific levels) is μ/**unnest** — named here as the
  future affordance so it is not reinvented, not built now.
- **Build order (each step gated):** (1) this ADR; (2) backend `group_by` + presentation removal +
  materializer; (3) evaluator — §5 row preservation, §2 levels, §6 provenance; (4) panes — defaults,
  delete synthesis, Assistants re-key; (5) designer Organize + lift/lower; (6) sweep — StructureTree
  drops its forced presentation, `ViewPresentation` eradicated, gates + browser-verify.
- The test of the model: the grammar **shrank** (one enum and one pane mechanism removed, no new
  node) while its reach **grew** (Paris-style views: `nest(located_in, orphans: keep) +
  group_by(entry_type)` — universal entities' type buckets beside city headers, each city holding
  the same by-type grouping — previously inexpressible).
