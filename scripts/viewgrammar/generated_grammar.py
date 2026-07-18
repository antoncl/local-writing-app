"""GENERATED from view-grammar.yaml by emit_python.py — do not edit."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

class FieldPredicate(BaseModel):
    key: str = Field(min_length=1)
    op: Literal["overlap", "disjoint", "set", "unset"]
    value: Any = None


class FieldOfOp(BaseModel):
    of: ViewExpr
    field: str = Field(min_length=1)


class AnnotatePayload(BaseModel):
    label: str | None = None
    color: str | None = None
    rank: int | None = None


class DifferenceOp(BaseModel):
    keep: ViewExpr
    remove: ViewExpr


class NestMatch(BaseModel):
    field: str = Field(min_length=1)
    direction: Literal["child_to_parent", "parent_to_children"]
    by: Literal["ref", "title"] = "ref"


class NestOp(BaseModel):
    parents: ViewExpr | None = None
    children: ViewExpr | None = None
    match: NestMatch
    recursive: bool = False
    id: str | None = None


_VIEW_EXPR_PRIMARY_SLOTS: tuple[str, ...] = (
    "union",
    "intersect",
    "difference",
    "complement",
    "nest",
    "annotate",
    "field_of",
    "type",
    "descendants_of",
    "tagged",
    "field",
    "hand_picked",
    "var",
    "orphans_of",
)

class ViewExpr(BaseModel):
    union: list[ViewExpr] | None = None
    intersect: list[ViewExpr] | None = None
    difference: DifferenceOp | None = None
    complement: ViewExpr | None = None
    nest: NestOp | None = None
    annotate: AnnotatePayload | None = None
    field_of: FieldOfOp | None = None
    type: str | dict[str, Any] | None = None
    descendants_of: str | dict[str, Any] | None = None
    tagged: str | dict[str, Any] | None = None
    field: FieldPredicate | None = None
    hand_picked: list[str] | None = None
    var: str | None = None
    orphans_of: str | None = None
    of: ViewExpr | None = None
    orphans_nest: NestOp | None = None

    @model_validator(mode='after')
    def _exactly_one_primary(self) -> ViewExpr:
        present = [s for s in _VIEW_EXPR_PRIMARY_SLOTS if getattr(self, s) is not None]
        if len(present) != 1:
            raise ValueError(
                'a view expression must set exactly one of '
                f'{list(_VIEW_EXPR_PRIMARY_SLOTS)}; got {present or ["none"]}'
            )
        slot = present[0]
        if slot == 'annotate' and self.of is None:
            raise ValueError('a `annotate` node requires a `of` input')
        if slot != 'annotate' and self.of is not None:
            raise ValueError('`of` is only valid paired with `annotate`')
        if slot != 'orphans_of' and self.orphans_nest is not None:
            raise ValueError('`orphans_nest` is only valid paired with `orphans_of`')
        if slot == 'annotate' and self.annotate.label is None and self.annotate.color is None:
            raise ValueError('a `annotate` payload must set at least one of label/color')
        if slot in ('union', 'intersect') and not getattr(self, slot):
            raise ValueError(f'`{slot}` requires at least one operand')
        return self


FieldPredicate.model_rebuild()
FieldOfOp.model_rebuild()
AnnotatePayload.model_rebuild()
DifferenceOp.model_rebuild()
NestMatch.model_rebuild()
NestOp.model_rebuild()
ViewExpr.model_rebuild()


def children(e: ViewExpr) -> list[Any]:
    """Every sub-ViewExpr of `e` (generated — the single traversal all walkers use)."""
    out: list[Any] = []
    out.extend(e.union or [])
    out.extend(e.intersect or [])
    if e.difference is not None:
        if e.difference.keep is not None:
            out.append(e.difference.keep)
        if e.difference.remove is not None:
            out.append(e.difference.remove)
    if e.complement is not None:
        out.append(e.complement)
    if e.nest is not None:
        if e.nest.parents is not None:
            out.append(e.nest.parents)
        if e.nest.children is not None:
            out.append(e.nest.children)
    if e.field_of is not None:
        if e.field_of.of is not None:
            out.append(e.field_of.of)
    if e.field is not None:
        _v = e.field.value
        if isinstance(_v, dict) and 'field_of' in _v:
            out.append(_v['field_of']['of'])
    if e.of is not None:
        out.append(e.of)
    if e.orphans_nest is not None:
        if e.orphans_nest.parents is not None:
            out.append(e.orphans_nest.parents)
        if e.orphans_nest.children is not None:
            out.append(e.orphans_nest.children)
    return out
