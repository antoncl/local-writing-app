# Design: Views & Filters — v1 (0.5.0, epic #35)

Status: **draft for review** · 2026-07-02
Companion: GH #35 (epic), #77 (prerequisite), [`adr/README.md`](adr/README.md) (ADRs to be added on acceptance, §11)

## 0. What this is

Every filtering/view system we know of — including several Anton has built — ends up
power-user-only. The diagnosis is twofold: **boolean predicate logic gets tricky fast**, and
**the UIs are lousy**. This design attacks both, without giving up expressiveness:

- Replace boolean operators with **set operations** (union, intersection, difference,
  complement). These are exactly isomorphic to OR/AND/AND-NOT/NOT — nothing is lost — but
  most people have a working intuition for sets-of-things that they lack for predicates.
- Author views in a **drag-and-drop composition graph** whose operation nodes carry
  **Venn-diagram glyphs** (the Figma/Illustrator boolean-ops pattern: a two-circle icon with
  the result region filled). Non-designers use those daily without knowing the word
  "boolean". Not a literal interactive Venn canvas — that famously stops working past 2–3
  sets. The graph is a DAG with one output; most real views are two or three nodes deep.

One design serves the epic's three use cases (filter scenes by metadata, virtual groupings
in Lore, tagged-assistant picker scoping) plus a fourth that fell out during design:
**the same language replaces `NodePickerConfig`'s membership vocabulary** (§6).

## 1. The set model

### 1.1 Universe

> **Amended by ADR-0031 §I / ADR-0034 / §14 (0.7.0).** The universe is the view's **roster** (the
> `EvalNode[]` the pane supplies), and **complement is kind-relative**:
> `complement(S) = { n ∈ roster : kind(n) ∈ kinds(S) } − S`. The single-kind description below is the
> v1 (0.5.0) baseline and the *common* case (roster = one kind) — it no longer bounds the model.

