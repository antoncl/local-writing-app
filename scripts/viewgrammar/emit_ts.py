"""Emit the TS `ViewExpr` grammar family from `view-grammar.yaml` (#277 spike, ADR-0041).

The SAME IDL as the Python emitter, second backend. Writes `generated_grammar.ts`; the
equivalence test (`equiv.ts` + `tsconfig.check.json`) checks it against the hand-written
`frontend/src/lib/types.ts` via `tsc`. Where the hand-written TS carries incidental idiom-drift
(mixed `?`/`| null`, a defaulted field left required), the generated form normalizes it — that
normalization *is* the drift #277 exists to kill, and the equiv test reports exactly where.

Run: backend/.venv/Scripts/python.exe scripts/viewgrammar/emit_ts.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent

# IDL record name -> TS type name (emitters own their target's naming convention).
TS_NAME = {
    "FieldPredicate": "ViewFieldPredicate",
    "FieldOfOp": "ViewFieldOf",
    "AnnotatePayload": "ViewAnnotatePayload",
    "DifferenceOp": "ViewDifferenceOp",
    "FilterOp": "ViewFilterOp",
    "NestMatch": "ViewNestMatch",
    "NestOp": "ViewNestOp",
}


def _tstype(spec: dict[str, Any], records: dict[str, Any]) -> str:
    t = spec["type"]
    if spec.get("operand"):
        return "ViewOperand"
    if t == "str":
        return "string"
    if t == "int":
        return "number"
    if t == "bool":
        return "boolean"
    if t == "any":
        return "unknown"
    if t == "enum":
        return " | ".join(f'"{v}"' for v in spec["values"])
    if t == "leaf_value":
        return "ViewLeafValue"
    if t == "list[ViewExpr]":
        return "ViewExpr[]"
    if t == "list[str]":
        return "string[]"
    if t == "ViewExpr":
        return "ViewExpr"
    return TS_NAME.get(t, t)


def _optional(spec: dict[str, Any]) -> bool:
    """TS-optional iff a primary slot, an `optional` field, or carrying a default.
    `ts_required` overrides (reproduces a hand-written field left required despite a default)."""
    if spec.get("ts_required"):
        return False
    return spec.get("primary", False) or spec.get("optional", False) or "default" in spec


def _member(name: str, spec: dict[str, Any], records: dict[str, Any]) -> str:
    q = "?" if _optional(spec) else ""
    ann = _tstype(spec, records)
    if spec.get("ts_null"):
        ann = f"{ann} | null"
    return f"  {name}{q}: {ann};"


def _emit_type(ts_name: str, fields: dict[str, Any], records: dict[str, Any]) -> str:
    body = "\n".join(_member(n, s, records) for n, s in fields.items())
    return f"export type {ts_name} = {{\n{body}\n}};"


def _emit_children(records: dict[str, Any], node: dict[str, Any]) -> str:
    out = [
        "// The single generated traversal (mirrors walkViewExpr).",
        "export function children(e: ViewExpr): ViewExpr[] {",
        "  const out: ViewExpr[] = [];",
    ]
    for slot, spec in node["slots"].items():
        base = spec["type"]
        if base == "list[ViewExpr]":
            out.append(f"  for (const s of e.{slot} ?? []) out.push(s);")
        elif base == "ViewExpr" and spec.get("child"):
            out.append(f"  if (e.{slot}) out.push(e.{slot});")
        elif base in records:
            rec = records[base]
            cfs = [f for f, fs in rec["fields"].items() if fs.get("child")]
            ofs = [f for f, fs in rec["fields"].items() if fs.get("operand")]
            for cf in cfs:
                out.append(f"  if (e.{slot}?.{cf}) out.push(e.{slot}.{cf});")
            for of in ofs:
                out += [
                    f"  const _v_{slot} = e.{slot}?.{of};",
                    f'  if (_v_{slot} && typeof _v_{slot} === "object" && "field_of" in _v_{slot})',
                    f"    out.push((_v_{slot} as {{ field_of: ViewFieldOf }}).field_of.of);",
                ]
    out += ["  return out;", "}"]
    return "\n".join(out)


def main(out: Path | None = None) -> None:
    g = yaml.safe_load((HERE / "view-grammar.yaml").read_text(encoding="utf-8"))
    records: dict[str, Any] = g["records"]
    node = g["node"]

    parts = [
        "// MACHINE-GENERATED from view-grammar.yaml by emit_ts.py — DO NOT EDIT.",
        "// Edit the IDL and regenerate. See scripts/viewgrammar/README.md for the",
        "// stable surface vs. what churns on a grammar change.",
        "",
        "export type ViewLeafValue = string | { var: string };",
        "export type ViewOperand = unknown | { var: string } | { field_of: ViewFieldOf };",
        "",
    ]
    for name, rec in records.items():
        parts += [_emit_type(TS_NAME[name], rec["fields"], records), ""]

    slot_fields = {s: spec for s, spec in node["slots"].items()}
    parts += [_emit_type("ViewExpr", slot_fields, records), ""]
    parts += [_emit_children(records, node), ""]

    dest = out or (HERE.parents[1] / "frontend" / "src" / "lib" / "viewGrammar.generated.ts")
    dest.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {dest}")


if __name__ == "__main__":
    import sys

    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
