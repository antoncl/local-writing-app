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
- [0031](0031-parameterized-views-free-variables-and-field-extraction.md) — Parameterized views: free variables + a bindings environment. **Revised 2026-07-09:** parameters are two families on two wire pipes (entity → node-set; value → `{field,value}` → Filter RHS), value/binding handles at node top, `field_of` (node-set → `{field,value}`) is a same-field extractor that always emits `{field,value}`, Filter RHS stays value-only, and **referenced-by is not a field predicate — it is Match (0033)**; cardinality-driven overlap collapses the `op` enum 6→4, `long_text` excluded, `$self` reserved (#184; amends 0018/0025/0027, builds on 0023)
- [0032](0032-parameter-declaration-and-binding-provenance.md) — Parameter declaration + binding provenance: author declares a Parameter node typed by reference (entity → view/node-set-pipe, value → field domain/`{field,value}`-pipe), entity types subtype-polymorphic (`is_a`, ADR-0026); binding ladder (surface `$self` / author default / runtime control / context-wire); runtime picks ephemeral (view = template, pane state not spec); the #182 wrapper owns the parameter strip (#184 configurator slice; follows 0031, builds on 0023/0022/0026; **revised 2026-07-09** — output pipes explicit, reference traversal → 0033)
- [0033](0033-match-flat-relational-sibling-of-nest.md) — Match: the flat relational sibling of Nest. Same config + `by:ref|title` link core (0028), but no recursion and a flat, header-stripped, deduped output — a semi-join returning the matched children (Parent/Child roles govern which side). Owns referenced-by / "scenes where `$character` is POV"; lets Filter stay value-only and Nest tree-only; input-aware match-field dropdown (shared with Nest) (#184; follows 0028/0031)
