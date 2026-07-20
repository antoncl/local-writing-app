"""Project-node singleton slice of ProjectService (#14 backend split).

The per-folder project node (project.md): book/series metadata, blurb, etc.
It is addressed without an id (one singleton per folder), so it sits outside
the kind-polymorphic node ops. This mixin owns its read/save + file IO;
`ProjectService` composes it. Shared tooling resolves via the MRO
(`_require_project`, `read_metadata_schema`, `_normalise_metadata`, the
metadata-value strip/validate helpers, markdown IO, `_maybe_rename_node_file`,
`_read_yaml`/`_write_yaml`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.models import ProjectNode, SaveProjectNodeRequest
from app.services.project.errors import ProjectServiceError


class ProjectNodeMixin:
    def _project_node_path(self) -> Path:
        return self._require_project() / "project.md"

    def _project_node_id(self, front_matter: dict[str, Any]) -> str:
        """The project node's identity, read from front matter like any node.

        Minted (#343) rather than constant: the singleton-per-folder *address*
        is what stays stable, not the id. Only a project node written before
        the id existed lands in the mint branch.
        """
        raw_id = front_matter.get("id")
        if isinstance(raw_id, str) and raw_id.strip():
            return raw_id.strip()
        return self._new_id("project")

    def read_project_node(self) -> ProjectNode:
        path = self._project_node_path()
        if not path.exists():
            # Should be auto-created by the v3 migration on open. If the file
            # is genuinely missing (e.g. brand-new project before migration
            # runs), synthesize from project.yaml's title.
            manifest = self._read_yaml(self._require_project() / "project.yaml")
            return ProjectNode(
                id=self._new_id("project"),
                title=str(manifest.get("title") or self.title or "Untitled Project"),
                body="",
                revision="",
                entry_type="project:project",
                metadata={},
            )
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._project_node_id(front_matter)
        title = str(front_matter.get("title") or self.title or "Untitled Project")
        raw_entry_type = front_matter.get("entry_type") or "project:project"
        entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "project:project"
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        return ProjectNode(
            id=node_id,
            title=title,
            body=body,
            revision=self._revision(path),
            entry_type=entry_type,
            metadata=metadata,
            computed_metadata=self._computed_entry_metadata(body, node_id=node_id, entry_type=entry_type),
        )

    def save_project_node(self, request: SaveProjectNodeRequest) -> ProjectNode:
        path = self._project_node_path()
        exists = path.exists()
        current_revision = self._revision(path) if exists else ""
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Project node changed on disk after it was opened.", 409)
        # Identity is carried by the file, not by the save request — a save
        # must never re-mint it.
        if exists:
            node_id = self._project_node_id(self._read_front_matter_only(path, strict=True))
        else:
            node_id = self._new_id("project")
        metadata = self._normalise_metadata(request.metadata, path)
        node = ProjectNode(
            id=node_id,
            title=request.title,
            body=request.body,
            revision=current_revision,
            entry_type=request.entry_type,
            metadata=metadata,
        )
        self._write_project_node_file(path, node)
        # Keep the cached title and project.yaml's title in sync so legacy
        # readers (current_project, etc.) see the latest value.
        self.title = request.title
        self._sync_project_yaml_title(request.title)
        return self.read_project_node()

    def _write_project_node_file(self, path: Path, node: ProjectNode) -> None:
        front_matter = yaml.safe_dump(
            {
                "id": node.id,
                "title": node.title,
                "entry_type": node.entry_type,
                "metadata": node.metadata,
            },
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body = node.body.rstrip() + "\n" if node.body.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body}")

    def _sync_project_yaml_title(self, title: str) -> None:
        root = self._require_project()
        manifest_path = root / "project.yaml"
        if not manifest_path.exists():
            return
        manifest = self._read_yaml(manifest_path)
        if manifest.get("title") == title:
            return
        manifest["title"] = title
        self._write_yaml(manifest_path, manifest)
