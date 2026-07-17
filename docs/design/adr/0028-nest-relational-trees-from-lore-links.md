# ADR-0028: Nest — relational trees denormalized from lore links

- Status: Accepted — 0.5.4, 2026-07-04
- Feature: #35 Views & Filters · builds on #101 (user-authored trees) · Doc: `views-and-filters.md` §13
- Amends: ADR-0025 (adds iterative fixpoint evaluation for the recursive region),
  ADR-0027 (path segments may now carry real-node identity sourced from data, and
  paths may exceed depth 1), ADR-0018 (adds a structural operator to the palette)
- Governed by: `memory/decisions_view_trees_are_path_denormalization.md`,
  `memory/decisions_ui_widget_taxonomy.md`

## Context
Every ViewExpr leaf answers *"is this node in the set?"* (type / tag / field / hand-picked /
view-ref — ADR-0018 §1.4). None of them express **how nodes relate to one another**. But the
denormalization machinery (ADR-0027 §E: rows `(node, path)`, normalized into nesting) can
already carry and render an arbitrary-depth tree — the renderer (`GroupTree.svelte`) recurses
unbounded today; only the *authoring* of depth > 1 was deferred. `decisions_view_trees_are_
path_denormalization.md` reserved this slot: *user-authored trees, where path segments carry
real-node identity and render as real NodeRows.*

Writers already model hierarchy in their lore by hand — Continents contain Countries contain
Cities; a family tree; nested Locations — using the tools they have: an `entity_ref` field
pointing at a related card, or a tag naming the parent. What is missing is a way to *turn those
links into a tree view*. That is a **1-to-many join** followed by denormalization, and it is
the natural home for depth > 1.

## Decision
Add a **Nest** node to the view designer — a structural operator (power tier) that reads
user-authored links between cards and emits denormalized parent/child rows.

**A. Shape — two input handles, real-node parent segments.**
The node is **Nest** (grammar keyword `nest`). It has **two input handles, both on the node's
left edge** — **Parents** (upper) and **Children** (lower), stacked like the Difference node's
keep/remove — and one output on the right. The handle names say what to wire: parent cards into
one, child cards into the other. For each child that matches a parent under the rule (B), it
emits a row whose `path` gains a `PathSegment` for that
parent with **`nodeId = parent.id`** — so parents render as real,
collapsible `NodeRow`s with identity, not synthetic buckets. Many-to-many falls out of
`(node, path)` dedupe: a child matching two parents yields two rows (appears under both). An
unmatched parent stays (a childless parent is legitimate); an unmatched child (orphan) is
dropped, with a surfaced count.

**B. One parameterized match rule, not three nodes.** The three ways a writer expresses a link
collapse to one rule with two axes:
- **direction** — `child→parent` (the child card holds the reference) or `parent→children`
  (the parent card holds the references);
