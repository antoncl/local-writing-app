"""The two trees, as configuration (ADR-0094).

The manuscript and research trees are one mechanism: nodes of one kind, in one
folder, each file carrying its own placement (`parent` / `rank`), assembled by
`TreeNodesMixin`. What differs between them is data, and it lives here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TreeSpec:
    """One tree: which nodes it holds and what its leaves are.

    `kind` — the node kind whose files make up the tree.
    `folder` — where those files live under a project folder; only the open
        project's own folder is placed (a tree never spans the inherits chain).
    `leaf_type` — the entry type that cannot hold other nodes.
    `root_title` — the synthetic root's display title.
    `id_prefix` — what a new node's id is minted with (`_new_id`).
    """

    kind: str
    folder: str
    leaf_type: str
    root_title: str
    id_prefix: str


MANUSCRIPT_TREE = TreeSpec(
    kind="manuscript",
    folder="scenes",
    leaf_type="manuscript:scene",
    root_title="Manuscript",
    id_prefix="manuscript",
)

RESEARCH_TREE = TreeSpec(
    kind="research",
    folder="research/notes",
    leaf_type="research:note",
    root_title="Research",
    id_prefix="note",
)
