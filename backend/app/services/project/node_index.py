"""The node-index value types.

`NodeIndex` / `NodeIndexEntry` describe the result of walking a project's
layered Node files into an id→entry map, plus the `ReferenceEdge`s extracted
from the same pass (#305 / ADR-0040). They live in their own module so
the per-kind mixin slices (assistants, …) that instantiate `NodeIndex` or
annotate against these types can import them without a circular import
back into `project_service.py`. `project_service.py` re-exports both names,
so existing references keep working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class NodeIndexEntry:
    id: str
    kind: str
    entry_type: str
    path: Path
    title: str = ""
    source_layer_id: str = ""
    source_layer_label: str = ""


@dataclass(frozen=True)
class ReferenceEdge:
    """One `entity_ref` / `entity_ref_list` link, qualified by the field it came
    from.

    The field is part of the edge identity, not decoration: ADR-0039's
    reference-typed overrides must know *which* field an override re-points, and
    two fields on the same node may legitimately point at the same target.
    """

    src: str
    dst: str
    field_id: str


@dataclass
class NodeIndex:
    by_id: dict[str, NodeIndexEntry] = field(default_factory=dict)
    id_by_path: dict[Path, str] = field(default_factory=dict)
    # Forward edges keyed by source id, in field-declaration order. Written per
    # node during the index walk, so a shadowing descendant replaces the
    # ancestor's edges the same way it replaces its `by_id` entry.
    edges_by_src: dict[str, list[ReferenceEdge]] = field(default_factory=dict)
    # Reverse adjacency — the structure backlinks are served from. Populated by
    # `rebuild_reverse_edges` once the walk is complete.
    edges_by_dst: dict[str, list[ReferenceEdge]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def rebuild_reverse_edges(self) -> None:
        """(Re)build `edges_by_dst` from `edges_by_src`.

        Backlinks read this map rather than scanning a flat edge list — measured
        per query at Weber/huge scale: reverse map 179 ns / 194 ns, edge-list
        scan 229 µs / 518 µs (ADR-0040). Building it costs 0.7 ms / 6.5 ms, paid
        once per index build. Must run *after* the whole walk: forward edges are
        overwritten per id as inner layers shadow outer ones.
        """
        reverse: dict[str, list[ReferenceEdge]] = {}
        for edges in self.edges_by_src.values():
            for edge in edges:
                reverse.setdefault(edge.dst, []).append(edge)
        self.edges_by_dst = reverse
