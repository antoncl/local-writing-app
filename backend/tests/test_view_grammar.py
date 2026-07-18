"""Guards for the machine-generated ViewExpr grammar (#277, ADR-0041).

The grammar is generated from scripts/viewgrammar/view-grammar.yaml into
app/view_grammar_generated.py. After the Phase-3 backend cutover the reproduce-vs-hand-written
proof retired (there is no separate hand-written model to compare against); what remains are the
ongoing guards:

- **freshness** — the committed generated module equals a fresh emit (edit the IDL → regenerate);
- **children()** — the generated traversal reaches every child edge, incl. the operand-buried
  `field.value.field_of.of` that walkViewExpr special-cases.

Behavioural validation of `ViewExpr` (exactly-one, pairing, op enum, …) lives in test_views.py.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from app import view_grammar_generated as g

_ROOT = Path(__file__).resolve().parents[2]
_EMIT = _ROOT / "scripts" / "viewgrammar" / "emit_python.py"
_COMMITTED = _ROOT / "backend" / "app" / "view_grammar_generated.py"


def test_committed_generated_is_fresh() -> None:
    """The committed module must equal a fresh emit — catches a forgotten regenerate."""
    tmp = Path(tempfile.mkdtemp()) / "gen.py"
    subprocess.run([sys.executable, str(_EMIT), str(tmp)], check=True, capture_output=True)

    def norm(s: str) -> str:
        return s.replace("\r\n", "\n")

    assert norm(_COMMITTED.read_text(encoding="utf-8")) == norm(tmp.read_text(encoding="utf-8")), (
        "view_grammar_generated.py is stale — run scripts/viewgrammar/emit_python.py"
    )


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
