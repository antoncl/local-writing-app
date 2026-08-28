"""Backend membership evaluator for context-pick selectors (ADR-0074 slice 5).

A tag / saved-view / plotline pick in the node picker persists as a *selector*
(`{kind, expr}`) rather than a bare id — e.g. a tag emits
`{kind: "lore", expr: {intersect: [{tagged: "World-building"}, {union: [...]}]}}`.
The picker resolves that selector on the frontend (`evaluateView`) for its live
counts, but the AI-context path had no evaluator, so the selected documents
never reached the prompt. This module is that evaluator.

**Parity is the contract.** The result must be the SAME node set the frontend
`evaluateView` produces (`frontend/src/lib/views/evaluateView.ts`), so the
highlight/preview and the actual send agree. The load-bearing semantics, mirrored
verbatim from `evalExpr`/`evalLeaf`:

- `type` is **exact** `entry_type` equality; `descendants_of` is the is_a family
  (self + every entry_type whose `parent:` chain reaches it).
- `tagged` matches when the node's tags contain the name — **exact,
  case-sensitive, trimmed** (tags stored as a list or a comma string).
- `intersect`/`union`/`difference`/`complement` are plain set ∩/∪/∖; `complement`
  is against the roster universe. Membership is order-independent; the emitted
  list follows roster order (deduped), like `evalSegment`.
- `filter` desugars: keep → `intersect[of, pred]`, drop →
  `difference{keep: of, remove: pred}`.
- An absent/empty/unrecognized expr selects **nothing** (ADR-0036) — "everything"
  must be stated explicitly.

Only this flat-membership subset is supported — the shapes the picker emits plus
safe set algebra. The relational/projection operators that can appear only in a
hand-built saved view (`nest`, `field_of`, `var`, `orphans_of`) raise
`UnsupportedSelectorExpr`; the AI-context caller fails soft (the pick contributes
no members rather than a wrong set).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, NamedTuple


class SelectorNode(NamedTuple):
    """One candidate node in a roster: the fields the grammar can test."""

    id: str
    entry_type: str
    tags: tuple[str, ...]
    metadata: Mapping[str, Any]


class UnsupportedSelectorExpr(Exception):
    """A ViewExpr operator outside the flat-membership subset. Raised so the
    caller can fail soft rather than silently resolve to an empty (wrong) set."""


def selector_node_tags(metadata: Any) -> tuple[str, ...]:
    """A node's tags, normalized exactly as the frontend `nodeTags` reader:
    a list maps each item to a trimmed string (empties dropped); a bare string
    splits on commas and trims. Case is preserved."""
    raw = metadata.get("tags") if isinstance(metadata, Mapping) else None
    if isinstance(raw, (list, tuple)):
        return tuple(t for t in (str(x).strip() for x in raw) if t)
    if isinstance(raw, str):
        return tuple(t for t in (p.strip() for p in raw.split(",")) if t)
    return ()


def evaluate_selector_membership(
    expr: Mapping[str, Any] | None,
    nodes: Sequence[SelectorNode],
    *,
    is_descendant: Callable[[str, str], bool],
    collection_fields: frozenset[str] = frozenset(),
    numeric_fields: frozenset[str] = frozenset(),
) -> list[str]:
    """Member node ids for `expr` over `nodes`, in roster order (deduped).

    `is_descendant(entry_type, target)` answers the `descendants_of` leaf — True
    when `entry_type` equals or descends from `target` (the backend
    `_entry_type_matches`). `collection_fields`/`numeric_fields` tune the `field`
    predicate for multi-value and number fields; both may be empty (list-valued
    data is still detected at runtime)."""
    universe = {n.id for n in nodes}
    member = _eval(expr, nodes, universe, is_descendant, collection_fields, numeric_fields)
    return [n.id for n in nodes if n.id in member]


def _eval(
    expr: Any,
    nodes: Sequence[SelectorNode],
    universe: set[str],
    is_desc: Callable[[str, str], bool],
    coll: frozenset[str],
    numf: frozenset[str],
) -> set[str]:
    """The set combinators; leaves delegate to `_eval_leaf`."""
    if not isinstance(expr, Mapping):
        return set()
    expr = _lower_filter(expr)

    def rec(child: Any) -> set[str]:
        return _eval(child, nodes, universe, is_desc, coll, numf)

    if _has(expr, "union"):
        out: set[str] = set()
        for child in expr["union"]:
            out |= rec(child)
        return out
    if _has(expr, "intersect"):
        return _eval_intersect(expr["intersect"], rec)
    if _has(expr, "difference"):
        diff = expr["difference"]
        return rec(diff.get("keep")) - rec(diff.get("remove"))
    if _has(expr, "complement"):
        return universe - rec(expr["complement"])
    if _has(expr, "annotate"):
        # Color-only pass-through: its members are its `of` operand unchanged.
        return rec(expr.get("of"))
    return _eval_leaf(expr, nodes, is_desc, coll, numf)


def _eval_intersect(children: Any, rec: Callable[[Any], set[str]]) -> set[str]:
    # No children folds to empty, matching the frontend `intersectAll`.
    if not children:
        return set()
    acc: set[str] | None = None
    for child in children:
        evaluated = rec(child)
        acc = evaluated if acc is None else (acc & evaluated)
    return acc if acc is not None else set()


def _eval_leaf(
    expr: Mapping[str, Any],
    nodes: Sequence[SelectorNode],
    is_desc: Callable[[str, str], bool],
    coll: frozenset[str],
    numf: frozenset[str],
) -> set[str]:
    if _has(expr, "type"):
        want = _leaf_operand(expr["type"])
        return {n.id for n in nodes if n.entry_type in want}
    if _has(expr, "descendants_of"):
        want = _leaf_operand(expr["descendants_of"])
        return {n.id for n in nodes if any(is_desc(n.entry_type, t) for t in want)}
    if _has(expr, "tagged"):
        want = _leaf_operand(expr["tagged"])
        return {n.id for n in nodes if want.intersection(n.tags)}
    if _has(expr, "hand_picked"):
        want = set(expr["hand_picked"] or [])
        return {n.id for n in nodes if n.id in want}
    if _has(expr, "field"):
        return _eval_field(expr["field"], nodes, coll, numf)
    for unsupported in ("nest", "field_of", "var", "orphans_of", "orphans_nest"):
        if _has(expr, unsupported):
            raise UnsupportedSelectorExpr(unsupported)
    # Absent / unrecognized slot = empty set (ADR-0036).
    return set()


def _has(expr: Mapping[str, Any], key: str) -> bool:
    # Pydantic dumps every slot with unset ones as explicit null; the picker's
    # on-disk specs are compact. Either way an absent slot is null-or-missing.
    return key in expr and expr[key] is not None


def _lower_filter(expr: Mapping[str, Any]) -> Mapping[str, Any]:
    """Desugar `filter` exactly as the frontend `lowerFilter` (ADR-0041 §C)."""
    if not _has(expr, "filter"):
        return expr
    spec = expr["filter"]
    of, pred, mode = spec.get("of"), spec.get("pred"), spec.get("mode")
    if mode == "drop":
        return {"difference": {"keep": of, "remove": pred}}
    return {"intersect": [of, pred]}


def _leaf_operand(value: Any) -> set[str]:
    """A leaf operand (`type`/`tagged`/`descendants_of`) to a string set. A bare
    string is one candidate; a `{var}` is unsupported (the picker emits none)."""
    if isinstance(value, str):
        return {value}
    if isinstance(value, Mapping) and "var" in value:
        raise UnsupportedSelectorExpr("var")
    if isinstance(value, (list, tuple)):
        return {x for x in value if isinstance(x, str)}
    raise UnsupportedSelectorExpr("leaf-operand")


def _eval_field(
    pred: Mapping[str, Any],
    nodes: Sequence[SelectorNode],
    coll: frozenset[str],
    numf: frozenset[str],
) -> set[str]:
    """The `field` predicate, mirroring the frontend `evalField`."""
    key = pred.get("key")
    op = pred.get("op")
    if op == "set":
        return {n.id for n in nodes if not _is_empty(n.metadata.get(key))}
    if op == "unset":
        return {n.id for n in nodes if _is_empty(n.metadata.get(key))}
    if op not in ("overlap", "disjoint"):
        raise UnsupportedSelectorExpr(f"field-op:{op}")
    is_coll = key in coll
    operand = _operand_set(pred.get("value"), is_coll)
    numeric = key in numf
    want = op == "overlap"
    out: set[str] = set()
    for node in nodes:
        raw = node.metadata.get(key)
        if is_coll or isinstance(raw, (list, tuple, set)):
            overlaps = bool(_to_str_set(raw) & operand)
        else:
            overlaps = _scalar_overlap(raw, operand, numeric)
        if overlaps == want:
            out.add(node.id)
    return out


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _to_str_set(raw: Any) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, (list, tuple, set)):
        return {s for s in (str(x).strip() for x in raw) if s}
    s = str(raw).strip()
    return {s} if s else set()


def _operand_set(value: Any, collection: bool) -> set[str]:
    """A predicate operand to a string set. A scalar field's string literal stays
    ONE token; a collection field's splits on commas (#202); a list keeps items
    whole."""
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {s for s in (str(x).strip() for x in value) if s}
    s = str(value).strip()
    if not s:
        return set()
    if collection:
        return {p for p in (part.strip() for part in s.split(",")) if p}
    return {s}


def _scalar_overlap(raw: Any, operand: set[str], numeric: bool) -> bool:
    """Whole-value scalar match (#202): the node's single value equals ANY
    operand candidate. Trimmed-string equality always; numeric equivalence only
    for declared number fields. An empty value overlaps nothing."""
    if _is_empty(raw):
        return False
    s = str(raw).strip()
    if s in operand:
        return True
    if numeric:
        try:
            n = float(s)
        except ValueError:
            return False
        for cand in operand:
            candidate = cand.strip()
            if not candidate:
                continue
            try:
                if float(candidate) == n:
                    return True
            except ValueError:
                continue
    return False
