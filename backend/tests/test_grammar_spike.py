"""Reproduce-today proof for the ViewExpr grammar IDL (#277, ADR-0041 Decision G).

Proves the emitter (`scripts/viewgrammar/emit_python.py`) regenerates a `ViewExpr` grammar
family that is **behaviourally identical** to the hand-written one in `app.models_views`, before
we use the IDL to evolve the grammar (Filter first-class, etc.). Three checks:

1. **field parity** — every class has the same field names, required-ness, and defaults;
2. **validation + dump parity** — a battery of valid/invalid exprs; real and generated must agree
   on accept-vs-reject, and agree on `model_dump()` when both accept;
3. **children() reachability** — the generated traversal reaches every declared child edge,
   including the operand-buried `field.value.field_of.of` that walkViewExpr special-cases.

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_grammar_spike.py -q
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import models_views as real

_SPIKE = Path(__file__).resolve().parents[2] / "scripts" / "viewgrammar"


def _load_generated():
    """Regenerate from the IDL, then import the emitted module fresh."""
    subprocess.run(
        [sys.executable, str(_SPIKE / "emit_python.py")], check=True, capture_output=True
    )
    spec = importlib.util.spec_from_file_location(
        "generated_grammar", _SPIKE / "generated_grammar.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load_generated()

_CLASSES = ["FieldPredicate", "FieldOfOp", "AnnotatePayload", "DifferenceOp", "NestMatch", "NestOp", "ViewExpr"]


@pytest.mark.parametrize("cls_name", _CLASSES)
def test_field_parity(cls_name: str) -> None:
    r = getattr(real, cls_name)
    g = getattr(gen, cls_name)
    assert set(r.model_fields) == set(g.model_fields), cls_name
    for name, rf in r.model_fields.items():
        gf = g.model_fields[name]
        assert rf.is_required() == gf.is_required(), f"{cls_name}.{name} required-ness"
        assert rf.default == gf.default, f"{cls_name}.{name} default"


def test_primary_slots_match() -> None:
    assert real._VIEW_EXPR_PRIMARY_SLOTS == gen._VIEW_EXPR_PRIMARY_SLOTS


# (kwargs, should_construct) — valid cases + one per invalid branch the validator guards.
_CHAR = {"type": "lore:character"}
_BATTERY: list[tuple[dict, bool]] = [
    # valid leaves / operators
    (_CHAR, True),
    ({"descendants_of": "lore:location"}, True),
    ({"tagged": "protagonist"}, True),
    ({"type": {"var": "T"}}, True),
    ({"var": "$self"}, True),
    ({"hand_picked": ["id1", "id2"]}, True),
    ({"union": [_CHAR, {"tagged": "x"}]}, True),
    ({"intersect": [_CHAR]}, True),
    ({"difference": {"keep": _CHAR, "remove": {"tagged": "x"}}}, True),
    ({"complement": _CHAR}, True),
    ({"field": {"key": "pov", "op": "overlap"}}, True),
    ({"field": {"key": "pov", "op": "set"}}, True),
    ({"field": {"key": "pov", "op": "overlap", "value": {"var": "POV"}}}, True),
    ({"field_of": {"of": {"type": "scene:scene"}, "field": "pov"}}, True),
    ({"annotate": {"label": "L"}, "of": _CHAR}, True),
    ({"annotate": {"color": "#abc"}, "of": _CHAR}, True),
    (
        {
            "nest": {
                "parents": {"field": {"key": "parent", "op": "unset"}},
                "children": _CHAR,
                "match": {"field": "parent", "direction": "child_to_parent"},
            }
        },
        True,
    ),
    ({"orphans_of": "n1"}, True),
    # invalid: exactly-one violations
    ({}, False),
    ({"type": "lore:character", "tagged": "x"}, False),
    ({"var": "$self", "type": "lore:character"}, False),
    ({"nest": {"match": {"field": "p", "direction": "child_to_parent"}}, "type": "lore:x"}, False),
    ({"field_of": {"of": _CHAR, "field": "pov"}, "type": "lore:character"}, False),
    # invalid: pairing / payload / min-items / min-length
    ({"annotate": {"label": "L"}}, False),  # annotate without of
    ({"annotate": {}, "of": _CHAR}, False),  # empty payload
    ({"type": "lore:character", "of": {"tagged": "x"}}, False),  # of without annotate
    ({"orphans_nest": {"match": {"field": "p", "direction": "child_to_parent"}}}, False),  # orphans_nest w/o orphans_of
    ({"union": []}, False),  # empty union
    ({"intersect": []}, False),  # empty intersect
    ({"field": {"key": "", "op": "overlap"}}, False),  # empty field key
    ({"field": {"key": "pov", "op": "eq"}}, False),  # retired op
    ({"field_of": {"of": _CHAR, "field": ""}}, False),  # empty projected field
]


@pytest.mark.parametrize("kwargs, ok", _BATTERY)
def test_validation_and_dump_parity(kwargs: dict, ok: bool) -> None:
    r_err = g_err = None
    r_obj = g_obj = None
    try:
        r_obj = real.ViewExpr(**kwargs)
    except ValidationError as e:
        r_err = e
    try:
        g_obj = gen.ViewExpr(**kwargs)
    except ValidationError as e:
        g_err = e

    # accept-vs-reject must agree, and match the expectation.
    assert (r_err is None) == (g_err is None) == ok, (kwargs, r_err, g_err)
    if ok:
        assert r_obj.model_dump() == g_obj.model_dump(), kwargs


def _dump(x):
    """Sparse dump — model → its set fields; a raw operand dict passes through."""
    return x.model_dump(exclude_none=True) if hasattr(x, "model_dump") else x


def test_children_reaches_every_edge() -> None:
    """Craft an expr touching each child edge (incl. operand-buried field_of) and confirm reach."""
    keep = {"type": "a:a"}
    remove = {"tagged": "r"}
    buried = {"type": "b:b"}
    e = gen.ViewExpr(difference={"keep": keep, "remove": remove})
    assert [_dump(c) for c in gen.children(e)] == [keep, remove]

    # nested field_of + operand-buried field_of in a union
    fo_child = {"type": "scene:scene"}
    u = gen.ViewExpr(
        union=[
            {"field_of": {"of": fo_child, "field": "pov"}},
            {"field": {"key": "pov", "op": "overlap", "value": {"field_of": {"of": buried, "field": "x"}}}},
        ]
    )
    top = gen.children(u)  # the two union members
    assert len(top) == 2
    # the field_of member reaches its `of`
    fo_reached = gen.children(top[0])
    assert [_dump(c) for c in fo_reached] == [fo_child]
    # the field member reaches the operand-buried `of` (a raw dict, per the Any typing)
    assert [_dump(c) for c in gen.children(top[1])] == [buried]
