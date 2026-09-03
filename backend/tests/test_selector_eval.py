"""Membership parity for the backend selector evaluator (ADR-0074 slice 5).

These pin the semantics the backend must share with the frontend `evaluateView`
(`frontend/src/lib/views/evaluateView.ts`): `type` exact vs `descendants_of`
is_a, `tagged` as a schema-free metadata backlink test, set algebra, `filter`
desugar, `field` overlap, and empty-expr = nothing. A drift here selects the
wrong documents for AI context.
"""

from __future__ import annotations

import pytest

from app.services.ai.selector_eval import (
    SelectorNode,
    UnsupportedSelectorExpr,
    evaluate_selector_membership,
    selector_references,
)

# A tiny is_a family: lore:hero descends from lore:character.
_PARENT = {"lore:hero": "lore:character"}


def _is_descendant(entry_type: str, target: str) -> bool:
    seen: set[str] = set()
    current: str | None = entry_type
    while current is not None and current not in seen:
        if current == target:
            return True
        seen.add(current)
        current = _PARENT.get(current)
    return False


def _nodes(*specs: tuple[str, str, tuple[str, ...]]) -> list[SelectorNode]:
    return [SelectorNode(nid, et, frozenset(tags), {"tags": list(tags)}) for nid, et, tags in specs]


def _run(expr, nodes, **kw) -> list[str]:
    return evaluate_selector_membership(expr, nodes, is_descendant=_is_descendant, **kw)


# --- the shape the tag picker actually emits ------------------------------


def test_tag_intersect_with_type_union_is_the_picker_shape():
    nodes = _nodes(
        ("l1", "lore:note", ("World-building",)),
        ("l2", "lore:location", ("World-building",)),
        ("l3", "lore:character", ("Real-world",)),  # wrong tag
        ("l4", "lore:chat", ("World-building",)),  # tagged but type not in union
    )
    expr = {
        "intersect": [
            {"tagged": "World-building"},
            {"union": [{"type": "lore:note"}, {"type": "lore:location"}]},
        ]
    }
    assert _run(expr, nodes) == ["l1", "l2"]


def test_bare_tagged_selects_every_tag_bearer():
    nodes = _nodes(("a", "lore:note", ("T",)), ("b", "lore:note", ()), ("c", "lore:item", ("T",)))
    assert _run({"tagged": "T"}, nodes) == ["a", "c"]


# --- type (exact) vs descendants_of (is_a) --------------------------------


def test_type_is_exact_not_subtype():
    nodes = _nodes(("hero", "lore:hero", ()), ("char", "lore:character", ()))
    # `type` matches the exact entry_type only — the hero subtype is excluded.
    assert _run({"type": "lore:character"}, nodes) == ["char"]


def test_descendants_of_includes_subtypes():
    nodes = _nodes(("hero", "lore:hero", ()), ("char", "lore:character", ()))
    assert _run({"descendants_of": "lore:character"}, nodes) == ["hero", "char"]


# --- tagged: backlink-edge test over metadata (ADR-0082 slice 2b) ---------


def test_tagged_matches_a_scalar_metadata_value():
    # selector_references walks every scalar/list value in the metadata, not
    # just a conventional `tags` field — a schema-free backlink test.
    metadata = {"pov": "tag_x"}
    assert selector_references(metadata) == frozenset({"tag_x"})
    node = SelectorNode("x", "lore:note", selector_references(metadata), metadata)
    assert _run({"tagged": "tag_x"}, [node]) == ["x"]


def test_tagged_matches_a_nested_item_group_member():
    metadata = {"cast": [{"name": "Nyla", "role_tag": "tag_x"}]}
    node = SelectorNode("x", "lore:note", selector_references(metadata), metadata)
    assert _run({"tagged": "tag_x"}, [node]) == ["x"]


def test_tagged_id_as_substring_does_not_match():
    metadata = {"notes": "tag_x_extended"}
    node = SelectorNode("x", "lore:note", selector_references(metadata), metadata)
    assert _run({"tagged": "tag_x"}, [node]) == []


def test_tagged_is_case_sensitive():
    nodes = _nodes(("x", "lore:note", ("World",)))
    assert _run({"tagged": "world"}, nodes) == []


# --- set algebra ----------------------------------------------------------


def test_difference_and_complement():
    nodes = _nodes(("a", "lore:note", ("T",)), ("b", "lore:note", ()), ("c", "lore:item", ("T",)))
    assert _run({"difference": {"keep": {"tagged": "T"}, "remove": {"type": "lore:item"}}}, nodes) == ["a"]
    assert _run({"complement": {"tagged": "T"}}, nodes) == ["b"]


def test_output_follows_roster_order_and_dedups():
    nodes = _nodes(("a", "lore:note", ("T",)), ("b", "lore:note", ("T",)))
    # union of two overlapping leaves — each node appears once, in roster order.
    assert _run({"union": [{"tagged": "T"}, {"type": "lore:note"}]}, nodes) == ["a", "b"]


# --- filter desugar (ADR-0041 §C) -----------------------------------------


def test_filter_keep_lowers_to_intersect():
    nodes = _nodes(("a", "lore:note", ("T",)), ("b", "lore:item", ("T",)))
    expr = {"filter": {"of": {"tagged": "T"}, "pred": {"type": "lore:note"}}}
    assert _run(expr, nodes) == ["a"]


def test_filter_drop_lowers_to_difference():
    nodes = _nodes(("a", "lore:note", ("T",)), ("b", "lore:item", ("T",)))
    expr = {"filter": {"of": {"tagged": "T"}, "pred": {"type": "lore:note"}, "mode": "drop"}}
    assert _run(expr, nodes) == ["b"]


