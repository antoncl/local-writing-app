# ADR-0041: `ViewExpr` is a language — one IDL grammar generates both runtimes; Filter becomes first-class

- Status: **Accepted** — 0.7.0, 2026-07-18
- Feature: #277 · Retires the hand-rolled walkers named there
- Amends: **ADR-0027 §B** (Filter promoted from layout-only sugar to a first-class stored
  operator), ADR-0018/0021 (the grammar is now defined once, not twice by hand), ADR-0025
  (the type checker joins the evaluator frontend-side)
- Extends: ADR-0031 (`field_of`'s output kind → a kind-parameterized payload-type lattice),
  ADR-0038 §B (predicate-leaf injector hiding stays a *palette* choice, orthogonal to the grammar)
- Lineage: ADR-0037 ("NF², after RASMUS") drew on RASMUS for the *operators*; this ADR extends
  that lineage to the grammar's *tooling and type system* (RASMUS generates its AST + visitor
  from one spec, and types its language as a set-lattice)

## Context

At project start we asserted "no domain-specific language." De facto we built one: `ViewExpr`
is a set-algebra / relational AST. Today it is **defined twice** — the Pydantic `ViewExpr`
(`models_views.py`) and the TS `ViewExpr` (`types.ts`), both hand-maintained, drifting
independently — and **walked ~4 times** by hand, each copy re-listing the slots: `walkViewExpr`,
the evaluator's `evalExpr` dispatch, `specToGraph.walk`, plus per-concern collectors. The bill
is concrete and recurring: the #260 `collectNests` value-operand gap, the #275/#276
`orphans_nest` slot half-added to one walker but not another. Every grammar change is N hand-edits
across two runtimes.

Writing the grammar down forces three questions the twin hand-written definitions let us dodge —
and the answers are the substance of this ADR: **is Filter an operator or sugar?** (0027 §B said
sugar; intent was operator), **what is a reference?** (bare `str`, but semantically a typed
pointer), **what does `field_of` produce?** (Nodes *or* Values, of *any* kind).

## Decision

