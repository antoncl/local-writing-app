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
