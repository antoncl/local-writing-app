"""Guards for the machine-generated ViewExpr grammar (#277, ADR-0041).

The grammar is generated from scripts/viewgrammar/view-grammar.yaml into
app/view_grammar_generated.py. After the Phase-3 backend cutover the reproduce-vs-hand-written
proof retired (there is no separate hand-written model to compare against); what remains are the
ongoing guards:

- **freshness** — the committed generated module equals a fresh emit (edit the IDL → regenerate);
- **children()** — the generated traversal reaches every child edge, incl. the operand-buried
  `field.value.field_of.of` that walkViewExpr special-cases;
- **generated validators** — declared IDL constraints emit working checks (here the #275 / §F
  `companion_id_match`: an inline `orphans_nest` must carry the id its `orphans_of` names).

Broader behavioural validation of `ViewExpr` (exactly-one, pairing, op enum, …) lives in test_views.py.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import view_grammar_generated as g

_MATCH = {"field": "parent", "direction": "child_to_parent"}

_ROOT = Path(__file__).resolve().parents[2]
_EMIT = _ROOT / "scripts" / "viewgrammar" / "emit_python.py"
_COMMITTED = _ROOT / "backend" / "app" / "view_grammar_generated.py"
_EMIT_TS = _ROOT / "scripts" / "viewgrammar" / "emit_ts.py"
_COMMITTED_TS = _ROOT / "frontend" / "src" / "lib" / "viewGrammar.generated.ts"


def _norm(s: str) -> str:
    return s.replace("\r\n", "\n")


def _fresh_matches(emitter: Path, committed: Path, suffix: str) -> tuple[str, str]:
    tmp = Path(tempfile.mkdtemp()) / f"gen{suffix}"
    subprocess.run([sys.executable, str(emitter), str(tmp)], check=True, capture_output=True)
    return _norm(committed.read_text(encoding="utf-8")), _norm(tmp.read_text(encoding="utf-8"))


def test_committed_generated_is_fresh() -> None:
    """The committed Pydantic module must equal a fresh emit (regen on IDL change)."""
    committed, fresh = _fresh_matches(_EMIT, _COMMITTED, ".py")
    assert committed == fresh, "view_grammar_generated.py is stale — run emit_python.py"


def test_committed_ts_generated_is_fresh() -> None:
    """The committed TS module must equal a fresh emit (both runtimes share one IDL)."""
    committed, fresh = _fresh_matches(_EMIT_TS, _COMMITTED_TS, ".ts")
    assert committed == fresh, "viewGrammar.generated.ts is stale — run emit_ts.py"


def _dump(x):
    return x.model_dump(exclude_none=True) if hasattr(x, "model_dump") else x


def test_children_reaches_every_edge() -> None:
    keep = {"type": "a:a"}
    remove = {"tagged": "r"}
    buried = {"type": "b:b"}
    e = g.ViewExpr(difference={"keep": keep, "remove": remove})
    assert [_dump(c) for c in g.children(e)] == [keep, remove]

    fo_child = {"type": "scene:scene"}
    u = g.ViewExpr(
        union=[
            {"field_of": {"of": fo_child, "field": "pov"}},
            {"field": {"key": "pov", "op": "overlap", "value": {"field_of": {"of": buried, "field": "x"}}}},
        ]
    )
    top = g.children(u)
    assert len(top) == 2
    assert [_dump(c) for c in g.children(top[0])] == [fo_child]
    assert [_dump(c) for c in g.children(top[1])] == [buried]


def test_orphans_companion_id_must_match_reference() -> None:
    """#275 / ADR-0041 §F: the generated `companion_id_match` rule rejects an inline
    `orphans_nest` whose id disagrees with the `orphans_of` reference (they'd name
    different Nests and the orphan node-set couldn't resolve)."""
    # Inline Nest referenced by the SAME id → valid.
    g.ViewExpr(orphans_of="cities", orphans_nest={"match": _MATCH, "id": "cities"})
    # A plain by-id reference (no inline Nest) → valid: it resolves to a Nest elsewhere.
    g.ViewExpr(orphans_of="cities")

    # Mismatched id → rejected.
    with pytest.raises(ValidationError, match="must equal"):
        g.ViewExpr(orphans_of="cities", orphans_nest={"match": _MATCH, "id": "other"})
    # A missing id on the inline Nest is also a mismatch (None != the reference).
    with pytest.raises(ValidationError, match="must equal"):
        g.ViewExpr(orphans_of="cities", orphans_nest={"match": _MATCH})
