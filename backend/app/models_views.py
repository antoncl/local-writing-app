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

# The ViewExpr grammar is machine-generated from the view-grammar IDL (#277,
# ADR-0041). Edit scripts/viewgrammar/view-grammar.yaml and regenerate; do not
# hand-write these here. See scripts/viewgrammar/README.md for the stable surface.
from app.view_grammar_generated import ViewExpr


class ViewSort(BaseModel):
    """View ordering, orthogonal to membership (doc §1.5). `by`: "manual" =
    stored/drag order (load-bearing for Assistants), "title" = by node title,
    "field" = by `field_key`. `dir` applies to title/field. `then` is the #230
    multi-level tiebreaker chain (sort by A, then B, …) — the single-key form
    (no `then`) is unchanged. The backend stores the chain verbatim and never
    evaluates it. Sort applies within each annotate group."""

    by: Literal["manual", "title", "field"] = "manual"
    field_key: str | None = None
    dir: Literal["asc", "desc"] = "asc"
    then: ViewSort | None = None

    @model_validator(mode="after")
    def _field_key_present(self) -> ViewSort:
        if self.by == "field" and not self.field_key:
            raise ValueError('a sort by "field" requires `field_key`')
        return self


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


class ViewGroupSpec(BaseModel):
    """One named group = one named input handle on the View node (ADR-0027
    §D/§E, #91). `name` is the group label and the row `path` segment; `expr` is
    the group's membership (None = the whole universe); `sort` sorts this
    segment; `color` is an optional group tint. `group_by` is this group's own
    organize levels (ADR-0037 Amendment 1 — each group organizes independently).
    Group order = handle order = the `groups` list order; same-name handles
    union + dedupe in the evaluator."""

    name: str = Field(min_length=1)
    expr: ViewExpr | None = None
    sort: ViewSort | None = None
    color: str | None = None
    group_by: list[ViewGroupByLevel] | None = None


class ViewParam(BaseModel):
    """A declared runtime formal (#184, ADR-0032): a promoted Filter value slot.
    `name` is the stable key `{"var": name}` operands reference; `label` is the
    parameter-strip UI; `default` is the authored OVERRIDABLE default (null/absent
    ⇒ unbound ⇒ its predicate is inactive until the user picks). **No `type` is
    stored** — a param's type is recomputed at load from the field(s) whose slot
    references it (the intersection rule, ADR-0031 §F), single source of truth."""

    name: str = Field(min_length=1)
    label: str = ""
    # The overridable default operand — a literal in the field's stored shape
    # (e.g. a list of ids for entity_ref). Loose for the same reason as
    # `FieldPredicate.value`.
    default: Any = None


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
    # Only a STRING type leaf is a static entry_type whitelist. A promoted
    # `{"var": ...}` type leaf (ADR-0038 §C Amendment 1) is a parameterized source,
    # not a fixed set — it has no degenerate (kinds, entry_types) reduction.
    if isinstance(expr.type, str):
        return [expr.type]
    if expr.union is not None and all(isinstance(child.type, str) for child in expr.union):
        return [child.type for child in expr.union if isinstance(child.type, str)]
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
# A saved view is a frontmatter-only Node of kind `view` (folder `views/`, no
# prose body), carrying a ViewSpec. Storage mirrors mutation sets — the spec
# lives in front matter via `_write_node_entry_file`'s `extra=`. `spec.kind` is
# the ViewSpec's *anchor* kind (which kind of nodes the view selects), distinct
# from the node's own `view` kind. ADR-0021, doc §2/§3. (Grouping/tree layout is
# the view's own shape — `group_by` + Nest — never a presentation hint: ADR-0037
# §3 eradicated `ViewPresentation`.)


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
    """The view designer's visual graph (nodes + edges). Non-semantic designer
    state; the evaluator ignores it and it lives off `ViewSpec` (the portable
    semantic core) on purpose. Absent for views authored without the designer —
    the frontend falls back to laying the `expr` out automatically."""

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
    # The full spec, so a client that lists views already holds everything it
    # needs to evaluate them without a second per-view fetch — list_views already
    # parses it (#95). None if malformed.
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
    layout: ViewLayout | None = None


class SaveViewRequest(BaseModel):
    title: str = Field(min_length=1)
    base_revision: str | None = None
    entry_type: str = "view:view"
    spec: ViewSpec
    layout: ViewLayout | None = None


class UpdateViewUiRequest(BaseModel):
    """Body for the lock-free `PUT /api/views/{id}/ui` (ADR-0036). Carries ONLY
    the fold/ui state — never `spec`/`revision`, so a fold toggle can't 409
    against a concurrent designer save. For a `view_default_<kind>` id the node
    is materialized on first write."""

    ui: ViewUiState = Field(default_factory=ViewUiState)
