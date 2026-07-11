# Architecture Decision Records

One decision per file (MADR-lite: decision · why/rejected-alternative · consequences). The *why*,
especially the rejected alternative, is the load-bearing part — it's what decays from memory.

## 0.4.0 — Mid-scene lore mutations (#33)
Design docs: [`../mid-scene-lore-mutations.md`](../mid-scene-lore-mutations.md) (v1.0 spine) ·
[`../mid-scene-lore-mutations-v1.1.md`](../mid-scene-lore-mutations-v1.1.md) (v1.1)

### v1.0
- [0001](0001-mutations-as-scene-body-markers.md) — Mutations as self-contained scene-body markers (Model A)
- [0002](0002-independent-interval-model.md) — Independent-interval model — no stack, no frames
- [0003](0003-position-granular-resolution.md) — Cumulative, position-granular resolution in manuscript order
- [0004](0004-every-field-mutable.md) — Every field is mutable — no `mutable` flag
- [0005](0005-book-as-resolution-boundary.md) — Book as the resolution boundary
- [0006](0006-resolver-mediated-context.md) — Lore context resolver-mediated at the `_format_lore_block` formatter
- [0007](0007-mutation-value-is-a-field-value.md) — A mutation value is a field value — validated
- [0008](0008-mutable-names-segment-the-matcher.md) — Mutable names segment the implicit-context matcher (v1.1+; **amended** in v1.1 → per-resolution-scene)

