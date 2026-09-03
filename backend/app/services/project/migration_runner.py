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

from app.services import machine_settings as ms_service
from app.services import migrations
from app.services.project.node_index_gate import node_index_gate
from app.services.project.overrides import OVERRIDES_FOLDER

logger = logging.getLogger(__name__)


class MigrationRunnerMixin:
    def _run_migrations(self, *, chain: migrations.ChainContext | None = None) -> list[str]:
        """Run pending migrations for the open project: root/chain steps against
        the root, then the document pass over every owned document, stamping once
        at the end (ADR-0071 §4). The orchestrator that replaces the old free
        migrate_project.

        `chain=None` (every real caller) means this is the TOP-LEVEL call for
        whatever project is being opened: it first migrates every declared
        ancestor project — `collect_layers(root)` (project layers only,
        outermost → root; a folder without its own `project.yaml` never reaches
        this list), each through its own lightweight `ProjectService`, running
        the FULL ladder against it exactly as this method does for the open
        root — accumulating one `ChainContext` across the whole walk (ADR-0082
        slice 4, #1785), so a descendant layer's chain step sees a name an
        ancestor's step already minted. `chain=<ctx>` (an ancestor's own
        recursive call, from just below) skips that walk — an ancestor's
        `inherits:` is not re-consulted from here — and just runs this one
        layer's own ladder against the SAME context.
        """
        root = self.root_path
        if root is None or not (root / "project.yaml").exists():
            return []
        if chain is None:
            from app.scope import WorkScope
            from app.services.project_service import ProjectService

            ctx = migrations.ChainContext(machine_names=self._seed_machine_tag_names())
            for layer in self.collect_layers(root):
                if layer.is_root or not (layer.folder / "project.yaml").exists():
                    continue
                applied = ProjectService(WorkScope(root=layer.folder))._run_migrations(chain=ctx)
                if applied:
                    logger.info("Migrated ancestor layer %s: %s", layer.folder, "; ".join(applied))
            result = self._run_migrations_for_this_layer(ctx)
            # One more invalidate after the WHOLE chain (on top of whatever
            # `_migrate_owned_documents` already did per layer): a chain step
            # (not a DocumentMigration) can mint/rewrite files at an ancestor
            # layer with no document-pass trigger of its own, and the open
            # project's later reads must see them.
            node_index_gate.invalidate()
            return result
        return self._run_migrations_for_this_layer(chain)

    @staticmethod
    def _seed_machine_tag_names() -> dict[str, str]:
        """The assistant-tag vocabulary a chain run's `ChainContext` starts
        from: run the machine's own once-only conversion (idempotent — a
        no-op past `version==2`; `main.py`'s startup hook is the primary
        trigger, this covers a project opened without the app ever starting,
        e.g. a script or a test), then read whatever `<machine>/tags/*.md`
        holds."""
        ms_service.migrate_assistant_tags_once()
        return ms_service.machine_tag_names()

    def _run_migrations_for_this_layer(self, ctx: migrations.ChainContext) -> list[str]:
        """One layer's own ladder — root/chain steps against `self.root_path`,
        then the document pass, stamped once. Split out from `_run_migrations`
        so the top-level call's ancestor walk can run this per ancestor without
        re-entering the walk itself (see `_run_migrations`'s docstring)."""
        root = self.root_path
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
            elif isinstance(step, migrations.ChainMigration):
                try:
                    step.fn(root, ctx)
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
