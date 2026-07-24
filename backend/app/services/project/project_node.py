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

import yaml

from app.models import ProjectNode, SaveProjectNodeRequest
from app.services.project.errors import ProjectServiceError


class ProjectNodeMixin:
    def _project_node_path(self) -> Path:
        return self._require_project() / "project.md"

    def read_project_node(self) -> ProjectNode:
        path = self._project_node_path()
        if not path.exists():
            # project.md always exists: create_project writes it first, and
            # there is no back-fill (the v3 migration was retired with #343),
            # so a folder without one is damaged. `validate_project` reports it
            # and `repair_project` recreates it — both of which write the file,
            # where minting an id is honest. Synthesizing a node here would mint
            # an identity that never reaches disk, so two reads would disagree.
            raise ProjectServiceError("Project node file project.md is missing.", 404)
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._require_node_id(path, front_matter)
        title = str(front_matter.get("title") or self._project_title(path.parent) or "Untitled Project")
        raw_entry_type = front_matter.get("entry_type") or "project:project"
        entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "project:project"
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        # Same read-side healing every other node kind gets (#345): the project
        # node has carried schema-driven metadata since #334, so it can hold a
        # reference whose target was deleted.
        metadata = self._strip_dangling_references(metadata, self.read_metadata_schema(), self._build_node_index())
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
        # never re-mints an id the file already has. Where the file has none to
        # carry (absent, or damaged into losing its id), a save is the sanctioned
        # repair: it mints, and unlike a read it writes what it minted, so the
        # id it hands back is the one on disk.
        node_id = (self._front_matter_id(path) if exists else None) or self._new_id("project")
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
        # project.yaml's title is the single source (#399 retired the cached
        # copy on the service), so keep it in step with the node's.
        #
        # Ordering note (#476): the project.md write above patches the memo's
        # project-node title and marks a deferred flush; this project.yaml write
        # then invalidates the whole memo (project.yaml fans out —
        # `_maintain_index_after_write`). The patch is **not** lost — invalidate
        # now flushes-before-clear, and the next resolve rebuilds cold and reads
        # the title back from project.md. The narrower "only invalidate when
        # `inherits` changed" rule the #476 comment floats is deliberately NOT
        # taken: the index reads its project-node title from project.md, never
        # from project.yaml, so a title sync is already index-irrelevant, and a
        # chain-diff that guessed wrong would serve a stale layer chain — a
        # silent-staleness bug traded for skipping one rebuild on a rare rename.
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