# --- field predicate (the plotline shape) ---------------------------------


def test_field_overlap_on_list_value_matches_plotline():
    nodes = [
        SelectorNode("c1", "plot:card", frozenset(), {"plotline": ["pl_1", "pl_2"]}),
        SelectorNode("c2", "plot:card", frozenset(), {"plotline": ["pl_3"]}),
    ]
    expr = {
        "intersect": [
            {"type": "plot:card"},
            {"field": {"key": "plotline", "op": "overlap", "value": "pl_1"}},
        ]
    }
    assert _run(expr, nodes) == ["c1"]


def test_field_set_and_unset():
    nodes = [
        SelectorNode("a", "lore:note", frozenset(), {"pov": "Bob"}),
        SelectorNode("b", "lore:note", frozenset(), {"pov": ""}),
        SelectorNode("c", "lore:note", frozenset(), {}),
    ]
    assert _run({"field": {"key": "pov", "op": "set"}}, nodes) == ["a"]
    assert _run({"field": {"key": "pov", "op": "unset"}}, nodes) == ["b", "c"]


# --- ADR-0036: absent/empty expr selects nothing --------------------------


def test_empty_expr_selects_nothing():
    nodes = _nodes(("a", "lore:note", ("T",)))
    assert _run({}, nodes) == []
    assert _run(None, nodes) == []


def test_intersect_of_no_children_is_empty():
    nodes = _nodes(("a", "lore:note", ("T",)))
    assert _run({"intersect": []}, nodes) == []


# --- unsupported operators fail loud (caller fails soft) -------------------


@pytest.mark.parametrize("expr", [{"var": "x"}, {"nest": {}}, {"field_of": {}}, {"tagged": {"var": "x"}}])
def test_unsupported_operators_raise(expr):
    with pytest.raises(UnsupportedSelectorExpr):
        _run(expr, _nodes(("a", "lore:note", ())))


# --- merged-tag canonicalisation (ADR-0082 §5) ------------------------------
#
# `SelectorNode.references` are canonicalised where the roster is built
# (`preview.py`'s `_canonical_references`), not inside this module — this
# pins that a `tagged:` leaf over such a roster matches through a redirect,
# the same contract `preview.py`'s own construction sites rely on.


class _FakeIndex:
    """The one method `_canonical_references` reads off a `NodeIndex` — a
    small stand-in so this stays a unit test, not a project fixture."""

    def __init__(self, canonical: dict[str, str]) -> None:
        self._canonical = canonical

    def canonical_id(self, node_id: str) -> str:
        return self._canonical.get(node_id, node_id)


def test_tagged_matches_a_carrier_still_holding_a_merged_tags_id():
    from app.services.ai.preview import _canonical_references

    index = _FakeIndex({"tag_mirror": "tag_mirrors"})
    metadata = {"motifs": ["tag_mirror"]}
    node = SelectorNode("lore_a", "lore:note", _canonical_references(index, metadata), metadata)
    assert _run({"tagged": "tag_mirrors"}, [node]) == ["lore_a"]
    # Without the `canonical_id` kwarg the OPERAND is taken literally — the
    # merged id itself doesn't match a roster whose references are already
    # canonical (the default/today's behaviour, #1805).
    assert _run({"tagged": "tag_mirror"}, [node]) == []


def test_canonical_references_is_identity_when_nothing_is_merged():
    from app.services.ai.preview import _canonical_references

    index = _FakeIndex({})
    metadata = {"motifs": ["tag_a", "tag_b"]}
    assert _canonical_references(index, metadata) == frozenset({"tag_a", "tag_b"})


# --- `canonical_id` kwarg: OPERAND-side canonicalisation (#1805) -----------


def test_canonical_id_kwarg_follows_a_tagged_operand_to_the_survivor():
    from app.services.ai.preview import _canonical_references

    index = _FakeIndex({"tag_mirror": "tag_mirrors"})
    metadata = {"motifs": ["tag_mirror"]}
    node = SelectorNode("lore_a", "lore:note", _canonical_references(index, metadata), metadata)
    # The stored operand still names the merged id; with `canonical_id` given it
    # is followed to the survivor before the intersection, matching the roster's
    # already-canonical reference.
    assert _run({"tagged": "tag_mirror"}, [node], canonical_id=index.canonical_id) == ["lore_a"]


def test_canonical_id_kwarg_is_a_two_hop_chain():
    # `canonical_id` is called ONCE per operand id (no chain-walking inside
    # `_eval_leaf`) — the contract, matching `NodeIndex.canonical_id`, is that
    # the callable itself already resolves a multi-hop `merged_into` chain to
    # its end, so this stand-in walks the chain rather than doing one hop.
    redirects = {"tag_a": "tag_b", "tag_b": "tag_c"}

    def canonical_id(node_id: str) -> str:
        seen: set[str] = set()
        current = node_id
        while current in redirects and current not in seen:
            seen.add(current)
            current = redirects[current]
        return current

    node = SelectorNode("x", "lore:note", frozenset({"tag_c"}), {"tags": ["tag_c"]})
    assert _run({"tagged": "tag_a"}, [node], canonical_id=canonical_id) == ["x"]


def test_canonical_id_kwarg_defaults_to_none_unchanged_behaviour():
    node = SelectorNode("x", "lore:note", frozenset({"tag_t"}), {"tags": ["tag_t"]})
    assert _run({"tagged": "tag_t"}, [node]) == ["x"]
    assert _run({"tagged": "tag_t"}, [node], canonical_id=None) == ["x"]
