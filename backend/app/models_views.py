"""View models — the ViewSpec membership language + saved-view node (0.5.0, #78).

Split out of `models.py` (which is at the file-size cap): a cohesive slice
covering the ViewSpec set-algebra grammar, the `NodePickerConfig` picker config
(membership `sources` + mechanics), the degenerate `sources` <-> legacy
`(kinds, entry_types)` reducers, and the frontmatter-only `view` node models.
Re-exported from `models.py`, so `from app.models import NodePickerConfig,
ViewSpec, ...` keeps resolving.

A ViewSpec is (kind, expr, sort): a kind-anchored set-algebra expression over
the project's nodes plus an ordering. Two carriers — a saved `view` node
(frontmatter-only, folder `views/`) and an inline anonymous spec embedded as a
NodePickerConfig source. `expr` is a recursive tree; entry_type references
serialize as FQN (`lore:character`, per #77). See docs/design/
views-and-filters.md §1–2 and ADR-0018/0019/0021/0023.

0.5.0 step 1 / #78 lands the *storage format + structural validation only* —
there is no evaluator yet. Panes render their existing hardcoded shapes and
pickers keep filtering by kind/entry_type via the degenerate-source reducer
(`_sources_membership`), which reads back the `{kinds, entry_types}` subset a
kind-only-or-type-leaf source encodes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# The op enum collapsed 6→4 for the forward model (ADR-0031 §E, #184): `eq`+
# `includes` → `overlap` (set-coerce both sides, test non-empty intersection),
# `neq`+`not_includes` → `disjoint` (its negation), `set`/`unset` kept. An
# `entity_ref` field compares by id, a scalar by value. No migration of stored
# old-op values — test projects are recreated (pre-1.0).
FieldPredicateOp = Literal["overlap", "disjoint", "set", "unset"]


class FieldPredicate(BaseModel):
    """A `field` leaf: test a metadata field against an operand. `op` set/unset
    test presence and ignore `value`; overlap/disjoint set-coerce both sides and
    test (non-)intersection (ADR-0031 §E). Authored via the field's own widget —
    no free-text DSL (doc §1.4)."""

    key: str = Field(min_length=1)
    op: FieldPredicateOp
    # The operand: EITHER a bare metadata literal (str/int/float/bool/list) OR a
    # tagged operand — `{"var": name}` (a promoted formal or the reserved
    # `$self`) or `{"field_of": {...}}` (a forward projection, #184 §14.1). Kept
    # loose (`Any`) — the two shapes are mutually exclusive and the frontend
    # evaluator dispatches on shape (no evaluator here; backend is structural).
    value: Any = None


class FieldOfOp(BaseModel):
    """`field_of` — forward projection (ADR-0031 §D, #184): `flatMap(of, n →
    valuesOf(n, field))`, deduped. `of` is the input set (any ViewExpr — a leaf,
    a `$self` var, set algebra); `field` is the projected key. The output payload
    is INFERRED, never stored: a reference field yields a node-set, a scalar field
    a value-set. Appears as a standalone ViewExpr (feeds set algebra / the render
    wrapper) or inline in a predicate `value` (same-field/same-value matching)."""

    of: ViewExpr
    field: str = Field(min_length=1)


class AnnotatePayload(BaseModel):
    """Stamped by an `annotate` pass-through node (never filters). `color` is a
    soft in-place tint on the existing NodeRow color-part system (Highlight).
    `label`/`rank` are INERT since #91/ADR-0027 — grouping is now the View's
    named handles (`ViewSpec.groups`), not annotate label+rank. The fields are
    retained only so an existing spec round-trips; do NOT re-wire grouping off
    them (that reintroduces the rank/predicate power-user trap #91 rejected). At
    least one of label/color is set (enforced on ViewExpr). Doc §1.3, §12."""

    label: str | None = None
    color: str | None = None
    rank: int | None = None


class DifferenceOp(BaseModel):
    """The `difference` combinator: `keep` ∖ `remove`. Not commutative — the
    ports carry explicit roles (doc §1.2)."""

    keep: ViewExpr
    remove: ViewExpr


NestDirection = Literal["child_to_parent", "parent_to_children"]
NestMatchBy = Literal["ref", "title"]


class NestMatch(BaseModel):
    """The parameterized link rule a `nest` denormalizes (ADR-0028 §B). The three
    ways a writer expresses a parent/child link collapse to one rule with two
    axes: `direction` — which card holds the link (`child_to_parent`: the child
    holds an `entity_ref` to its parent; `parent_to_children`: the parent holds
    the refs) — and `by` — `ref` (an `entity_ref`/id field) or `title` (the
    child's tag equals the parent's title). `field` names the metadata field
    carrying the link. `context_pick` fields are deliberately NOT joinable
    (per-prompt runtime, not authored structure, ADR-0028 § Consequences); that
    exclusion is enforced at authoring time by the match-rule picker (field-type
    info isn't reachable here — the same reason `FieldPredicate.value` stays
    loose)."""

    field: str = Field(min_length=1)
    direction: NestDirection
    by: NestMatchBy = "ref"


class NestOp(BaseModel):
    """The `nest` operator: denormalize a user-authored tree out of the links
    writers already put in their lore (ADR-0028). Two role-carrying inputs —
    `parents` (seed the roots) and `children` (the candidate set) — plus a match
    rule; each child that matches a parent emits a `(node, path)` row whose path
    gains a real-node parent segment. `recursive` marks the canvas self-loop
    (output → own parents handle) that iterates a frontier BFS to traverse an
    unknown-depth homogeneous hierarchy (a family tree, nested Locations). A
    FIRST-CLASS relational operator, not sugar: it produces paths from data
    relationships that set-membership leaves cannot express, so — unlike the
    ADR-0027 Filters — it does NOT lower to set algebra (§F).

    `parents`/`children` are optional: an unconnected handle means the whole
    universe (the evaluator's `null expr = universe` convention). Seed `parents`
    with the roots (a `field: {op: unset}` leaf) for a clean tree; leaving it the
    universe yields a *thicket* (a subtree rooted at every node, ADR-0028 §C).
    `match` is required — without a rule there is no join.

    `orphans` (ADR-0037, #216): what happens to a candidate child that matched
    no parent — "drop" (the default; counted in diagnostics) or "keep" (the
    orphan stays at the root as a bare row — the who-lives-where pattern)."""

    parents: ViewExpr | None = None
    children: ViewExpr | None = None
    match: NestMatch
    recursive: bool = False
    orphans: Literal["keep", "drop"] | None = None


# The mutually-exclusive "primary" slots on a ViewExpr node: exactly one is set.
_VIEW_EXPR_PRIMARY_SLOTS: tuple[str, ...] = (
    "union",
    "intersect",
    "difference",
    "complement",
    "nest",
    "annotate",
    "field_of",
    "type",
    "descendants_of",
    "tagged",
    "field",
    "hand_picked",
    "view_ref",
    "var",
)


class ViewExpr(BaseModel):
    """One node in a view's set-algebra tree. Exactly one primary slot is set: a
    combinator (union / intersect / difference / complement), the `nest`
    relational operator (ADR-0028; produces denormalized parent/child rows, not
    just a set), an `annotate` pass-through (paired with `of`), or a leaf (type /
    descendants_of / tagged / field / hand_picked / view_ref). Validated
    structurally — the backend has no evaluator (eval is frontend-side)."""

    # Combinators
    union: list[ViewExpr] | None = None
    intersect: list[ViewExpr] | None = None
    difference: DifferenceOp | None = None
    complement: ViewExpr | None = None
    # Nest: relational join → denormalized parent/child rows (ADR-0028). Carries
    # its own inputs (parents/children), like `difference` — not via `of`.
    nest: NestOp | None = None
    # Annotate pass-through: the payload plus the input set it forwards unchanged.
    annotate: AnnotatePayload | None = None
    of: ViewExpr | None = None
    # Field projection (#184, ADR-0031 §D): project the input set through a field.
    # A set-producing operator, like the combinators — not paired via `of`.
    field_of: FieldOfOp | None = None
    # Leaves
    type: str | None = None  # exact entry_type FQN, e.g. "lore:character"
    descendants_of: str | None = None  # an entry_type FQN + every type inheriting it
    tagged: str | None = None  # a tag value
    field: FieldPredicate | None = None
    hand_picked: list[str] | None = None  # explicit node ids — the one static leaf
    view_ref: str | None = None  # a saved view node id (cycle-checked at save)
    # A free variable / reserved source leaf (#184, ADR-0032): `{"var": "$self"}`
    # is the anchored node (surface-supplied via bindings); a user-declared name
    # is a promoted formal. Resolves from `EvalContext.bindings` at eval time; in
    # an `of`/leaf position it is a singleton node-set (empty when unresolved).
    var: str | None = None

    @model_validator(mode="after")
    def _exactly_one_primary(self) -> ViewExpr:
        present = [s for s in _VIEW_EXPR_PRIMARY_SLOTS if getattr(self, s) is not None]
        if len(present) != 1:
            raise ValueError(
                "a view expression must set exactly one of "
                f"{list(_VIEW_EXPR_PRIMARY_SLOTS)}; got {present or ['none']}"
            )
        slot = present[0]
        if slot == "annotate":
            if self.of is None:
                raise ValueError("an `annotate` node requires an `of` input expression")
            if self.annotate.label is None and self.annotate.color is None:
                raise ValueError("an `annotate` payload must set at least one of label/color")
        elif self.of is not None:
            raise ValueError("`of` is only valid paired with `annotate`")
        if slot in ("union", "intersect") and not getattr(self, slot):
            raise ValueError(f"`{slot}` requires at least one operand")
        return self


class ViewSort(BaseModel):
    """View ordering, orthogonal to membership (doc §1.5). `by`: "manual" =
    stored/drag order (load-bearing for Assistants), "title" = by node title,
    "field" = by `field_key`. `dir` applies to title/field. Sort applies within
    each annotate group."""

    by: Literal["manual", "title", "field"] = "manual"
    field_key: str | None = None
    dir: Literal["asc", "desc"] = "asc"

    @model_validator(mode="after")
    def _field_key_present(self) -> ViewSort:
        if self.by == "field" and not self.field_key:
            raise ValueError('a sort by "field" requires `field_key`')
        return self


class ViewGroupSpec(BaseModel):
    """One named group = one named input handle on the View node (ADR-0027
    §D/§E, #91). `name` is the group label and the row `path` segment; `expr` is
    the group's membership (None = the whole universe); `sort` sorts this
    segment; `color` is an optional group tint. Group order = handle order = the
    `groups` list order; same-name handles union + dedupe in the evaluator."""

    name: str = Field(min_length=1)
    expr: ViewExpr | None = None
    sort: ViewSort | None = None
    color: str | None = None


class ViewParam(BaseModel):
    """A declared runtime formal (#184, ADR-0032): a promoted Filter value slot.
    `name` is the stable key `{"var": name}` operands reference; `label` is the
    parameter-strip UI; `default` is the authored OVERRIDABLE default (null/absent
    ⇒ unbound ⇒ its predicate is inactive until the user picks). **No `type` is
    stored** — a param's type is recomputed at load from the field(s) whose slot
    references it (the intersection rule, ADR-0031 §F), single source of truth.
    `$self` is reserved (surface-supplied) and never appears in a params list."""

    name: str = Field(min_length=1)
    label: str = ""
    # The overridable default operand — a literal in the field's stored shape
    # (e.g. a list of ids for entity_ref). Loose for the same reason as
    # `FieldPredicate.value`.
    default: Any = None


class ViewGroupByLevel(BaseModel):
    """One ADR-0037 §2 organize level — ν by attribute, on the result. `field`
    is any groupable field of the input set's kind (enum/select, the intrinsic
    entry_type, a reference field → real-node buckets; a multi-valued field
    fans a row out under each value; a missing value leaves the row bare at the
    level). Bucket order is first-seen in row order unless `order: "label"`
    opts into alphabetical-by-label. The backend stores levels verbatim and
    never evaluates them (ADR-0025)."""

    field: str = Field(min_length=1)
    order: Literal["label"] | None = None


class ViewSpec(BaseModel):
    """A kind-anchored membership expression + ordering — the portable core of a
    view. Membership is EITHER a single `expr` (flat view) OR an ordered
    `groups` list (named handles → 2+ populated handles render as groups,
    ADR-0027). `expr`/`groups` both None = the whole universe of `kind` (the
    degenerate "all nodes of this kind" spec a kind-only picker source uses).
    Entry_type refs inside `expr` are FQN (#77). `sort` is the fallback when a
    group carries no per-segment sort. `params` declares runtime formals (#184);
    a view with none is the degenerate closed case (existing views are unchanged).
    `group_by` (ADR-0037 §2) is the ordered organize-level list — orthogonal to
    the expr-XOR-groups rule (handles compose: handles outermost, levels
    innermost)."""

    kind: str = Field(min_length=1)
    expr: ViewExpr | None = None
    groups: list[ViewGroupSpec] | None = None
    sort: ViewSort | None = None
    params: list[ViewParam] | None = None
    group_by: list[ViewGroupByLevel] | None = None

    @model_validator(mode="after")
    def _expr_xor_groups(self) -> ViewSpec:
        if self.expr is not None and self.groups is not None:
            raise ValueError(
                "a ViewSpec sets either `expr` (flat) or `groups` (named handles), not both"
            )
        return self


class ViewRef(BaseModel):
    """A picker source that references a saved view node by id (the view carries
    its own kind + expr). Doc §6.1."""

    view: str = Field(min_length=1)


# Resolve the mutually-recursive forward refs (ViewExpr ↔ DifferenceOp/NestOp/
# FieldOfOp, self).
DifferenceOp.model_rebuild()
NestOp.model_rebuild()
FieldOfOp.model_rebuild()
ViewExpr.model_rebuild()


# A picker membership source is either an inline ViewSpec or a saved-view ref.
# Order matters for the smart union: a bare `{view: ...}` fails ViewSpec (no
# `kind`) and resolves to ViewRef; a `{kind: ...}` fails ViewRef (no `view`).
ViewSource = ViewSpec | ViewRef


def _view_expr_entry_type_leaves(expr: ViewExpr | None) -> list[str] | None:
    """Reduce an `expr` to the exact entry_type FQNs it whitelists, or None when
    it isn't a kind-only / type-leaf / union-of-type-leaves shape (the only
    forms the pre-evaluator degenerate reducer understands). None = "no
    entry_type constraint" (any type of the kind allowed)."""

    if expr is None:
        return None
    if expr.type is not None:
        return [expr.type]
    if expr.union is not None and all(child.type is not None for child in expr.union):
        return [child.type for child in expr.union if child.type is not None]
    return None


def _sources_membership(
    sources: list[ViewSource],
) -> tuple[list[str], dict[str, list[str]]]:
    """Degenerate reducer: read a `sources` list back as the legacy
    `(kinds, entry_types)` membership subset, so pre-evaluator picker/tag-scope
    filtering keeps working unchanged (0.5.0 step 1). Non-degenerate exprs and
    view-refs contribute their kind (when known) with no entry_type constraint."""

    kinds: list[str] = []
    entry_types: dict[str, list[str]] = {}
    for source in sources:
        if not isinstance(source, ViewSpec):
            continue  # view-refs can't be resolved without loading the view
        if source.kind not in kinds:
            kinds.append(source.kind)
        leaves = _view_expr_entry_type_leaves(source.expr)
        if leaves:
            bucket = entry_types.setdefault(source.kind, [])
            for fqn in leaves:
                if fqn not in bucket:
                    bucket.append(fqn)
    return kinds, entry_types


def _membership_to_sources(
    kinds: list[str], entry_types: dict[str, list[str]]
) -> list[ViewSpec]:
    """Inverse of `_sources_membership`: build one degenerate ViewSpec source per
    kind. A kind with an entry_type whitelist becomes a `type` leaf (single) or a
    `union` of type leaves; a kind without one becomes a kind-only spec (no
    expr). Deterministic so equal membership yields equal sources (tag-scope
    change detection compares serialized scopes)."""

    ordered_kinds = list(dict.fromkeys([*kinds, *entry_types.keys()]))
    sources: list[ViewSpec] = []
    for kind in ordered_kinds:
        fqns = entry_types.get(kind) or []
        if not fqns:
            sources.append(ViewSpec(kind=kind))
        elif len(fqns) == 1:
            sources.append(ViewSpec(kind=kind, expr=ViewExpr(type=fqns[0])))
        else:
            sources.append(
                ViewSpec(kind=kind, expr=ViewExpr(union=[ViewExpr(type=f) for f in fqns]))
            )
    return sources


class NodePickerConfig(BaseModel):
    """Per-field constraint for which nodes the picker offers. Split into
    **membership** (`sources`: one ViewSpec-or-view-ref per kind, unioned) and
    **mechanics** (`multiple` / `allow_target_marking` / `presets`) per ADR-0023.
    Serialized both for entity_ref metadata fields' `picker_config` and for the
    context_pick prompt input `target`.

    0.5.0 step 1 stores the new `sources` shape but has no evaluator: the legacy
    `kinds` / `entry_types` accessors below reduce a degenerate source list so
    existing filtering keeps working. Construct from the legacy pair with
    `NodePickerConfig.from_membership(...)`."""

    # Membership: one ViewSpec-or-ref per kind (union across sources).
    sources: list[ViewSource] = Field(default_factory=list)
    # Presets a context-pick UI may surface (full_outline, full_text…). Mechanics.
    presets: list[str] = Field(default_factory=list)
    # Multi-pick. None defers to the field type (entity_ref → false,
    # entity_ref_list → true).
    multiple: bool | None = None
    # Author opt-in for context-pick target-marking.
    allow_target_marking: bool | None = None

    @property
    def kinds(self) -> list[str]:
        """Legacy read accessor — the kinds the `sources` whitelist. Read-only
        (not serialized); membership lives in `sources`."""
        return _sources_membership(self.sources)[0]

    @property
    def entry_types(self) -> dict[str, list[str]]:
        """Legacy read accessor — the per-kind entry_type FQN whitelist the
        `sources` encode. Read-only (not serialized)."""
        return _sources_membership(self.sources)[1]

    @classmethod
    def from_membership(
        cls,
        *,
        kinds: list[str] | None = None,
        entry_types: dict[str, list[str]] | None = None,
        presets: list[str] | None = None,
        multiple: bool | None = None,
        allow_target_marking: bool | None = None,
    ) -> NodePickerConfig:
        """Build a config from the legacy `(kinds, entry_types)` membership pair,
        encoding it as degenerate `sources`. Mechanics pass through."""
        return cls(
            sources=_membership_to_sources(kinds or [], entry_types or {}),
            presets=presets or [],
            multiple=multiple,
            allow_target_marking=allow_target_marking,
        )


# --- Saved views: the frontmatter-only `view` node -----------------------
#
# A saved view is a frontmatter-only Node of kind `view` (folder `views/`,
# no prose body), carrying a ViewSpec + a presentation hint. Storage mirrors
# mutation sets — the spec lives in front matter via `_write_node_entry_file`'s
# `extra=`. `spec.kind` is the ViewSpec's *anchor* kind (which kind of nodes the
# view selects), distinct from the node's own `view` kind. ADR-0021, doc §2/§3.
ViewPresentation = Literal["tree", "grouped", "flat"]


class ViewLayoutNode(BaseModel):
    """A designer node's visual state: its kind, canvas position, and config.
    Persisted so reopening restores the exact graph the author arranged rather
    than re-deriving a fresh auto-layout from the semantic `expr`. `cfg` is the
    node's ViewNodeData (kept loose — non-semantic designer state)."""

    id: str
    kind: str
    position: dict[str, float] = Field(default_factory=dict)
    cfg: dict[str, Any] = Field(default_factory=dict)


class ViewLayoutEdge(BaseModel):
    id: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None


class ViewLayout(BaseModel):
    """The view designer's visual graph (nodes + edges). Non-semantic
    presentation state parallel to `presentation`; the evaluator ignores it and
    it lives off `ViewSpec` (the portable semantic core) on purpose. Absent for
    views authored without the designer — the frontend falls back to laying the
    `expr` out automatically."""

    nodes: list[ViewLayoutNode] = Field(default_factory=list)
    edges: list[ViewLayoutEdge] = Field(default_factory=list)


class ViewUiState(BaseModel):
    """Non-semantic per-view UI state — a presentation sibling of `spec`, like
    `layout` (ADR-0036). Today just the collapsed group set for a ViewNodeList;
    the extension point for future per-view UI (scroll, density). The backend
    stores `collapsed` VERBATIM — it never parses a key, never evaluates, never
    prunes (ADR-0025: views evaluate frontend-side); the frontend owns pruning
    inert keys. Written/read on the lock-free `/ui` endpoint, independent of the
    spec revision-lock so a fold toggle never contends with a designer save."""

    # Collapsed ViewGroup.key set (`node:<id>` / `group:<seg>`); absent ⇒ expanded.
    collapsed: list[str] = Field(default_factory=list)


class ViewNodeSummary(BaseModel):
    id: str
    title: str
    entry_type: str = "view:view"
    # The ViewSpec's anchor kind (the kind of nodes this view selects), surfaced
    # on the summary so a pane can group/offer views by the kind they target.
    view_kind: str = ""
    presentation: ViewPresentation = "flat"
    # The full spec, so a client that lists views already holds everything it
    # needs to evaluate them (incl. resolving view_ref leaves) without a second
    # per-view fetch — list_views already parses it (#95). None if malformed.
    spec: ViewSpec | None = None
    # ADR-0036: fold/ui state ships with the list so a pane seeds collapse without
    # a per-view fetch (None ⇒ no persisted state yet).
    ui: ViewUiState | None = None
    # ADR-0036: a system-provided default view — read-only (copyable, not
    # editable); the pane's implicit "Default" entry, always listed.
    system: bool = False
    source_layer_id: str = ""
    source_layer_label: str = ""


class ViewNode(BaseModel):
    id: str
    title: str
    revision: str
    entry_type: str = "view:view"
    spec: ViewSpec
    presentation: ViewPresentation = "flat"
    # Designer canvas layout (positions + wiring). None for views never opened
    # in / saved from the designer — the frontend auto-lays-out the expr then.
    layout: ViewLayout | None = None
    # ADR-0036: fold/ui state (collapsed groups). None until first `/ui` write.
    ui: ViewUiState | None = None
    # ADR-0036: system-provided read-only default view (Duplicate-not-Edit).
    system: bool = False
    source_layer_id: str = ""
    source_layer_label: str = ""


class ViewNodeList(BaseModel):
    entries: list[ViewNodeSummary] = Field(default_factory=list)


class CreateViewRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = "view:view"
    spec: ViewSpec
    presentation: ViewPresentation = "flat"
    layout: ViewLayout | None = None


class SaveViewRequest(BaseModel):
    title: str = Field(min_length=1)
    base_revision: str | None = None
    entry_type: str = "view:view"
    spec: ViewSpec
    presentation: ViewPresentation = "flat"
    layout: ViewLayout | None = None


class UpdateViewUiRequest(BaseModel):
    """Body for the lock-free `PUT /api/views/{id}/ui` (ADR-0036). Carries ONLY
    the fold/ui state — never `spec`/`revision`, so a fold toggle can't 409
    against a concurrent designer save. For a `view_default_<kind>` id the node
    is materialized on first write."""

    ui: ViewUiState = Field(default_factory=ViewUiState)