- **match-by** — `ref` (an `entity_ref`/id field) or `title` (the child's tag equals the
  parent's title).

Config: `{ matchField, direction, matchBy: ref | title }`. Building three separate nodes for
mechanisms that differ by two flags is the duplication `feedback_flag_duplication_before_
shipping.md` warns against.

**C. Recursion via self-loop — the designer's first legal cycle.** Wiring a Nest's output back
into its own **parents** handle makes it iterate: **frontier BFS**. Each pass, the parents are
the *most recent additions* (the wavefront); the pass matches their children and attaches them
one level deeper; iteration ends when a pass adds nothing (**NOP**). This is what traverses an
unknown-depth homogeneous hierarchy (a family tree, nested Locations) with a single node —
depth is discovered, not wired. Seed the **parents** handle with the roots (typically
`field: { op: unset }` on the ref field) and the **children** handle with the universe; seeding
parents with the universe instead produces a *thicket* (a subtree rooted at every node), so the
UI defaults / guides the parents seed to roots.

**D. Three guards, three layers — and they are different.**
- **Flow-graph operator cycles** (the designer canvas). The connect-time hard *block*
  (`wouldCycle`, `isValidConnection`) predated Nest and existed only to keep the operator graph
  a compilable DAG. It is **retired as a block and repurposed as a classifier**: cycle
  detection stays (general, any length — a recursion loop is a back-edge, not necessarily a
  self-edge), but a cycle that **passes through a Nest's parents handle is a legal recursion**,
  while a cycle with **no Nest on it is meaningless → warn** (the compiler's existing `seen`
  guard would otherwise silently drop the back-edge and yield a wrong result with no feedback).
- **Data cycles** (the evaluator, during denormalization). A **mandatory ancestor-path guard**:
  when attaching a child, if it already appears among its own ancestors on that path, drop the
  edge and count it (*"3 cyclic links skipped"*). This is **load-bearing, not hygiene** — lore
  relationships are freeform user data with **no** acyclicity guarantee (unlike manuscript
  structure and research, which the UI keeps acyclic). It is also what **guarantees
  termination**: no path may repeat a node, so path length ≤ |distinct nodes|, so a NOP is
  provably reached even on malformed data. The guard and the termination are one property.
- **Runaway fan-out** (the evaluator, materializing rows). Termination is *not* tractability:
  the ancestor-path guard bounds path *length* (≤ |nodes|) but not the *number* of distinct
  simple paths, which in a dense match relation is combinatorial (toward factorial as the
  relation approaches complete — the universe→universe cross-product case). So a third,
  independent ceiling caps **materialized rows at `K · N`** (N = live universe size for the
  kind; K a small constant, e.g. 8). This never fires on real hierarchies — a strict tree emits
  exactly N rows, legitimate multi-membership a small multiple — but factorial fan-out blows
  past it within a pass or two. The **leading indicator is cheaper still**: in a healthy tree
  the BFS frontier *shrinks* each level; a frontier that *grows* toward the ceiling is the early
  tell. On breach the evaluator **hard-stops, truncates, and surfaces a warning** naming the
  likely cause (a too-permissive match, or the universe wired into both handles) — protecting
  the browser, since evaluation is frontend-side.

**E. v1 loop-body ceiling.** Detection of a recursion is general, but v1 only *supports* the
loop body being **the Nest alone** (the cycle reduces to a direct self-loop). A multi-node loop
— `Nest → Filter → Nest`, which would transform the frontier between iterations ("attach this
node but don't expand its children") — is a real, useful construct but a materially bigger
evaluation (the iteration step becomes "run a subgraph"); it gets the **warning** "frontier
transforms not supported yet", not silent garbage, and is a clean v2 increment. Filtering
*which children are eligible* remains available now: put the Filter on the **children** input,
outside the loop.

**F. Grammar — a first-class operator, not sugar.** Unlike ADR-0027's Filters (which lower to
`intersect`/`difference` and live only in `layout`), Nest has **no set-algebra equivalent to
lower to** — it produces paths from data relationships that membership leaves cannot express.
So Nest is a **new `ViewExpr` construct** carried in the portable ViewSpec:
`nest: { parents, children, match: {field, direction, by}, recursive: bool }`. The canvas
self-loop is the `layout` representation; it lowers to `recursive: true`. Draft and research
also get a cheap **acyclicity check/warning** in the validator (defense in depth), separate
from the mandatory lore guard.

## Why / rejected alternatives
- **Node name — "Nest".** "Join" — DB jargon — rejected; **Nest** is the verb and names the
  output shape. Its two input handles are labelled **Parents** and **Children**, so the
  operation still reads off the node (wire parent cards into one, child cards into the other).
  `nest` is the matching grammar keyword.
- **Three separate nodes for the three link mechanisms — rejected** (§B): they differ by two
  flags; one parameterized rule keeps the palette small.
- **A `recurse` toggle on the node instead of a self-loop — rejected.** Recursion is more
  honestly *topology*: the writer wires the output back to the input and reads "this repeats."
  It also unifies the two homogeneous/heterogeneous cases — chained distinct Nests for
  Continent→Country→City, a self-loop for a family tree — under one mental model (feed a Nest's
  output into a Nest's parents).
- **Deleting the flow-graph cycle check outright — rejected** (§D). The compiler must already
  distinguish a Nest recursion from any other back-edge to lower it correctly; reusing that same
  detection to *warn* on meaningless cycles is nearly free and spares the user a silent wrong
  result.

## Consequences
- **The designer is no longer a DAG.** A controlled, classified cycle (recursion through a
  Nest) becomes legal; `graphToSpec` must recognize the back-edge and lower it to
  `nest{recursive}` rather than let its `seen` guard swallow it. This is the headline shift.
- **The grammar grows a relational operator** (amends ADR-0018/0021): the backend `models_
  views.py` gains a `nest` construct; `evaluateView` gains (a) edge-building from the match
  rule and (b) an **iterative fixpoint** step for the recursive region (amends ADR-0025's
  single-pass frontend evaluation). Frontend-side eval is retained; the loop is bounded by
  |nodes|.
- **Path segments may carry real-node identity from data** and **paths may exceed depth 1**
  (amends ADR-0027 §E). The renderer already recurses unbounded, so the increment is
  concentrated in evaluator + grammar + the node, not the view.
- **`entity_ref` fields become tree edges.** The match rule reads existing ref fields and
  tag↔title matches; no new storage on cards. Which field types are joinable (`entity_ref`
  and tag-vs-title in v1; `context_pick` deliberately excluded — it is per-prompt runtime, not
  authored structure) is enumerated in the doc.
- **Out of scope for 0.5.4**: multi-node loop bodies / frontier transforms (§E); mutual
  recursion (a cycle through two Nests — warn); joining across kinds beyond the roster the
  anchor kind exposes.

## Amendment 1 — Orphans are a structural output, not a scalar disposition (0.7.0)

- Status: Accepted — 0.7.0, 2026-07-15
- Amends: §A (unmatched children "dropped, with a surfaced count") and the later
  `orphans: "keep"` disposition (added for #216 via ADR-0037 §Sub-issues).
- Closes: #255 (the `orphans` scalar is lost on every designer round-trip); reframes #252
  (a filtered `parents` seed does not subtract from membership — see §A below); supersedes #216.

### Context
Orphans are the child candidates a Nest never places — nodes in the `children` set whose match
never attached them under a seeded parent. §A dropped them (with a count); #216 added a binary
`orphans: "keep"` that re-adds each unplaced node **flat at the root**. Two problems surfaced:

1. **`"keep"` shreds hierarchy.** The re-add pass emits each orphan independently with `path: []`.
   With three acts *Aleph / Bet / Gimmel* and only **Bet** wired into `parents` (children = All),
   everything under Aleph and Gimmel — the acts *and* their chapters *and* their scenes — is
   unplaced, so `"keep"` dumps them all as flat sibling rows at the root, discarding their
   containment. `"keep"` was written for **leaf** orphans (a character with no region); it has no
   notion of an orphan that owns a subtree.
2. **The scalar can't be authored.** It has no designer control and is discarded on the
   graph→spec→graph round-trip (#255), so it silently reverts to `"drop"` on the first edit.

The deeper truth §A obscured: **membership is the `children` operand; `parents` only chooses BFS
seeds** (Amendment target — this is the #252 "filter is ignored" report). Filtering `parents` down
to Bet cannot remove Aleph/Gimmel from the output — they are still in `children`, so they surface
as orphans (or are dropped). The fix is not to make `parents` subtract; it is to make the orphan
set a **first-class, routable output** so the author decides its fate in the graph.

### Decision
**A. The unplaced-child set becomes a second Nest output — an ordinary node-set handle.** A Nest
exposes two outputs: its **results** (the denormalized tree, unchanged) and its **orphans** (the
flat set of `children` it never placed). The orphan output is a **first-class source handle** — it
carries the unplaced nodes as a plain node-set and may be wired into **any** downstream operator,
exactly like any other output, or left unwired. It is **not** special-cased or restricted to a
particular destination.

**B. Unwired ⇒ drop (default preserved).** With nothing consuming the orphan output, orphans are
dropped and counted exactly as §A of the base ADR specified — the out-of-the-box behavior does not
change, and the `children`-defines-membership rule is now stated, not implicit.

**C. Wired ⇒ the orphans flow, through whatever they are wired into, to the *same* `ViewResult`.**
Every branch — the orphan output included — can only terminate in the one output sink
(`OUTPUT_NODE_ID = "output"`, `viewGraph.ts`), so the whole view is always **one `ViewResult`**:
intra-result composition (ADR-0035 §1), never inter-result / Views 2.0. Crucially this is
**orthogonal to whether the backing spec is a tree or a DAG**: a two-output Nest consumed by two
branches makes the lowered spec a **single-sink DAG** (the Nest computed once, referenced twice),
and a single-sink DAG is *still exactly one result*. The Views-2.0 line is **multiple sinks**, not
internal fan-out; inter-result composition unlocks only if the designer ever offers add/remove of
the results widget — until then the topology forbids it for free.

**D. The orphan output is routable; its serialization is an implementation detail; the
`keep`/`drop` scalar is retired.** The author may feed orphans into **any** operator — a Filter, a
Sort, a group on the sink, or a second Nest — and the design must **not** constrain that to protect
a simple serialization. How `graphToSpec` lowers a Nest whose two outputs are consumed by different
branches is an implementation concern that accommodates the graph, not a limit on it (Anton: "*it
is immaterial how that is expressed in the backing query language*"). The natural tree-compatible
encoding is an **inline orphan sub-expression** on the Nest — the wired downstream chain
(filter/sort/second Nest) evaluated over the unplaced set and concatenated into the result — which
covers every case *except* an orphan stream cross-merging with an *unrelated* branch mid-graph; that
lone exotic case (and only it) would want named intermediate results / a single-sink DAG form, and
is deferred. The portable spec grows whatever the wiring needs; the design does not pick for it. The
binary `orphans: "keep"|"drop"` scalar is **retired** — its two values collapse to *unwired* = drop
and *wired* = routed; pre-1.0 straight cut, no migration (`feedback_no_pre_1_0_migrations`).

**E. Orphan reprocessing is available, not deferred.** Because the orphan output is an ordinary
node-set output, feeding it into a Filter/Sort, or into a **second Nest seeded on the orphan roots**
to rebuild Aleph's and Gimmel's subtrees intact, is just normal wiring — not a special case, and
not a §E frontier transform (that is a transform *inside* the recursion loop; this is downstream of
it). What may phase is only how much of the evaluator/lowering lands first — never whether the
design permits routing.

### Why / rejected alternatives
- **Rejected: keep the binary `keep`/`drop` scalar.** It flattens hierarchical orphans (Context 1)
  and can't be authored/persisted (Context 2). A routable output lets the graph, not a frozen enum,
  decide — and subsumes both old values (`drop` = unwired, `keep` = wired to a flat group).
- **Rejected: make `parents` subtract from membership.** That would redefine `children` as
  "children reachable from a parent seed," coupling two operands the base ADR kept orthogonal, and
  it still gives the author no way to *see* what fell out. Exposing orphans keeps `parents`
  attachment-only and makes the residue inspectable.
- **Rejected: restrict the orphan output (e.g. group-only) to keep the spec a tree.** This inverts
  the priority — it lets the serialization format dictate the feature. A single-sink DAG in the
  backing spec is embraced where the graph needs it (§C/§D); what we reject is **multiple result
  sinks** (inter-result composition, Views 2.0 — `decisions_views_2_0_flow_model`), which a routable
  orphan output does **not** require, because with one sink every branch still lands in one result.

### Consequences
- `evaluateView`'s `evalNest` exposes the unplaced-child set as a **consumable stream**: when an
  `orphans` sub-expression is present it evaluates that over the unplaced set and concatenates the
  result; on the unwired/drop path it counts them (`orphansDropped`) as today.
- **Moderate, multi-surface — not a one-line bugfix, but not a whole-spec DAG rework.** The scope
  is: `models_views.py`'s `nest` gains an optional `orphans` **sub-expression** field; `evalNest`
  evaluates it; the designer's Nest node grows a second **source handle** ("Orphans", flat); and the
  trickiest piece is the `graphToSpec`/`specToGraph` lowering rule that folds the wired orphan branch
  into `nest.orphans` and rebuilds it (closing #255 — the disposition now round-trips). Named
  intermediate results are **deferred** to the cross-merge case (§D), so this stays within the
  existing tree-shaped spec.
- No backend storage change on cards.

### Resolved
- **Default label/placement — moot** (Anton): there is no inherent label for the orphan output
  unless it is wired straight to the results sink, and even then the designer can add or remove any
  label node we provide. So the ADR prescribes none — a raw orphan→results branch is just the
  unplaced nodes, and labelling is an ordinary designer affordance (a group/label the author
  inserts), not a Nest-op default.

### Follow-ups and governing invariants (#275)

Two invariants govern the Nest/orphans machinery. They are upheld structurally, so
the evaluator and the lowering carry **no runtime guards** for them — a permanent
record, because both guards below were once added on a code review that did not
know these invariants, and the implementing thread (#260) applied the review's
suggestions without checking them against the code:

- **Acyclicity of the view graph** is held by `isValidConnection` at authoring
  (Svelte Flow's per-connect callback rejects every cycle except a Nest's legal
  results→own-`parents` self-loop) **and** a load-time 3-colour-DFS repair
  (`cycleCheck.ts`) at BOTH entry paths a cyclic view can take: the designer graph
  (`repairGraphCycles` in `hydrateGraph`) and the pane's stored spec
  (`repairSpecCycles` in `ViewNodeList` — panes evaluate a spec directly, never
  building a graph). Authoring can't create a cycle and neither load path can admit
  one, so `{orphans_of}` can never re-enter the evaluator. The `nestInProgress`
  re-entrancy guard and the `buildNode.seen` lowering guard were therefore redundant
  and are removed; a runtime guard would only trade a loud, catchable failure for a
  silent-empty result that masks a real gate leak. **No save-time / backend DAG
  check** — the frontend load boundary is the guarantor (load-valid + every-edit-
  valid ⇒ every saved view is valid), and a "cycle detected" error is not actionable
  by a non-technical author. (A max review caught that the first cut guarded only
  the designer graph; the pane spec repair is the second surface it prompted.)
- **Uniqueness of Nest ids** is held by Svelte Flow keying nodes by id (a duplicate
  breaks the canvas) plus `addNode`/`seedAddCounter` minting fresh ids; `nest.id`
  *is* the node id. So the `nestCache` memo keyed by id cannot alias two Nests, and
  a WeakMap-on-op (a review suggestion) buys nothing — dropped.

**Orphans-only wiring serializes the Nest inline.** A Nest evaluates the same
regardless of which of its two outputs are wired — an unwired output is *discarded
output*, not a semantic change. So when only the orphans output is wired (results
unwired), the Nest is otherwise unreachable from the sink and no `{nest}` would
serialize it: lowering carries its definition inline on the `{orphans_of}`
reference (`orphans_nest`, a companion field) so the reference resolves and the
node survives save→reload. A Nest whose results output is wired is defined by its
`{nest}` and the reference stays a bare `{orphans_of: id}`.
