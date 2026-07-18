"""Emit the Pydantic `ViewExpr` grammar family from `view-grammar.yaml` (#277 spike, ADR-0041).

Reads the IDL and writes `generated_grammar.py`: the record classes, the `ViewExpr` node with
its generated `_exactly_one_primary`-style validator, the `_VIEW_EXPR_PRIMARY_SLOTS` tuple, and a
generated `children()` traversal. The reproduction test (`backend/tests/test_grammar_spike.py`)
proves this is behaviourally identical to today's hand-written model.

Run: backend/.venv/Scripts/python.exe scripts/viewgrammar/emit_python.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent


def _pytype(spec: dict[str, Any]) -> str:
    """The Python annotation for a field's base type (before optionality)."""
    t = spec["type"]
    if t == "str":
        return "str"
    if t == "int":
        return "int"
    if t == "bool":
        return "bool"
    if t == "any":
        return "Any"
    if t == "enum":
        vals = ", ".join(f'"{v}"' for v in spec["values"])
        return f"Literal[{vals}]"
    if t == "leaf_value":  # str | {"var": name}
        return "str | dict[str, Any]"
    if t == "list[ViewExpr]":
        return "list[ViewExpr]"
    if t == "list[str]":
        return "list[str]"
    return t  # a record name (ViewExpr, NestOp, ...)


def _field_line(name: str, spec: dict[str, Any], *, primary: bool) -> str:
    """One `name: annotation = default` line."""
    base = _pytype(spec)
    optional = primary or spec.get("optional", False)
    ann = f"{base} | None" if optional else base

    if spec["type"] == "str" and spec.get("min_len") and not optional:
        return f"    {name}: {ann} = Field(min_length={spec['min_len']})"
    if optional:
        return f"    {name}: {ann} = None"
    if "default" in spec:
        d = spec["default"]
        lit = "None" if d in ("null", None) else (f'"{d}"' if isinstance(d, str) else repr(d))
        return f"    {name}: {ann} = {lit}"
    return f"    {name}: {ann}"


def _emit_record(name: str, rec: dict[str, Any]) -> str:
    lines = [f"class {name}(BaseModel):"]
    for fname, fspec in rec["fields"].items():
        lines.append(_field_line(fname, fspec, primary=False))
    return "\n".join(lines)


def _emit_validator(node: dict[str, Any], primaries: list[str]) -> list[str]:
    c = node["constraints"]
    out = [
        "    @model_validator(mode='after')",
        "    def _exactly_one_primary(self) -> ViewExpr:",
        "        present = [s for s in _VIEW_EXPR_PRIMARY_SLOTS if getattr(self, s) is not None]",
        "        if len(present) != 1:",
        "            raise ValueError(",
        "                'a view expression must set exactly one of '",
        "                f'{list(_VIEW_EXPR_PRIMARY_SLOTS)}; got {present or [\"none\"]}'",
        "            )",
        "        slot = present[0]",
    ]
    for comp, pair in c.get("pairing", {}).items():
        prim, required = pair["primary"], pair.get("required", False)
        if required:
            out += [
                f"        if slot == '{prim}' and self.{comp} is None:",
                f"            raise ValueError('a `{prim}` node requires a `{comp}` input')",
            ]
        out += [
            f"        if slot != '{prim}' and self.{comp} is not None:",
            f"            raise ValueError('`{comp}` is only valid paired with `{prim}`')",
        ]
    for slot, fields in c.get("payload_nonempty", {}).items():
        cond = " and ".join(f"self.{slot}.{f} is None" for f in fields)
        names = "/".join(fields)
        out += [
            f"        if slot == '{slot}' and {cond}:",
            f"            raise ValueError('a `{slot}` payload must set at least one of {names}')",
        ]
    mi = c.get("min_items", [])
    if mi:
        tup = ", ".join(f"'{s}'" for s in mi)
        out += [
            f"        if slot in ({tup}) and not getattr(self, slot):",
            "            raise ValueError(f'`{slot}` requires at least one operand')",
        ]
    out.append("        return self")
    return out


def _emit_children(records: dict[str, Any], node: dict[str, Any]) -> list[str]:
    """Generate `children(e)` from every `child: true` / `operand: true` declaration."""
    out = [
        "def children(e: ViewExpr) -> list[Any]:",
        '    """Every sub-ViewExpr of `e` (generated — the single traversal all walkers use)."""',
        "    out: list[Any] = []",
    ]
    for slot, spec in node["slots"].items():
        base = spec["type"]
        if base == "list[ViewExpr]":
            out.append(f"    out.extend(e.{slot} or [])")
        elif base == "ViewExpr" and spec.get("child"):
            out += [f"    if e.{slot} is not None:", f"        out.append(e.{slot})"]
        elif base in records and spec.get("child") is not False:
            # recurse into the record's own child fields
            rec = records[base]
            child_fields = [f for f, fs in rec["fields"].items() if fs.get("child")]
            operand_fields = [f for f, fs in rec["fields"].items() if fs.get("operand")]
            if child_fields or operand_fields:
                out.append(f"    if e.{slot} is not None:")
                for cf in child_fields:
                    out += [
                        f"        if e.{slot}.{cf} is not None:",
                        f"            out.append(e.{slot}.{cf})",
                    ]
                for of in operand_fields:
                    out += [
                        f"        _v = e.{slot}.{of}",
                        "        if isinstance(_v, dict) and 'field_of' in _v:",
                        "            out.append(_v['field_of']['of'])",
                    ]
    out.append("    return out")
    return out


def main(out: Path | None = None) -> None:
    g = yaml.safe_load((HERE / "view-grammar.yaml").read_text(encoding="utf-8"))
    records: dict[str, Any] = g["records"]
    node = g["node"]
    primaries = [s for s, spec in node["slots"].items() if spec.get("primary")]

    parts = [
        '"""MACHINE-GENERATED from view-grammar.yaml by emit_python.py — DO NOT EDIT.',
        "",
        "Edit the IDL and regenerate. See scripts/viewgrammar/README.md for the stable",
        'surface (what you may depend on) vs. what churns on a grammar change."""',
        "from __future__ import annotations",
        "",
        "from typing import Any, Literal",
        "",
        "from pydantic import BaseModel, Field, model_validator",
        "",
    ]
    for name, rec in records.items():
        parts += [_emit_record(name, rec), "", ""]

    parts.append(
        "_VIEW_EXPR_PRIMARY_SLOTS: tuple[str, ...] = (\n"
        + "".join(f'    "{s}",\n' for s in primaries)
        + ")\n"
    )
    node_lines = ["class ViewExpr(BaseModel):"]
    for slot, spec in node["slots"].items():
        node_lines.append(_field_line(slot, spec, primary=spec.get("primary", False)))
    node_lines.append("")
    node_lines += _emit_validator(node, primaries)
    parts += ["\n".join(node_lines), "", ""]

    # Resolve forward refs (every record referencing ViewExpr, plus ViewExpr).
    for name in [*records, "ViewExpr"]:
        parts.append(f"{name}.model_rebuild()")
    parts += ["", ""]
    parts.append("\n".join(_emit_children(records, node)))
    parts.append("")

    dest = out or (HERE / "generated_grammar.py")
    dest.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {dest} ({len(primaries)} primary slots)")


if __name__ == "__main__":
    import sys

    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