**A. One IDL is the source of truth.** A single machine-readable grammar spec
(`view-grammar.yaml`) defines the language once. Generators emit the Pydantic model, the TS type,
a canonical `children(expr)` traversal for **both** runtimes, and the structural + scope
validators. The IDL is hand-edited; the emitted models are build artifacts. A slot cannot be
half-added across the FE/BE boundary because there is one boundary-crossing declaration, and the
generated traversal is **exhaustive** (an un-handled child edge is a generate-time error — the
#260/#276 failure class, killed structurally). This is the AST-generated-from-one-spec pattern
RASMUS uses (`AST.txt` → node types + visitor); we need its *middle-end* (typed AST + traversal
+ validation), not a lexer/parser — `ViewExpr` has no surface text syntax.

**B. The grammar is modeled prescriptively: a primitive core + derived operators.** The
primitive core is `union / intersect / difference / complement / nest / field_of / annotate` plus
the injectors (D). A **derived operator** is a first-class stored node whose *meaning* is a
declared lowering (`≝`) to the core; its evaluation, its type signature, and its round-trip all
derive from that one rewrite — no bespoke per-operator code in any walker.

**C. Filter is first-class *to the user*; its stored form is chosen for grammar economy
(refines ADR-0027 §B).** The **fixed invariant** is the UX and the user's mental model: Filter is a
first-class operation — you narrow a set, the same verb whether it sits on a leaf or after a union.
What the grammar does *behind that surface* — store Filter as its own node, or lower it to the core
(`intersect`/`difference` + injector) as 0027 §B specified — is an **implementation choice, decided
on one axis: which minimizes the scope, complexity, and maintainability of the grammar.** It is not
a mental-model commitment either way.

The mechanism that keeps that choice open is modelling Filter as a **derived operator with a
declared lowering** (B): its meaning is the one rewrite 0027 §B already wrote —

    filter{of: S, pred: P, mode: keep}  ≝  intersect(S, inject(P))
    filter{of: S, pred: P, mode: drop}  ≝  difference(keep: S, remove: inject(P))

— so its evaluation, typing, and round-trip derive from that single definition *regardless* of the
serialized form. Reducibility is thus preserved as the operator's *definition*, never as grounds to
erase it from the user's model; and the equivalence being declared, a fold/expand normalizer is
derivable either direction, never hand-rolled.

The economy axis has a thumb on the scale worth recording, but the ADR does not pre-empt the call:
0027 §B's lower-on-save path stores only the expanded core, so a Filter-over-a-real-set serializes
as a plain `intersect`/`difference` — **indistinguishable from a user's explicit intersect**, its
Filter identity surviving a round-trip *only* through the *non-semantic* persisted `layout` (which
`hydrateGraph` reopens directly, bypassing `specToGraph`). A layout-less or backend-authored view
therefore **loses that identity entirely**, reopening as a bare combinator — a standing surface↔core
drift source. (Note precisely: `specToGraph` has **no** `intersect(S, leaf)`→`Filter(S)`
reconstruction to lean on; the only load-time canonicalization is the *leaf-level* bare-predicate →
`All → Filter` rewrite of ADR-0038 §B, a separate, deterministic, lossless mechanism that is
**retained** — the predicate leaves stay the §D injectors Filter's `pred` points at.) Serializing
the `filter` node moves that identity **into the grammar**, so a layout-less view reopens with its
Filter transforms intact — a maintainability win *for the grammar*, so the economy criterion likely
favours the stored-node form. The implementation makes the final serialization call on that basis;
the ADR fixes the **invariant** (user-facing first-classness) and the **mechanism** (derived
operator + declared lowering), not the byte layout.

**D. Injector is a *derived* role (set-arity 0), not a node type — pin this precisely, because it
is exactly the kind of context-dependent call an implementing thread can get wrong.** An operator's
**set-arity** is the number of **declared set-valued input ports** it has — inputs wired to carry a
node/value *set* produced by another expression. Optional ports count. Set-arity is a fixed
structural fact *per operator kind*, **not** a property of a particular node instance's wiring. It
counts *only* set-input ports; it does **not** count:

- value / config fields — `field_of.field`, `Filter.pred`, `NestMatch.*`, sort keys;
- literal operands;
- **by-id references** — `orphans_of` names a Nest via `ref(nest_id)`, and `hand_picked` names
  nodes via `ref(node)`; a reference resolved elsewhere is **not** a set-input port;
- a predicate `value` that embeds a `field_of` — that is a *nested sub-expression*, not a
  set-input port of the predicate.

| operator | set-arity | ports |
|---|---|---|
| `union` / `intersect` | n | the operand list |
| `difference` | 2 | `keep`, `remove` |
| `nest` | 2 | `parents?`, `children?` (both optional, still 2 ports) |
| `complement` / `field_of` / `annotate` / `Filter` | 1 | `of` |
| `all` | 0 | — |
| `type` / `descendants_of` / `tagged` / `field` (predicate leaves) | 0 | — |
| `hand_picked` | 0 | — (ids are refs, not ports) |
| `var` / `$self` | 0 | — |
| `orphans_of` | 0 | — (`nest_id` is a ref, not a port) |

**"Injector" ≡ the derived predicate `set-arity == 0`.** It is emphatically **not** a stored field,
a base class, or a node type: the emitted models contain no `Injector` type. Any code that needs
"the injectors" computes `operators where set_arity == 0` — which *includes* `orphans_of` and
*excludes* a `nest` whose two handles happen to be unwired (that is a 2-arity `nest` with nothing
connected, still a `nest`, never an injector).

**`field_of`'s "source role" is a palette affordance, outside the grammar.** In the grammar
`field_of` is arity-1, always. That the designer may *offer* it as a starting node when rooted at
`$self`/`All` is a UI decision (ADR-0038 §B territory) and must **not** leak into the grammar as a
special case. Likewise 0038 §B's hiding of the redundant predicate-leaf injectors is a **palette**
decision, orthogonal to the grammar; the hidden leaves are retained precisely as the targets of
Filter's rewrite (`inject(P)`). **Implementer rule: model set-arity as the table above; derive
"injector" from it; keep every role/palette judgment in the designer layer.**

**E. Payload types are kind-parameterized; `field_of` has a dependent signature (extends
ADR-0031).** The type domain is not a flat `{NodeSet, ValueSet}` tag but `NodeSet<K>` (K a kind
FQN, or `*` for heterogeneous / off-anchor) and `ValueSet<T>`, ordered as a lattice
(`NodeSet<lore:character> ⊆ NodeSet<*>`); a position accepts a set-type and the check is
`produced ⊆ accepted` (RASMUS's `subset`). `field_of`'s signature is genuinely dependent —
`of: NodeSet<_>, field: F  →  NodeSet<target_kind(F)>` for a reference field, `ValueSet<scalar(F)>`
for a scalar — resolved from the field's schema. Off-anchor node-sets already occur today
(`field_of(References)` from a drafts view yields lore entries) and must be *representable and
type-checkable*, so the kind must live in the type from the outset.

**F. Generated now vs. declared-but-deferred.** Generated in #277: the types, `children()`, and
the structural + scope validators — including the parked #275 `orphans_of` ↔ `orphans_nest.id`
consistency check, now one declared rule rather than a fifth hand-rolled validator. **Declared in
the IDL but not yet consumed:** the kind-parameterized type signatures and the `ref(domain)`
classifications (node / field / nest_id / param). **Deferred, in two different senses:** the
inferring type-checker that resolves `field_of` against the schema is *preferably* deferred to its
own issue — but it may prove **required** once implementation goes deeper (e.g. the evaluator or the
designer needs `produced ⊆ accepted` to reject an ill-typed composition), so it is deferred with
eyes open: the IDL declares the signatures + `ref(domain)`s precisely enough that the checker can be
built *without reshaping the spec* whenever it is needed. **Multi-kind result rendering** — a view
whose result rows span kinds, with per-kind self-render — is firmly Views-2.0 flow-model frontier
and out of scope. #277 makes an off-anchor intermediate *representable and (later) checkable*; it
renders no multi-kind result.

**G. Bootstrapping safety net.** The unchanged primitive core must regenerate **byte-identical**
to today's hand-written `models_views.py` / `types.ts` (a `git diff`-empty acceptance test) before
the IDL is used to *evolve* anything. If Filter is serialized first-class (C's economy-favoured
form) — the one part that would change the stored shape — that change is validated by **semantic
equivalence**: a Filter evaluated via its declared rewrite yields the same set as today's
`intersect`/`difference` + leaf encoding. Prove reproduction, then evolve.

## Why / rejected alternative

- **Rejected: option A — the Pydantic model as source, JSON-Schema → TS, `children()` inferred.**
  Cheapest (Pydantic already emits JSON Schema), but the loose slots (`field.value`, the
  `{var}`/`{field_of}` tagged unions carried in prose comments) emit as `any`/`unknown` — a TS
  type *weaker than today's hand-written one*, a regression — and `children()` inference over
  `$ref`s is fragile exactly at the operand-buried `field.value.field_of.of`. It cannot express
  `field_of`'s dependent, kind-parameterized signature at all. The interesting part of the language
  is its *type system*, and only a declared model carries it.
- **Rejected: descriptive modeling** (reproduce the current stored slots verbatim, Filter stays
  dissolved). Single-sources the machinery but bakes in the 0027 §B inversion — operator identity
  in layout, heuristic reconstruction — leaving the very surface↔core drift #277 exists to kill.
- **Rejected: Filter as an irreducible primitive.** Would need bespoke Filter evaluation, typing,
  and round-trip in every walker (more drift, not less) and discards the reducibility that lets its
  meaning be single-sourced. Derived-with-declared-lowering buys first-classness *and* one
  definition.

## Consequences

- **The surface/core split collapses to one grammar.** With derived operators carrying declared
  lowerings, the surface→core lowering becomes "expand derived → primitive," *generated* from those
  lowerings rather than hand-written — one grammar with a primitive/derived distinction, not two
  grammars plus a desugaring relation. And **if** Filter is serialized first-class (C's
  economy-favoured form), a Filter-over-a-real-set's identity lives in the grammar rather than the
  non-semantic `layout`, so a layout-less / backend-authored view reopens with its Filter transforms
  intact instead of as a bare combinator — the maintainability payoff that drives that serialization
  choice. This retires **no** `specToGraph` intersect→Filter reconstruction (there is none); the
  leaf-level bare-predicate → `All → Filter` canonicalization (ADR-0038 §B) is a distinct mechanism
  and is retained.
- **The #275 `orphans_of`/`orphans_nest` companion wart is re-examined** under the injector-role
  framing (orphans as a source may not need the inline-`orphans_nest` companion) — flagged for the
  modelling pass, not committed here.
- **Pre-1.0, no migration** (project policy): promoting Filter changes the stored shape; test
  projects are recreated, no defensive reads.
- **The deferred frontier is named, not solved.** Multi-kind result rendering is a firm non-goal
  (Views 2.0); the inferring type-checker is deferred but flagged as a **likely-required**
  follow-on (F), with the spec shaped so it needs no reshaping when the time comes. This ADR locks
  the foundation and *enumerates* the type-system edge rather than resolving the whole type system
  in one stroke.
- **`adr/README.md` is intentionally not indexed here** — the #7 thread holds uncommitted index
  changes in the main worktree; 0041 is added to the index alongside 0039/0040 when that lands.
