"""The node-index value types.

`NodeIndex` / `NodeIndexEntry` describe the result of walking a project's
layered Node files into an id→entry map. They live in their own module so
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


@dataclass
class NodeIndex:
    by_id: dict[str, NodeIndexEntry] = field(default_factory=dict)
    id_by_path: dict[Path, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
