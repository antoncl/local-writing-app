"""Shared tree-config constants (#14 backend split).

The manuscript and research trees are both `TreeStructureService` instances
parameterised by a `TreeConfig`. These constants used to live at module scope
in `project_service.py`, but the research slice (`project/research.py`) needs
`RESEARCH_TREE_CONFIG` too — defining them here lets both the core class and
the mixin import them without an import cycle (the mixin must not import back
into `project_service`).
"""

from __future__ import annotations

from app.services.tree_structure import TreeConfig

MANUSCRIPT_TREE_CONFIG = TreeConfig(
    yaml_filename="manuscript.structure.yaml",
    root_title="Manuscript",
    leaf_ref_field="scene_id",
    leaf_subdir="scenes",
)

RESEARCH_TREE_CONFIG = TreeConfig(
    yaml_filename="research.structure.yaml",
    root_title="Research",
    leaf_ref_field="note_id",
    leaf_subdir="research/notes",
)
