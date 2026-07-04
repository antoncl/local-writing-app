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

FieldPredicateOp = Literal["eq", "neq", "includes", "not_includes", "set", "unset"]


class FieldPredicate(BaseModel):
    """A `field` leaf: test a metadata field against a value. `op` set/unset test
    presence and ignore `value`; eq/neq compare scalars; includes/not_includes
    test collection membership. Authored via the field's own widget — no
    free-text DSL (doc §1.4)."""

    key: str = Field(min_length=1)
    op: FieldPredicateOp
    # A metadata value (str/int/float/bool/list/dict); kept loose to avoid a
    # models.py <-> models_views.py import cycle. Only structurally validated in
    # step 1 — there is no evaluator comparing it yet.
    value: Any = None


class AnnotatePayload(BaseModel):
    """Stamped by an `annotate` pass-through node (never filters). `label` drives
    hard grouping (`rank` orders the groups); `color` is a soft in-place tint on
    the existing NodeRow color-part system. At least one of label/color is set
    (enforced on ViewExpr). Doc §1.3, ADR-0019."""

    label: str | None = None
    color: str | None = None
    rank: int | None = None


class DifferenceOp(BaseModel):
    """The `difference` combinator: `keep` ∖ `remove`. Not commutative — the
    ports carry explicit roles (doc §1.2)."""

    keep: ViewExpr
    remove: ViewExpr


# The mutually-exclusive "primary" slots on a ViewExpr node: exactly one is set.
_VIEW_EXPR_PRIMARY_SLOTS: tuple[str, ...] = (
    "union",
    "intersect",
    "difference",
    "complement",
    "annotate",
    "type",
    "descendants_of",
    "tagged",
    "field",
    "hand_picked",
    "view_ref",
)


class ViewExpr(BaseModel):
    """One node in a view's set-algebra tree. Exactly one primary slot is set: a
    combinator (union / intersect / difference / complement), an `annotate`
    pass-through (paired with `of`), or a leaf (type / descendants_of / tagged /
    field / hand_picked / view_ref). Validated structurally — there is no
    evaluator in 0.5.0 step 1."""

    # Combinators
    union: list[ViewExpr] | None = None
    intersect: list[ViewExpr] | None = None
    difference: DifferenceOp | None = None
    complement: ViewExpr | None = None
    # Annotate pass-through: the payload plus the input set it forwards unchanged.
    annotate: AnnotatePayload | None = None
    of: ViewExpr | None = None
    # Leaves
    type: str | None = None  # exact entry_type FQN, e.g. "lore:character"
    descendants_of: str | None = None  # an entry_type FQN + every type inheriting it
    tagged: str | None = None  # a tag value
    field: FieldPredicate | None = None
    hand_picked: list[str] | None = None  # explicit node ids — the one static leaf
    view_ref: str | None = None  # a saved view node id (cycle-checked at save)

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


class ViewSpec(BaseModel):
    """A kind-anchored membership expression + ordering — the portable core of a
    view. Membership is EITHER a single `expr` (flat view) OR an ordered
    `groups` list (named handles → 2+ populated handles render as groups,
    ADR-0027). `expr`/`groups` both None = the whole universe of `kind` (the
    degenerate "all nodes of this kind" spec a kind-only picker source uses).
    Entry_type refs inside `expr` are FQN (#77). `sort` is the fallback when a
    group carries no per-segment sort."""

    kind: str = Field(min_length=1)
    expr: ViewExpr | None = None
    groups: list[ViewGroupSpec] | None = None
    sort: ViewSort | None = None

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


# Resolve the mutually-recursive forward refs (ViewExpr ↔ DifferenceOp, self).
DifferenceOp.model_rebuild()
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


class ViewNodeSummary(BaseModel):
    id: str
    title: str
    entry_type: str = "view:view"
    # The ViewSpec's anchor kind (the kind of nodes this view selects), surfaced
    # on the summary so a pane can group/offer views by the kind they target.
    view_kind: str = ""
    presentation: ViewPresentation = "flat"
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
