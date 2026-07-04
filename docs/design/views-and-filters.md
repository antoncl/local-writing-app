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

A view is **anchored to one kind**. Its universe — what complement is relative to — is
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
  comparison DSL.
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
deferred to a later slice, deliberately.

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
- Membership-filtering the Draft tree (§3.1 — color annotations only).
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
- Views are kind-anchored; universe = all nodes of the kind (§1.1).
- Saved views are frontmatter-only nodes; ViewSpec is the portable core (§2).
- Every NodeList is backed by a view; presentation ∈ {tree, grouped, flat} (§3).
- NodePickerConfig = sources (ViewSpecs/refs) + mechanics (§6.1).
- Assistant dynamic default = topmost matching; ★ flag retired (§6.3).
- Type-aware Jinja helpers on a shared ancestry primitive (§8.1).
- **The approachable flow: injectors, filters, named-handle grouping, denormalized output
  (§12; ADR-0027 — amends set-algebra/annotate/sort ADRs, #91).**

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
