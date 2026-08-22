"""Migration orchestration — the project-open runner + document pass (#366,
ADR-0071 §4).

`migrations.py` holds the pure pieces: the typed registry, `migrate_document`
(the isolated per-document entry point), version I/O, `backup_project`. This
mixin is the **orchestrator**, because it needs instance seams the pure module
cannot reach — `self._build_node_index`, `self._read/_write_markdown_with_front_matter`,
`self._metadata_schema_layer_id` — so it lives on `ProjectService` and runs
through a constructed instance, on open, before the service serves any request
(`ProjectService.opened_at`). `ProjectService` composes this mixin; shared
helpers (`self._require_project`, `self._build_node_index`,
`self._metadata_schema_layer_id`, `self._read_markdown_with_front_matter`,
`self._write_markdown_with_front_matter`) resolve via MRO.
"""

from __future__ import annotations

import logging

from app.services import migrations
from app.services.project.node_index_gate import node_index_gate
from app.services.project.overrides import OVERRIDES_FOLDER

logger = logging.getLogger(__name__)


class MigrationRunnerMixin:
    def _run_migrations(self) -> list[str]:
        """Run pending migrations for the open project: root steps against the root,
        then the document pass over every owned document, stamping once at the end
        (ADR-0071 §4). The orchestrator that replaces the old free migrate_project."""
        root = self.root_path
        if root is None or not (root / "project.yaml").exists():
            return []
        current = migrations.read_project_version(root)  # captured once, before any stamp
        pending = migrations.pending_migrations(current)
        if not pending:
            if current < migrations.CURRENT_VERSION:
                migrations.write_project_version(root, migrations.CURRENT_VERSION)
            return []
        migrations.backup_project(root, current)
        applied: list[str] = []
        for step in pending:
            if isinstance(step, migrations.RootMigration):
                try:
                    step.fn(root)
                except Exception:
                    logger.exception("Migration to v%s failed", step.version)
                    raise
            applied.append(f"v{step.version}: {step.description}")
        if any(isinstance(s, migrations.DocumentMigration) for s in pending):
            self._migrate_owned_documents(current)
        migrations.write_project_version(root, migrations.CURRENT_VERSION)
        return applied

    def _migrate_owned_documents(self, from_version: int) -> None:
        """Apply the document-scoped subladder to every content-bearing file the open
        project OWNS — index nodes AND its own overrides/*.md (ADR-0071 §3/§5). Writes
        a file back only when a step actually changed it."""
        root = self._require_project()
        # The node-index memo is process-global and survives across opens; invalidate
        # so the walk reflects post-root-step disk, not a stale prior-open index
        # (ADR-0071 §4; the Q7 ordering hazard).
        node_index_gate.invalidate()
        open_layer_id = self._metadata_schema_layer_id(root)
        index = self._build_node_index()
        paths = [e.path for e in index.by_id.values() if e.source_layer_id == open_layer_id]
        paths += sorted((root / OVERRIDES_FOLDER).glob("*.md"))  # own overrides (under root)
        for path in paths:
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            migrated = migrations.migrate_document(
                migrations.MigratableDocument(front_matter, body), from_version
            )
            # Compare the PARSED tuple, not bytes: the generic writer's format differs
            # from the kind writers', so a byte compare would churn every file. Only a
            # real content change writes (no mtime churn — ADR-0071 §4).
            if (migrated.front_matter, migrated.body) != (front_matter, body):
                self._write_markdown_with_front_matter(path, migrated.front_matter, migrated.body)
