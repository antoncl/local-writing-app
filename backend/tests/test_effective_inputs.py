"""Unit tests for the ADR-0061 effective-inputs resolver.

The resolver is pure — it takes a `resolve_snippet` callback, so these tests
build a snippet registry in memory and never touch a ProjectService.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.models import PromptInputDefinition
from app.services.ai.effective_inputs import (
    SnippetSource,
    resolve_effective_inputs,
)
from app.services.ai.snippet_loader import match_snippet_name


def _inp(name: str, type: str = "text", **kw) -> PromptInputDefinition:
    return PromptInputDefinition(name=name, type=type, **kw)


def _snippet(snippet_id: str, body: str, *inputs: PromptInputDefinition) -> SnippetSource:
    return SnippetSource(id=snippet_id, body=body, inputs=tuple(inputs))


def _resolver(*snippets: SnippetSource):
    """A resolve_snippet callback over a registry keyed by snippet id — the
    literal include name in these tests IS the snippet id."""
    registry = {s.id: s for s in snippets}
    return lambda name: registry.get(name)


def _names(inputs) -> list[str]:
    return [i.name for i in inputs]


# --- gather semantics -------------------------------------------------------


def test_no_includes_returns_own_inputs_unchanged():
    own = [_inp("a"), _inp("b")]
    result = resolve_effective_inputs("Plain body, no includes.", own, _resolver())
    assert _names(result.inputs) == ["a", "b"]
    assert result.conflicts == []


def test_single_include_contributes_its_input():
    voice = _snippet("voice", "{{ input.tone }}", _inp("tone", "select"))
    result = resolve_effective_inputs('{% include "voice" %}', [], _resolver(voice))
    assert _names(result.inputs) == ["tone"]
    assert result.inputs[0].type == "select"


def test_own_and_snippet_union_own_first():
    voice = _snippet("voice", "{{ input.tone }}", _inp("tone"))
    result = resolve_effective_inputs(
        'Body {% include "voice" %}', [_inp("subject")], _resolver(voice)
    )
    # Own inputs come first, then the purely-inherited ones.
    assert _names(result.inputs) == ["subject", "tone"]


def test_transitive_include_through_a_snippet():
    inner = _snippet("inner", "{{ input.deep }}", _inp("deep"))
    outer_snip = _snippet("outer", '{% include "inner" %}', _inp("mid"))
    result = resolve_effective_inputs('{% include "outer" %}', [], _resolver(inner, outer_snip))
    # Pre-order: the outer snippet's own input before its include's.
    assert _names(result.inputs) == ["mid", "deep"]


def test_include_inside_role_block_is_scanned():
    voice = _snippet("voice", "hi", _inp("tone"))
    body = '{% role "user" %}{% include "voice" %}{% endrole %}'
    result = resolve_effective_inputs(body, [], _resolver(voice))
    assert _names(result.inputs) == ["tone"]


def test_include_list_contributes_each_member():
    a = _snippet("a", "", _inp("x"))
    b = _snippet("b", "", _inp("y"))
    result = resolve_effective_inputs('{% include ["a", "b"] %}', [], _resolver(a, b))
    assert _names(result.inputs) == ["x", "y"]


def test_dangling_include_contributes_nothing():
    result = resolve_effective_inputs('{% include "missing" %}', [_inp("a")], _resolver())
    assert _names(result.inputs) == ["a"]


# --- static, not runtime (ADR §2) -------------------------------------------


def test_dynamic_include_contributes_nothing():
    voice = _snippet("voice", "", _inp("tone"))
    # A dynamically-named include can't be resolved statically → no fields.
    result = resolve_effective_inputs("{% include input.which %}", [], _resolver(voice))
    assert result.inputs == []


def test_conditional_include_still_contributes():
    voice = _snippet("voice", "", _inp("tone"))
    body = "{% if input.flag %}{% include 'voice' %}{% endif %}"
    result = resolve_effective_inputs(body, [], _resolver(voice))
    # The condition decides expansion at render, never gathering — the field is
    # always offered (the form must over-provide, never under-provide).
    assert _names(result.inputs) == ["tone"]


def test_malformed_body_degrades_to_no_includes():
    # An unbalanced tag mid-edit must not crash gathering; own inputs survive.
    result = resolve_effective_inputs("{% include 'voice' ", [_inp("a")], _resolver())
    assert _names(result.inputs) == ["a"]


# --- collisions (ADR §3) ----------------------------------------------------


def test_nearer_wins_outer_overrides_presentation_not_type():
    voice = _snippet(
        "voice", "", _inp("tone", "select", default="snip", label="Snip", hidden=False)
    )
    own = [_inp("tone", "text", default="outer", label="Outer", hidden=True)]
    result = resolve_effective_inputs('{% include "voice" %}', own, _resolver(voice))
    assert _names(result.inputs) == ["tone"]
    tone = result.inputs[0]
    # The snippet owns existence + type; the outer overrides default/label/hidden.
    assert tone.type == "select"
    assert tone.default == "outer"
    assert tone.label == "Outer"
    assert tone.hidden is True
    # Type is owned by the snippet, not retyped by the outer → not a conflict.
    assert result.conflicts == []


def test_same_name_same_type_across_snippets_is_not_a_conflict():
    a = _snippet("a", "", _inp("tone", "text"))
    b = _snippet("b", "", _inp("tone", "text"))
    result = resolve_effective_inputs(
        '{% include "a" %}{% include "b" %}', [], _resolver(a, b)
    )
    assert _names(result.inputs) == ["tone"]
    assert result.conflicts == []


def test_same_name_different_type_across_snippets_is_a_conflict():
    a = _snippet("a", "", _inp("tone", "text"))
    b = _snippet("b", "", _inp("tone", "select"))
    result = resolve_effective_inputs(
        '{% include "a" %}{% include "b" %}', [], _resolver(a, b)
    )
    # First-seen type wins so a form still renders...
    assert _names(result.inputs) == ["tone"]
    assert result.inputs[0].type == "text"
    # ...but the clash is surfaced, never silently resolved.
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.name == "tone"
    assert conflict.types == ("text", "select")


# --- guards -----------------------------------------------------------------


def test_include_cycle_terminates():
    a = _snippet("a", '{% include "b" %}', _inp("a_field"))
    b = _snippet("b", '{% include "a" %}', _inp("b_field"))
    result = resolve_effective_inputs('{% include "a" %}', [], _resolver(a, b))
    # Both contribute once; the cycle does not recurse forever.
    assert set(_names(result.inputs)) == {"a_field", "b_field"}


def test_recursion_depth_guard_bounds_a_deep_chain():
    chain = [
        _snippet(f"s{i}", f'{{% include "s{i + 1}" %}}', _inp(f"i{i}")) for i in range(10)
    ]
    result = resolve_effective_inputs(
        '{% include "s0" %}', [], _resolver(*chain), max_depth=5
    )
    # Depth 1..5 contribute (s0..s4); the guard stops before s5 at depth 6.
    assert _names(result.inputs) == ["i0", "i1", "i2", "i3", "i4"]


def test_diamond_snippet_contributes_once():
    shared = _snippet("shared", "", _inp("common"))
    left = _snippet("left", '{% include "shared" %}', _inp("l"))
    right = _snippet("right", '{% include "shared" %}', _inp("r"))
    result = resolve_effective_inputs(
        '{% include "left" %}{% include "right" %}', [], _resolver(shared, left, right)
    )
    assert _names(result.inputs) == ["l", "common", "r"]


# --- shared name matcher (used by both the loader and the resolver) ---------


def _cand(snippet_id: str, title: str):
    return SimpleNamespace(id=snippet_id, title=title)


def test_match_snippet_name_prefers_id_then_unique_title():
    snippets = [_cand("p1", "Alpha"), _cand("p2", "Beta")]
    kw = {"id_of": lambda e: e.id, "title_of": lambda e: e.title}
    assert match_snippet_name("p1", snippets, **kw).id == "p1"
    assert match_snippet_name("p1.md", snippets, **kw).id == "p1"  # .md stripped
    assert match_snippet_name("Alpha", snippets, **kw).id == "p1"  # unique title
    assert match_snippet_name("nope", snippets, **kw) is None


def test_match_snippet_name_ambiguous_title_is_unresolved():
    snippets = [_cand("p1", "Dup"), _cand("p2", "Dup")]
    kw = {"id_of": lambda e: e.id, "title_of": lambda e: e.title}
    assert match_snippet_name("Dup", snippets, **kw) is None