A view is **anchored to one kind** (v1). Its universe — what complement is relative to — is
*all nodes of that kind in the project*: all lore entries, all scenes, all assistants.
This keeps complement well-defined, matches how the panes are already kind-scoped, and
keeps cross-kind "smart folders" out of scope (per #35).

### 1.2 Operations

> **Amended by §12 / ADR-0027 (#91).** The combinators below are retained but **demoted to
> the power tier**. The common case is authored with **injectors + filters** (a pipeline);
> explicit Operations appear only when the graph branches across differently-sourced sets.

Four combinators, each a node in the composition graph:

| Op | Glyph | Semantics |
|---|---|---|
| Union | ◉◉ both filled | A ∪ B (n-ary) |
| Intersection | ◉◉ overlap filled | A ∩ B (n-ary) |
| Difference | ◉◉ left lobe filled | A ∖ B — **not commutative**; ports have explicit roles (*keep* / *remove*) and the glyph shows which lobe survives |
| Complement | ◉ inverted | universe ∖ A |

Difference is the op most likely to confuse exactly the users this design targets; the
port-role labelling + filled-lobe glyph is a hard requirement, not polish.

### 1.3 Annotate — labels and colors (grouping dissolves into the graph)

> **Amended by §12 / ADR-0027 (#91).** The **label → grouping** half below is superseded:
> grouping is now the **View's named handles** (same handle unions+dedupes; handles concatenate
> in order; handle order = group order — the `rank` field is retired), and the standalone
> **Group** node and implicit "everything else" bucket retire with it. The **color → Highlight**
> half and the tint-for-depth rule survive unchanged.

A fifth node type, **annotate** (internal/ADR name), is a *pass-through*: it stamps the
members of its input set with a payload and forwards the set unchanged. It never filters.
Payloads:

- **Label** → *hard grouping*. The view's output nodes carry zero or more labels; the
  rendered list groups by label. A node with two labels appears in both groups (settled:
  multi-membership shows the node in every group). Unlabeled nodes fall into an implicit
  **"everything else"** bucket at the end. Each annotate node carries an explicit **rank**
  that orders the groups (alphabetical is wrong often enough that order needs a home).
- **Color** → *soft grouping*. Tints matching rows in place without re-partitioning the
  list — "make the Gotham entries findable at a glance while keeping the type grouping."
  Color annotations supply the **existing NodeRow color-part system** (the same slot
  entry_type colors feed today); precedence: a view color overrides the type color for
  the rows it covers. No new color treatment is invented
  (per `decisions_ui_widget_taxonomy`).

**User-facing naming.** "Annotate" is internal only. The designer surfaces **two palette
nodes, "Group" and "Highlight," both compiling to one annotate op** — because the two
payloads are two distinct user intents: *Group* assigns a name and **restructures** the
list into a bucket; *Highlight* assigns a color and **emphasizes in place** without
restructuring. One umbrella verb (e.g. "Mark") would misdescribe one of the two and
collides with the mutation-"marker" vocabulary. A Group node may *also* carry a color —
the combined case below.

**Tinting for depth.** When color and grouping combine — a Highlight *within* a named
Group, or (later) genuinely nested groups — each nesting level's color is a **programmatic
tint of the base color** (mix toward the background a fixed step per level), so depth is
legible at a glance. The tint is a computed shade of the **existing NodeRow color part**,
not a new treatment. **Scope:** v1 ships flat rank-ordered groups with optional per-group
color (tinting applies to the Group+Highlight overlay); true multi-level *nested* grouping
is a natural extension of chaining annotate nodes and lands when the designer proves it is
wanted — the tint rule is specified now so nesting inherits it for free.

This dissolves the epic's separate **Group** primitive: a grouping is not a parallel
structure in the view file, it *is* the annotate nodes in the expression graph. The
worked example that motivated it (see #35 use case 2 and the roll-up problem):

- "Characters" group = annotate(label: Characters, rank: 1) ← descendants-of(lore:character) ∖ descendants-of(lore:deity)
- "Deities" group = annotate(label: Deities, rank: 2) ← descendants-of(lore:deity)

Add a `demigod` subtype next month and it lands in the right group with no view edit.

### 1.4 Leaves

The combinators are settled and few; the **leaf vocabulary defines what the system can
express**. v1 leaves:

| Leaf | Example | Liveness |
|---|---|---|
| **type** | `entry_type = lore:character` (exact) | live |
| **descendants-of** | `lore:character` and every entry_type inheriting from it (`parent:` chains, `schema.py` inheritance resolution) | live |
| **tag** | tagged `gotham` | live |
| **field predicate** | `pov = honor`, `status ≠ draft`, `locations includes kitchen` | live |
| **hand-picked** | an explicit node list, chosen via NodePicker | **static** |
| **view-ref** | embed a saved view as a sub-expression | as referenced |

Notes:

- Field-predicate leaves are authored with the field's **own widget**
  (`FieldValueEditor` already renders per-type) — a select field offers its options, an
  entity_ref field offers the picker. Operators per type: equals / not-equals for
  scalars, includes / not-includes for collections, plus set/unset. No free-text
  comparison DSL. **(Amended by §14 / ADR-0031 §E, 0.7.0: these collapse to
  `overlap`/`disjoint` (+`set`/`unset`) under set-coerced overlap — a single-valued field tests
  against a multi-pick set. The 6-op vocabulary here is the v1 baseline.)**
- **Hand-picked is the one static leaf** — a snapshot enumeration ("my problem scenes"),
  not a query. The designer shows the live/static distinction; mixing them in one view
  is fine and useful.
- **view-ref** is where views-as-nodes pays off: "Gotham cast" defined once, reused in
  the Lore pane, in an entity_ref field's picker constraint, and as a prompt's
  context_pick source. Cycle detection at save time (reject, name the cycle).
- Entry_type references serialize the **FQN** form — which is why **#77 must land
  first** (§8).

### 1.5 Sort

Orthogonal to membership, per the epic. v1 vocabulary: by field (any comparable field,
asc/desc), by title, by **manual/stored order** — the last is load-bearing for
Assistants, where drag-reorder is the ranking the dynamic default reads (§6.3). Sort
applies within each group; group order comes from handle order (§12, ADR-0027).

> **Amended by §12 / ADR-0027 (#91).** Sort is **per-segment**: a **Sorter node** in a branch
> sorts that segment before it reaches its handle. This ViewSpec-level `sort` remains the
> fallback when no per-branch Sorter is present.

## 2. ViewSpec — one membership language, two carriers

**ViewSpec** = `(kind, expr, sort)` — the portable core. Two carriers:

1. **A saved view** = a **frontmatter-only node** of new kind `view` (folder `views/`,
   no body): name + ViewSpec + presentation hints (§3). Node storage gives CRUD,
   listing, naming, project-versioned persistence for free — no bespoke `views.yaml`
   subsystem (the chat-as-node lesson). Answers #35's persistence question:
   project-scoped; per-user views are out of scope for a single-user local app.
2. **An inline anonymous ViewSpec** embedded where a membership constraint lives today
   (picker configs, §6) — same schema, no node.

Serialized shape (illustrative, not final YAML):

```yaml
kind: lore
expr:
  union:
    - annotate: { label: "Characters", rank: 1 }
      of:
        difference:
          keep: { descendants_of: "lore:character" }
          remove: { descendants_of: "lore:deity" }
    - annotate: { label: "Deities", rank: 2 }
      of: { descendants_of: "lore:deity" }
sort: { by: "title", dir: "asc" }
```

**Evaluation lives frontend-side in v1**: one pure `evaluateView(spec, nodes)` module
consumed by panes and pickers alike. Panes already hold their kind's node summaries; the
backend stores and validates view nodes but runs no queries. Server-side evaluation is
deferred until something that can't see the frontend (context expansion?) actually needs
it — explicitly out of v1.

### 2.1 Rejected alternative: a SQLite index as the evaluator

Considered and rejected. **Performance is not the reason to reach for a database here —
measured, the in-memory evaluator has ~5× frame-budget headroom on a pathological
project and microsecond cost on a realistic one:**

| Scenario | `evaluateView` cost |
|---|---|
| Realistic large project (800 lore entries), simple view | ~42 µs |
| Pathological (10,000 nodes), deep view (2× descendants-of, tag + field predicate, difference/intersection/union, 2 annotates, sort, row materialize) | ~3.2 ms |

The 60fps budget is 16 ms; 10,000 nodes is ~20× a large fiction project's lore
collection. Set operations over a few thousand ids are simply not where wall-clock goes.

SQLite would *cost*, not save:

- **The data is already frontend-side.** Panes load their kind's summaries today;
  evaluation runs on data in hand. A SQLite evaluator adds an HTTP round-trip
  (~1–5 ms) per evaluation — more than the entire in-memory evaluation, and the
  designer's live preview (re-evaluating per edit) would feel it.
- **Coherence is a new failure category.** Files on disk are the source of truth; a
  SQLite index is a derived write-through cache needing correct invalidation on every
  mutation path — including external edits and the uvicorn-restart-mid-save class
  (#72). `.cache/` is rebuildable *by design* precisely because derived state drifts.
- **The ops don't map cleanly.** `descendants-of` needs recursive CTEs or a maintained
  closure table; the multi-label **annotate** pass-through has no SQL shape — you'd run
  N queries and merge in code anyway, so SQL buys nothing.
- **Where SQLite wins** — data exceeding memory, selective indexed lookups over 100k+
  rows — a fiction project never reaches. If one did, the "pane holds the whole kind"
  model breaks *before* the evaluator does — a larger redesign independent of evaluator
  location.

**Two real performance concerns, neither addressed by a database:** (1) *payload width* —
field-predicate leaves need their fields present in the frontend summaries, so those
summaries may widen (or those leaves evaluate backend-side); verify during build step 2.
(2) *rendering, not evaluating* — a 1,700-row result is microseconds to compute, real
milliseconds to lay out; the fix if it ever bites is list virtualization in NodeList,
orthogonal to the evaluator.

**Escape hatch by construction:** `evaluateView(spec, nodes)` is a pure function over a
serialized spec. If the backend ever needs to evaluate views (context expansion), port
that one function to Python over the existing node index — still no database.

## 3. Every NodeList is backed by a view

The invariant: **every NodeList renders through a view** — most implicit and fixed, some
user-switchable. The 2026-07-02 inventory (12 NodeList sites + 3 hand-rolled lists):

| Surface | Default view (implicit) | Switcher in v1? |
|---|---|---|
| Lore pane | group-by-entry_type (as today) | **yes** |
| Draft pane (Tree) | manuscript structure | **yes** (color annotations only, §3.1) |
| Assistants pane | group-by-layer, manual order | **yes** |
| Prompts, Chats, Mutations panes | current shapes, expressed as fixed views | no (later) |
| Pickers, add-menus, BacklinksPanel, MutationTimeline, SchemaTreePane, ReferencePicker | fixed views | no |
| Search / Todo / cost breakdown (hand-rolled) | — | no; Search is the natural later adoption (a search = an ad-hoc view), Todo is an index over markers (`decisions_todo_as_node_index`), cost breakdown isn't a node list |

### 3.1 Presentation: tree is a shape, not a grouping

A view's presentation is one of **tree-from-structure / grouped / flat**. The set
machinery handles *membership and annotation* in all three; label-grouping applies only
to grouped/flat. The Draft tree keeps its structural shape — v1 gives it **color
annotations** ("tint Honor's scenes" over the hierarchy), which delivers use case 1
visually *without* solving filtered-tree ancestor visibility (a matching scene needs its
non-matching chapter/act ancestors kept visible). Membership-filtering the tree is
deferred to a later slice, deliberately. **(Amended by ADR-0034 / §14, 0.7.0: Draft
membership-filtering — scene POV/status — now ships, over the enriched structure roster
(ADR-0034 path (a)); a matching scene keeps its non-matching chapter/act ancestors via the
`presentation: "tree"` ancestry path.)**

## 4. Authoring UI — the view designer

> **Amended by §12 / ADR-0027 (#91).** The palette gains **roles** — injector (incl. universal
> `All`) · filter · operation (power tier) · sorter · View with named handles — so the 90% case
> reads as a pipeline. See §12 for the paradigm.

- **Svelte Flow** (`@xyflow/svelte` 1.0) — verified a full Svelte 5 rewrite, stores
  converted to runes. Adopted for the designer canvas. (Likely double duty in the 0.6.0
  workspace overhaul, which is node-based-UI home turf.)
- The designer is a **NodeEditor body view** for the `view` kind (the app-reduces-to-
  NodeRow-or-NodeEditor lens): leaf nodes on the left, combinator/annotate nodes with
  Venn glyphs, one output node. Leaf configuration uses the widgets named in §1.4.
- Live preview: the designer evaluates against the open project as you compose —
  the result list (with groups/colors) renders beside the canvas.

## 5. Switchable views on panes

Lore, Draft, Assistants gain a **view selector** in the pane handle bar (the "+ Entry" /
"+ New set" pattern): the implicit default view first, then saved views for that kind,
then "New view…" opening the designer. The pane persists its last-selected view in UI
state (not in the project — the *views* are project data; the *selection* is not).

## 6. NodePickerConfig unification

### 6.1 Membership vs. mechanics

Today's `NodePickerConfig` (`{kinds, entry_types, presets, multiple,
allow_target_marking}`) conflates **which nodes are pickable** (membership — an
impoverished view language) with **how the picker behaves** (mechanics). The
unification splits it:

```yaml
sources:                              # membership: one ViewSpec-or-ref per kind
  - kind: lore
    expr: { intersect: [ { descendants_of: "lore:character" }, { tagged: "villain" } ] }
  - view: "act-2-cast"                # reference to a saved view node
multiple: true                        # mechanics stay picker-local
allow_target_marking: false
presets: []                           # full_outline / full_text are synthetic, not nodes
```

`sources` is a **list because views are kind-anchored** (§1.1) but pickers legitimately
span kinds: one source per kind, union across sources, dropdown keeps grouping by kind.
Today's `{kinds, entry_types}` shape is exactly the degenerate one-leaf inline form —
the format flips wholesale, pre-1.0, no migration (`feedback_no_pre_1_0_migrations`).

Ripple: three storage sites carry the old shape — schema field `picker_config`, prompt
input `target`, `tags.yaml` scopes. All flip to `sources` in one slice, **early** in the
build order, so nothing downstream serializes the dead shape.

### 6.2 What deliberately does NOT unify in v1

- **Tag scopes stay on the degenerate form** (type leaves only). Scope enforcement is
  backend-side (`metadata_values.py` auto-broadening) — full expressions would force a
  backend evaluator into v1 — and tag-dependent tag scopes are a self-referential swamp.
  Same ViewSpec format, restricted expr subset: unified on paper, none of the machinery.
- **Editor UI**: `NodePickerConfigEditor` keeps its simple checkbox-tree form, emitting a
  degenerate ViewSpec, plus one addition: "…or use a saved view" (view-ref). The graph
  canvas ships once, for the designer (§4). Unify the language and the evaluator, not
  the authoring UI.

### 6.3 Tagged assistants — use case 3, nothing bespoke

- The built-in `assistant` entry_type gains a `tags` field (one-line default-schema
  addition; tag-scope auto-broadening applies unchanged).
- A prompt declares its assistant constraint as a source over `kind: assistant`
  (e.g. `tagged: summary`).
- The assistant picker's NodeList gets that view with **soft partition** presentation:
  matching assistants first (in manual drag order), the rest reachable below a divider —
  the epic's "full list still reachable, relevant first".
- **Dynamic default = the topmost matching row**; if nothing matches, topmost overall.
  The `★ default` flag is **retired** — manual order already expresses global
  preference, and "topmost" degrades to exactly the old behavior when no constraint is
  declared. (Resolves #35 open question 6: override, don't coexist.)

## 7. Cross-pane awareness — explicitly no

#35 question 5 (Draft view filters to Honor scenes → Lore pane auto-narrows to
referenced lore): **no in v1**. Cool but coupled; it makes pane state a dependency graph.
A user who wants it can build the lore-side view explicitly. Revisit post-0.6.0 if the
workspace overhaul makes pane linkage a first-class concept.

## 8. Prerequisites & ripples

1. **#77 — entry_type FQN** lands before any view serializes an entry_type reference.
   View expr uses the FQN form exclusively.
2. **Assistant `tags` field** in the built-in schema (§6.3).
3. **`view` joins the kind whitelist** — re-read `docs/metadata-strategy.md`
   class-instance invariants before touching it (standing rule).
4. Svelte Flow dependency added (frontend only).
5. **Shared `entry_type_ancestry` primitive.** The view `descendants-of` leaf (§1.4) and
   the type-aware Jinja helper (§8.1) both need one thing: given an entry_type FQN, its
   ancestor/descendant chain via `parent:` (schema inheritance resolution,
   `schema.py:832`). Build it **once** in the schema service; expose it in the schema
   payload the frontend already receives (for the evaluator) and call it directly
   backend-side (for the Jinja helper). Not two implementations.

### 8.1 Type-aware Jinja helpers (prompt logic branches on type)

Templates can branch on a node's exact entry_type today only via `entry.entry_type ==
"character"` (exact string, no inheritance, no FQN — `helpers.py:181`, `:349`). Add an
**inheritance-aware predicate** so a prompt's logic can key off type family:

- **`is_a(node, "lore:character")`** → bool; true when the node's entry_type **equals or
  descends from** the given FQN. Registered in `register_helpers()` (the
  `env.globals["…"] = …` pattern, `helpers.py:390–407`), backed by the §8-item-5 ancestry
  primitive. Enables `{% if is_a(entry, "lore:character") %}…{% endif %}`.
- (Optional) `kind_of(node)` → the entry_type FQN string; largely covered by
  `entry.entry_type` once FQN-qualified, so ship only if a call site wants it.

Additive to the template surface, so pre-1.0 is the right time (the surface freezes at
1.0). Depends on **#77** (FQN) for the qualified argument form and on the shared ancestry
primitive. See ADR-0026.

## 9. Out of scope (v1)

- Cross-kind views / smart folders (per #35).
- Text DSL — the graph is the authoring surface; the epic's GUI-vs-DSL question
  dissolves.
- Server-side evaluation / query indexes.
- Cross-pane narrowing (§7).
- ~~Membership-filtering the Draft tree (§3.1 — color annotations only).~~ **Now IN scope for 0.7.0**
  — ships via ADR-0034 (a) enrich (§3.1 amended).
- Search/Todo adoption of NodeList+views.
- Per-user (vs project) views.

## 10. Build order (sketch — sub-issues on acceptance)

0. **#77** FQN fix (independent, first).
1. **ViewSpec schema + backend storage**: `view` node kind (folder, CRUD, whitelist),
   ViewSpec validation, `NodePickerConfig` → `sources` format flip across the three
   sites. No evaluator yet — panes still render their hardcoded shapes.
2. **Frontend evaluator**: `evaluateView(spec, nodes)` + leaf evaluation + annotate;
   express the current Lore/Draft/Assistants shapes as implicit default views and route
   their NodeLists through the evaluator (behavior-identical refactor, verifiable).
3. **View designer**: Svelte Flow canvas as NodeEditor body view, Venn-glyph nodes,
   leaf widgets, live preview.
4. **Pane switchers** on Lore, Draft (color-on-tree), Assistants.
5. **Picker integration**: NodePickerConfigEditor emits ViewSpec + saved-view option;
   assistant tags + soft-partition picker + dynamic default.
6. **Type-aware Jinja helpers** (§8.1): `is_a` on the shared ancestry primitive. Depends
   on step 1 (the primitive) + #77; otherwise independent of the UI steps.

Each step lands green (ruff + pytest + svelte-check + browser-verify) before the next.

## 11. ADRs to add on acceptance

- Set algebra over boolean predicates; Venn-glyph graph authoring (§0–1).
- Annotate op: grouping/coloring dissolve into the expression graph; user-facing
  Group/Highlight; tinting for depth (§1.3).
- Views are kind-anchored; universe = all nodes of the kind (§1.1). **(Superseded for 0.7.0 by
  ADR-0031 §I / ADR-0034: universe = the view's roster; complement is kind-relative.)**
- Saved views are frontmatter-only nodes; ViewSpec is the portable core (§2).
- Every NodeList is backed by a view; presentation ∈ {tree, grouped, flat} (§3).
- NodePickerConfig = sources (ViewSpecs/refs) + mechanics (§6.1).
- Assistant dynamic default = topmost matching; ★ flag retired (§6.3).
- Type-aware Jinja helpers on a shared ancestry primitive (§8.1).
- **The approachable flow: injectors, filters, named-handle grouping, denormalized output
  (§12; ADR-0027 — amends set-algebra/annotate/sort ADRs, #91).**
- **Nest: relational trees denormalized from lore links; the designer's first legal (classified)
  cycle (§13; ADR-0028 — 0.5.4, amends evaluator/output/palette ADRs).**

## 12. The approachable flow (#91 — paradigm overhaul)

The Venn-glyph graph (§0–1) is the right *foundation* but a hostile *front door*: a bare leaf
reads as "the whole universe," and the simplest narrowing needs an explicit Intersect. #91
keeps the set-algebra foundation and makes the authoring surface approachable — **not** by
reverting to a boolean filter builder (predicate logic in a costume; rejected — see ADR-0027),
but by giving the palette **roles** so the 90% case reads as a pipeline and the algebra appears
only when the graph branches.

**Palette roles.**

- **Injector** — a source (no input) emitting a set: the §1.4 leaves **plus a universal
  `All`** (the whole kind universe).
- **Filter** — a transform (set in → narrowed set out) on the same predicates. **Series = AND,
  parallel = OR** (topology, never keywords). A filter is **sugar**: `keep: p` →
  `intersect(input, inject(p))`, `drop: p` → `difference(input, inject(p))`. It lives in the
  designer `layout` and lowers to the §2 `expr` on save — the evaluator and grammar are
  unchanged.
- **Operation** — the §1.2 combinators, **power tier only**.
- **Sorter** — sorts one branch/segment (§1.5, amended).
- **View** — the output, with **N named input handles**.

**Named handles = grouping, and dedupe made visible.** Handles are ordered top-to-bottom.
*Same handle* → union + dedupe (one group; a flat OR is "both branches into one handle").
*Across handles* → ordered concatenation, each handle a group, **handle order = group order**
(drag to reorder; no `rank`). A node may sit under several handles (multi-membership). The
handle's **name is the group label**. This supersedes §1.3's label+rank grouping; Highlight
(color) survives.

**Denormalized output — grouping and trees are one mechanism.** `evaluateView` returns rows
**`(node, path)`**, `path` = handle / sub-flow names outer→inner. **Dedupe on identical
`(node, path)`**; **normalize by `path`** (0–1 segments → flat/grouped; deeper → nesting — the
RPG-II level-break). Handle / sub-flow order = sibling order per level. Trees fall *out* of
named handles + named sub-flows — no separate subsystem.

**0.5.0 cut line.** The row/`path` contract carries arbitrary depth from day one, but **v1
emits depth ≤ 1**: a sub-flow / view-ref feeding a handle contributes its *result set* (flat,
deduped — today's view-ref behavior). A sub-flow contributing its *own group structure* (real
nesting) is the later increment — a renderer that walks paths deeper than one. Nothing in the
grammar or stored spec caps depth; only the renderer does. **Rendering:** 1-handle View → flat
(handle name = the list's title); 2+ handles → groups.

**What this closes.** The four #91 polish items dissolve structurally: the comparator lives
*inside* a Filter (derived from the field); Type is offered only for kinds with >1 entry_type;
"Views over" hides when the anchor kind comes from pane context; group order is handle order.
See ADR-0027 for the full decision, rejected alternative, and consequences.

## 13. Relational trees — the Nest node (0.5.4; ADR-0028)

§12's named handles + sub-flows give grouping and *shallow* nesting from **wiring**. Writers,
though, already model deep hierarchy in their **data**: a Country card's `continent` field
points at a Continent; a City is tagged with its Country; a person references their parent.
**Nest** (grammar keyword `nest`) turns those links into a tree — a 1-to-many join, denormalized
into rows. It is the authoring surface for depth > 1
(`decisions_view_trees_are_path_denormalization.md`), and unlike a Filter it is **not sugar**:
set-membership leaves cannot express relationships, so it is a first-class operator in the
ViewSpec.

**Two handles, real parents.** Nest's two input handles — **Parents** (upper) and **Children**
(lower), both on the node's left edge like the Difference node's keep/remove — say what to wire:
parent cards into one, child cards into the other. For each matching child it emits a row whose
path gains a segment for its parent — with the parent's real `nodeId`, so it renders
as a genuine collapsible `NodeRow`, not a synthetic bucket. A child matching two parents appears
under both (`(node, path)` dedupe); a childless parent stays; an orphan child drops with a
surfaced count.

**One match rule, three link styles.** The rule has two axes — **direction** (`child→parent`
if the child holds the reference, `parent→children` if the parent does) and **match-by**
(`ref` for an `entity_ref`/id field, `title` for child-tag-equals-parent-title). One node,
one `{ field, direction, by }` picker — not three nodes. (`context_pick` is excluded: it is
per-prompt runtime, not authored structure.)

**Recursion is a self-loop.** Wire the node's output back into its own **Parents** handle and it
iterates — **frontier BFS**: each pass takes the most recent additions as parents, attaches
their children a level deeper, and stops when a pass adds nothing (**NOP**). One node traverses
an unknown-depth homogeneous hierarchy (family tree, nested Locations); chained distinct nodes
handle heterogeneous levels (Continent→Country→City). Seed **Parents** with the roots
(`field: unset` on the ref) and **Children** with the universe; seeding Parents with the
universe yields a thicket (a subtree per node), so the UI guides the Parents seed to roots.

**Three guards.** *(1) Flow-graph cycles* — the designer's old blanket "no cycles" block
predated this node and only kept the graph a compilable DAG; it is **downgraded from block to
classifier**. Detection stays (general, any length — a recursion loop is a back-edge, not
necessarily a self-edge): a cycle **through the node's Parents handle is a legal recursion**; a
cycle with **no Nest on it → warn** (otherwise the compiler silently drops the back-edge).
*(2) Data cycles* — the evaluator keeps a **mandatory ancestor-path guard**: a child already
among its own ancestors on a path is dropped and counted. Load-bearing, because lore links are
freeform (no UI acyclicity, unlike draft and research), and it is what **guarantees
termination**: no path repeats a node, so length ≤ |nodes|, so a NOP always arrives even on a
mistyped family tree. *(3) Runaway fan-out* — termination isn't tractability: the ancestor
guard bounds path *length*, not path *count*, which goes combinatorial in a dense match
(the universe→universe cross-product). So a **materialized-row ceiling at `K · N`** (N =
universe size, K a small constant) hard-stops, truncates, and warns — never tripping on a real
tree (strict tree = exactly N rows) but catching the cross-product blow-up within a pass or two.
The early tell is a BFS frontier that *grows* instead of shrinking.

**0.5.4 cut line.** Recursion detection is general, but only the **direct self-loop** (loop
body = the node alone) is *supported*; a multi-node loop (`nest → Filter → nest`, transforming
the frontier between passes) is warned and deferred to a later increment. Child-eligibility
filtering meanwhile goes on the **children** input, outside the loop. See ADR-0028 for the
grammar construct, evaluation, and consequences.

## 14. Parameterized views (0.7.0, #184 — ADR-0031 / 0032 / 0034)

The *why* (forward model, `$self`, kind-relative complement, why Match is unnecessary) lives in
ADR-0031/0032/0033(withdrawn)/0034. This section pins the **representable shapes** a builder needs,
so nothing here has to be inferred from intent.

Parameterization touches **both** representations: the portable `ViewSpec = (kind, expr, sort)` and
the designer `ViewGraph` it lowers from (`graphToSpec`).

### 14.1 ViewSpec additions (the portable, stored, evaluated core)

**Parameter list — `ViewSpec.params`:**
```yaml
params:
  - { name: "POV",    label: "Point of view", default: null }
  - { name: "status", label: "Status",        default: ["draft", "revised"] }
```
- `name` — stable key, referenced by operands (below). `label` — parameter-strip UI. `default` —
  the authored **overridable** default (ADR-0032); `null`/absent ⇒ unbound ⇒ its predicate is
  **inactive** until the user picks (ADR-0031 §B).
- **No `type` field is stored.** A param's type is **recomputed at load** from the field(s) whose
  slot references it (the intersection rule, ADR-0031 §F) — single source of truth, no drift.
- `$self` is **reserved** and never appears in `params` (surface-supplied via bindings).

**Variable / projection operand.** A `field` predicate's `value` is **either** a literal (as today)
**or** exactly one tagged operand — mutually exclusive by shape, so there is no precedence to
resolve (a slot holds one value):
```yaml
field: { key: "status",  op: "overlap", value: ["draft"] }                        # literal (unchanged)
field: { key: "pov_ref", op: "overlap", value: { var: "POV" } }                   # promoted formal
field: { key: "pov_ref", op: "overlap", value: { var: "$self" } }                 # reserved anchor
field: { key: "tags",    op: "overlap", value: { field_of: { of: <ViewExpr>, field: "tags" } } }  # projection
```
The designer's three fill-modes (inline literal / promoted formal / wired source) lower to exactly
these two ViewSpec shapes — a **bare literal** or a **tagged operand** (`{var}` or `{field_of}`).
That is the whole operand discriminator.

**`field_of` — a new `ViewExpr` that produces a set:**
```yaml
field_of: { of: <ViewExpr>, field: "pov" }
```
- `of` = the input set (any `ViewExpr`: a leaf, `$self`, set algebra). `field` = the projected key.
- **Output payload is inferred, never stored** (ADR-0031 §D): `field` a **reference** field →
  a **node-set**; a **scalar** field → a **value-set**. Evaluator does `flatMap` + dedup.
- Appears standalone (feeds set algebra / the render wrapper) or inline in a predicate `value`
  (same-field / same-value / same-tag matching).

**`$self`** — the reserved operand/leaf `{ var: "$self" }`; in an `of`/leaf position it is a
**singleton node-set** (the anchored node). Bound by the surface via `EvalContext.bindings`;
unresolved (a pane with no anchor) ⇒ the **empty set**.

**`references`** (label "References") — no special shape. It is the ADR-0029 catalog **computed**
field (node-set-valued; §G of ADR-0031, spec'd in §14.4), so it is just a `field` key:
`field_of: { of: { var: "$self" }, field: "references" }` → the referrers.

**`op` enum, 6→4** — `ViewFieldPredicate.op ∈ { overlap, disjoint, set, unset }` (was
`eq`/`neq`/`includes`/`not_includes`/`set`/`unset`). `overlap` = set-coerce both sides, test
non-empty intersection; `disjoint` = its negation. `entity_ref` compared by **id**, scalar by
value (ADR-0031 §E). No migration of stored old-op values — test projects recreated (pre-1.0).

**Entity-typed operands, literals, and bindings.** An `entity_ref` operand — a literal, a `default`,
or a resolved binding — is a **list of ids** (the field's stored representation), e.g.
`value: ["char-bob", "char-alice"]` or `default: ["char-bob"]`; comparison is **id-overlap**. So
`ctx.bindings[name]` for an entity formal is an **id-set**; for a value formal, a **value-set**. The
`{ var: name }` shape is **position-dispatched**: in an `of`/leaf position it must resolve to a
**node-set** (in the 0.7.0 cut only `$self` is legal there — a declared entity source is deferred,
ADR-0032/§14.5); as a predicate operand it may be a
node-set or a value-set, and the evaluator dispatches on the bound value's shape.

### 14.2 Evaluation

`evaluateView(spec, nodes, ctx)` — `ctx.bindings: Record<string, IdSet | ValueSet>` (name → actual),
injected exactly as `resolveView`/`schema` are (ADR-0025). `ctx` also threads the **reference index +
id→summary map** (§14.4), the same way. Resolution: `$self` and each promoted
formal read from `bindings`; an **unbound formal with no default** ⇒ its predicate is inactive
(input passes through); an **unresolved `$self`** ⇒ empty set. The runtime stays field-structural
(no per-node type inference at eval time — §14.3 is authoring-time only).

### 14.3 Designer graph (`ViewGraph`) additions

- New `GraphNodeKind`s: **`field_of`** (one `of` input handle, a field selector, one output) and
  **`self`** (reserved source, no input, one output). *(No `param` node — parameters are
  promote-in-place, §14.4; the deferred declared source node is ADR-0032, out of this cut.)*
- **Handle payload type.** Each handle carries an inferred payload type — **node-set** or
  **value-set** (ADR-0031 §D/§F). The connection validator rejects value-set → node-set-input and
  vice-versa: this is the two-payload accept-matrix (ADR-0031 §E table), enforced at authoring.
- **Field selectors** offer the **intersection of fields over the input set** (ADR-0031 §F),
  inferred statically (leaf kind → `Filter` preserves it → `field_of` remaps to the field's target).
  For `entity_ref` fields the offered picker domain is the **intersection of the slots' target
  kinds** (empty → the shared-formal warning, ADR-0032 §A).
- **Promote-in-place.** A Filter value slot's "promote" affordance binds the slot to a **named
  formal** (creates/reuses a `params` entry), **converts the current literal into that formal's
  `default`**, and renders the slot as a socket (ADR-0032). Un-promote restores an inline literal.

### 14.4 The `references` computed field + reverse index

**Field registration (ADR-0029).** Backlinks is surfaced as a built-in **catalog computed field** —
this is the *"backlinks when surfaced"* entry ADR-0029 already anticipated. Stable key **`references`**,
display label **"References"** (stable-key-vs-label, ADR-0029), category **computed**, value type
**node-set** (ADR-0029's first node-set-valued computed field — the one aspect it left implicit,
ADR-0031 §G). Like any catalog computed field it is **added/removed per type** (membership),
**reorderable and hideable/relabelable via `field_overrides` / `display_order`** (the "designable
move/hide in the field-types window" requirement, #118 pt 3), and its **definition is built-in / not
user-editable**. It reads read-only from the reverse index below. For designer handle-typing (§14.3)
a computed field **declares its value-type** (`references` → node-set) — a third payload-inference
source alongside ADR-0031 §D's *reference → node-set* / *scalar → value-set*.

**Reverse index (frontend, rebuildable).** A frontend structure `Map<targetId, Set<referrerId>>`,
built at load by **inverting the forward `entity_ref`/`entity_ref_list` adjacency over the full
roster** — the same in-memory inversion Nest performs (ADR-0028), promoted to a shared index. Its input is a
**shared cross-kind reference index** — for every node, only its forward `entity_ref`/`entity_ref_list`
**target ids** (spanning all kinds: a lore entry's referrers include scenes via `pov_ref`). This is
**distinct from the per-pane filtering rosters** (ADR-0034): those carry *full metadata for one kind*
(membership predicates); the reference index carries *per-node **display-summaries** + forward
ref-target-ids across all kinds* — **not** full metadata. The frontend loads it once from a **backend
load-time reference-graph payload** (per node: a display-summary — **id, title, entry_type, kind** —
plus its forward ref-target-ids) and inverts the adjacency. The same payload's **id→summary map
resolves referrer ids to renderable rows**, so the index is **self-contained** (no separate global
summary store needed). Build
cost O(nodes × ref-fields-per-node); it is **derived and rebuildable** (`.cache` class), rebuilt on
load and on any reference-mutating save (its caching policy is exactly "rebuild, never persist").
`references` is **any-field by construction** (it flattens all incoming reference fields); a
**field-specific** referenced-by ("scenes where Bob is POV") stays a forward `Filter(scenes, pov ∈
{Bob})` (ADR-0031 §G), so the index needs no per-field keying for this cut.

**Evaluation.** `field_of(of, references)` → for each node `n ∈ of`, `reverseIndex.get(n.id) ?? ∅`,
resolve ids → nodes, `flatMap` + dedup → a node-set. `field_of({ var: "$self" }, references)` is the
`$self`-backlinks case (UC1 / `BacklinksPanel`), now a synthetic view.

**Backend.** The forward-ref adjacency reaches the frontend as the **load-time reference-graph
payload** above (per node: a display-summary — id, title, entry_type, kind — plus forward
ref-target-ids) — computed once from the node index. The on-demand `/references/backlinks` scan (`references.py::list_backlinks`) is **not** on the
eval path (evaluation is frontend-side, ADR-0025); it is superseded for view evaluation and may remain
for non-view callers.

### 14.5 Not specified here (deferred — do not infer)

- Multi-hop `field_of → field_of` per-node inference — **single-hop cut** (ADR-0031): a `field_of`
  output feeds a terminal / set algebra / a Filter operand, not another type-aware node's input. The
  connection validator **rejects** a `field_of` whose `of` resolves (through the graph) from another
  `field_of`, enforcing the cut.
- The declared source Parameter node (ADR-0032, deferred — no use case yet).
- The concrete wire shape of the Draft-roster (a) enrichment (ADR-0034 — path decided; shape is an
  implementation detail).