### v1.1
- [0009](0009-collection-add-remove-and-list-contract.md) — Collection add/remove ops; `effective_state` returns typed lists (#58; **amended** — `add` also appends on text/long_text)
- [0010](0010-interval-close-marker.md) — Interval close is a separate close-marker (#59)
- [0011](0011-transformation-sets-are-a-node-kind.md) — Mutation sets are a first-class Node kind (#62; **amended** — renamed from "transformation set")
- [0012](0012-scene-ref-resolution-input.md) — Resolution scene is a `scene_ref` prompt input (#60)
- [0015](0015-user-nameable-mutations.md) — Mutations carry an optional user name — a label, not a frame (#65)

### v1.1 — the time-sensitive lore entry
Design doc: [`../time-sensitive-lore-entry.md`](../time-sensitive-lore-entry.md)
- [0013](0013-time-travel-aware-lore-entry.md) — Lore entry is time-travel-aware; whole-card read-only effective overlay (#64)
- [0014](0014-mutations-version-cross-pane-signal.md) — `mutationsVersion` cross-pane freshness signal (#63)

### Authoring rework — the mutation unit
Design doc: [`../mutation-unit-authoring.md`](../mutation-unit-authoring.md)
- [0016](0016-mutation-unit-carrier-marker.md) — The mutation unit: one carrier marker, one pill; rows keep their own lifetimes (#69, #70; amends 0001/0010, subsumes 0015 `group=`)
- [0017](0017-collection-mutations-authored-as-list-edits.md) — Collection mutations authored as list edits, diffed against the effective baseline (#71)

## 0.5.0 — Views & Filters (#35)
Design doc: [`../views-and-filters.md`](../views-and-filters.md) · Prerequisite: #77 (entry_type FQN)
- [0018](0018-set-algebra-with-venn-glyph-authoring.md) — Views are set algebra, authored as a Venn-glyph composition graph (no boolean operators, no text DSL)
- [0019](0019-annotate-op-dissolves-grouping.md) — The annotate op: grouping (label) and coloring dissolve into the expression graph
- [0020](0020-views-are-kind-anchored.md) — Views are kind-anchored; universe = all nodes of that kind (needs #77 FQN)
- [0021](0021-saved-views-are-nodes-viewspec-is-the-core.md) — Saved views are frontmatter-only nodes; ViewSpec `(kind, expr, sort)` is the portable core
- [0022](0022-every-nodelist-is-backed-by-a-view.md) — Every NodeList is backed by a view; presentation ∈ {tree, grouped, flat}
- [0023](0023-nodepickerconfig-is-sources-plus-mechanics.md) — NodePickerConfig = `sources` (ViewSpecs/refs) + mechanics
- [0024](0024-assistant-dynamic-default-topmost-matching.md) — Assistant dynamic default = topmost matching; ★ default flag retired (#35 Q6)
- [0025](0025-views-evaluate-frontend-side.md) — Views evaluate frontend-side; SQLite index rejected (measured)
- [0026](0026-type-aware-jinja-helpers.md) — Type-aware Jinja helpers (`is_a`) on a shared entry_type-ancestry primitive
- [0027](0027-approachable-flow-injectors-filters-named-handles.md) — The approachable flow: injector/filter roles + named-handle grouping + denormalized `(node, path)` output (#91; amends 0018/0019/0021/0025)
- [0028](0028-nest-relational-trees-from-lore-links.md) — Nest: relational trees denormalized from lore links (#35/#101/#105; amends 0018/0025/0027)

## 0.5.5 — Field model
- [0029](0029-the-field-model-categories-operations-surfaces.md) — The field model: a permissive convenience, categorized by authorship (stored/intrinsic/computed); layering extends & overlays built-in types, presentation ops are category-independent (#118; follows #116)

## 0.6.0 — UI overhaul
- [0030](0030-design-language-quiet-writing-desk.md) — The design language: a quiet writing desk; full token layer as visual contract, interaction law promoted into the repo, tiled-shell gestalt for #32 (#124; steers #32/#125)

## 0.7.0 — Render pipeline
- [0031](0031-parameterized-views-free-variables-and-field-extraction.md) — Parameterized views: free variables + a bindings environment. **Rewritten 2026-07-09 (forward model):** a view **predicates** (`Filter`) or **projects** (`field_of`) forward from the side that carries the field, over a full-field roster (0034); the Filter value slot is field-typed (`entity_ref` → an entity operand compared by id), parameterizable, with cardinality-driven `overlap` (op enum 6→4); `field_of`'s output kind follows the projected field (ref → nodes, value → values); field selectors = **intersection of fields over the input set**; referenced-by = a computed `'References'` node-set field, not an operator. **Withdraws Match (0033); the two-pipe / id-extraction revision is superseded.** (#184; amends 0018/0020/0025/0027, builds on 0023, depends on 0034)
- [0032](0032-parameter-declaration-and-binding-provenance.md) — Parameter declaration + binding provenance. **Amended 2026-07-09:** **promote-in-place** is primary — a runtime formal is a promoted Filter value slot, named in the view's parameter list, its type **derived from the field** (intersection when shared across slots); the #182 wrapper renders one strip control per formal. `$self` = a reserved **wired source node** (ambient, no control, type = anchor kind), not a formal. Binding ladder: surface/reserved `$self` / author default (inline literal) / runtime strip / context-wire (v2); runtime picks ephemeral (view = template). The **declared Parameter-node-typed-by-reference is deferred** to node-set-source params (no current use case). (#184; follows 0031, builds on 0023/0022/0026)
- [0033](0033-match-flat-relational-sibling-of-nest.md) — Match: the flat relational sibling of Nest. **WITHDRAWN 2026-07-09** — superseded by 0031's forward model: forward predication keeps the subject (no join to recover it) and `field_of` projects, so reference matching needs no dedicated operator; any-field referenced-by is the `'References'` computed field; flat-vs-tree is presentation (0027/#181), not grammar. Kept as the record of why the operator is unnecessary. (#184)
- [0034](0034-view-universe-is-a-full-field-roster.md) — The view universe is a full-field roster: the evaluator can only reference fields present in the roster it is handed, so the forward model (0031) requires every node's complete field set; the thin manuscript-structure projection (computed counters + surfaced status/color) is insufficient. Draft membership either enriches the roster or (leaning) evaluates over the full node index and projects the id-set onto the structure tree. (#184 prerequisite; relates #182/#112; follows 0025/0031)
- [0035](0035-viewnodelist-viewresult-is-the-sole-input.md) — `ViewNodeList` (the #182 render wrapper, so named): a view's output is **exactly one `ViewResult<T>`, always** (`T` a node — 0031's value-set payload is an eval-internal operand, never reaches the wrapper), and that is `ViewNodeList`'s **sole input** — no `ViewResult[]`, no `ViewResult | T[]` union. Concatenation always lands inside one result at two levels: 0027 §D/§E manage grouping/nesting *within* a single result (**intra-result**); multiple result nodes joined by "vertical edges" (**inter-result**, Views 2.0) also reduce to one result — so a collection never surfaces to the wrapper. Non-view sites lift via a `ViewResult` constructor (`nodeSet(nodes)` = degenerate one-stream; optional `concat(...)` mirrors 0027 §D for hand-assembled results — not grammar, same-kind). Rule (0027 §E / 0019 / 0028): `nodes` = membership (deduped), `groups` = presentation (may repeat). `ViewNodeList` **composes** NodeList, does not extend it; absorbs `ViewGroupedList`+`GroupTree`. (#182; follows 0021/0022/0025/**0027**/0034; consistent w/ 0019/0028/0031 §D; relates #112/#181/#184)
- [0036](0036-implicit-explicit-views-and-empty-evaluation.md) — **The empty/null view evaluates to the empty set** (kills the `expr:null → whole roster` hack at `evaluateView.ts:329`/`:668`/`:686`; distinct from the neutral-reset for an unset *combinator operand* at `:1033`, which stays). Views are **explicit** (a pane offers customization → always backed by a real view node on disk, incl. a **system-provided default** that's copyable-but-read-only, carrying an *explicit* whole-kind spec that reproduces the old null view per a **per-site equivalence audit**; `descendants_of:<kind>:base` + intrinsic presentation) or **implicit** (no customization → **not** disk-backed; in-memory spec, never null-means-everything). Fold/ui state persists accordingly: explicit → `ui.collapsed` on the view node (stored verbatim, backend never evaluates — 0025; lock-free `PUT/GET /api/views/{id}/ui` outside the spec revision-lock; `collapseState` controller debounce+flush; frontend prunes inert keys); implicit → on the host node. Fold is **per-view**. The system default is a read-only switcher entry offering **Duplicate, not Edit**; `treeActions` localStorage collapse is deleted. (#112 the vehicle; follows 0020/0021/0022/0025/0031-neutral-reset/0035; settles the PENDING collapse decision in `decisions_182_view_node_list`)
