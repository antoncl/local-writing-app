"""Project schema migrations.

Conventions:
- `CURRENT_VERSION` is the schema version the codebase represents.
- New projects are stamped with `schema_version: CURRENT_VERSION` on creation;
  they never run migrations on first open.
- Existing projects without `schema_version` are treated as version 0.
- Each entry in `MIGRATIONS` runs once to take the project from N-1 to N.
- Migrations run inside open_project, after the manifest is detected but before
  any other side effects. The whole project is zipped to
  `<root>/.migration-backups/v{from}-{utc-ts}.zip` first; the last 3 backups are
  kept and older ones are pruned.

Adding a migration:
1. Bump CURRENT_VERSION.
2. Append `RootMigration(version, "short description", migrator_fn)` to MIGRATIONS.
3. `migrator_fn(root: Path) -> None` mutates files in place; raise on failure.

Defensive reads are still the default for additive changes. Only add a migration
when failing to migrate would break something downstream.

Two shapes (ADR-0071 §1): `RootMigration` is for project-shaped changes — folders,
cross-file moves, `*.structure.yaml`, the schema — its `fn` mutates the project
root. `DocumentMigration` is for content transforms of one document in isolation
— its `fn` takes/returns a `MigratableDocument` and never sees the root or
sibling files. Reach for `DocumentMigration` when the content that needs
migrating doesn't always live under the project tree: a snapshot restored later
(ADR-0043) only has the document body to migrate against, so only the document
shape can reach it. `migrate_document` applies the `DocumentMigration` subladder
to a single document; the project-wide pass that runs it over every owned
document is slice 2 (#366).
"""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# Independent of MIGRATIONS on purpose: it is the version the code represents,
# not the height of the ladder. Deriving it (e.g. max(m[0] for m in MIGRATIONS))
# would throw on an empty registry and take the stamp-forward path down with it.
CURRENT_VERSION = 5
KEEP_BACKUPS = 3
BACKUP_DIRNAME = ".migration-backups"
# `snapshots/` is excluded because migrations never touch it: snapshots are
# immutable at rest and migrate at *restore*, over that one body, on the way out
# (ADR-0043). So the pre-migration zip has nothing to protect there, and
# excluding it keeps the three retained backups from each carrying a full copy
# of the project's history. Immutability at rest is what buys this; the two
# decisions stand or fall together.
SKIP_FROM_BACKUP = {".migration-backups", ".cache", "snapshots"}

logger = logging.getLogger(__name__)

MigrationFn = Callable[[Path], None]


@dataclass(frozen=True)
class MigratableDocument:
    """One document's content in isolation (ADR-0071 §1): the entire parsed
    front-matter mapping + the markdown body — exactly what
    _read_markdown_with_front_matter yields. A DocumentMigrationFn transforms this
    and nothing else: no root, no filesystem, no sibling documents."""

    front_matter: dict[str, Any]
    body: str


DocumentMigrationFn = Callable[[MigratableDocument], MigratableDocument]


@dataclass(frozen=True)
class RootMigration:
    """A project-shaped step (folders, cross-file moves, *.structure.yaml, the
    schema): fn mutates the project ROOT in place (ADR-0071 §1)."""

    version: int
    description: str
    fn: MigrationFn


@dataclass(frozen=True)
class DocumentMigration:
    """A content step: fn transforms ONE document in isolation (ADR-0071 §1/§3).
    Must be idempotent (re-applying to an already-migrated document is a no-op —
    ADR-0071 §2) and authored against the KNOWN format at its version transition,
    never reading the live schema."""

    version: int
    description: str
    fn: DocumentMigrationFn


MigrationStep = RootMigration | DocumentMigration


def _create_snippets_folder(root: Path) -> None:
    """v1→v2: introduce the snippets/ folder for the snippet node kind."""
    (root / "snippets").mkdir(exist_ok=True)


def _create_research_structure(root: Path) -> None:
    """v4→v5: introduce the research kind. Create research/notes/ for
    note markdown files and seed an empty research.structure.yaml so
    the validate/read paths don't have to special-case its absence
    (docs/research-strategy.md, slice 1)."""
    (root / "research" / "notes").mkdir(parents=True, exist_ok=True)
    structure_path = root / "research.structure.yaml"
    if structure_path.exists():
        return
    initial = {
        "root": {
            "id": "root",
            "type": "root",
            "title": "Research",
            "children": [],
        }
    }
    structure_path.write_text(
        yaml.safe_dump(initial, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


# Migrations run in registry order. Version numbers are history and are never
# reused or renumbered, so a retired step leaves a gap. Two gaps now: 3 (create
# project.md) was removed with #343 — it wrote a constant `id: project`, which
# collides at every layer of a nested chain; and 4 (move chat cost_usd_total
# into ai_invocations.yaml) was removed with #76 — pre-1.0 the only projects
# that would run it are recreated from scratch, so it had already served its
# purpose and was pure carrying cost. A folder sitting at a retired version is
# carried forward by the remaining steps and the final stamp-to-CURRENT_VERSION.
MIGRATIONS: list[MigrationStep] = [
    RootMigration(2, "create snippets/ folder for snippet node kind", _create_snippets_folder),
    RootMigration(5, "create research/ folder and research.structure.yaml", _create_research_structure),
]


def read_project_version(root: Path) -> int:
    manifest_path = root / "project.yaml"
    if not manifest_path.exists():
        return 0
    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return 0
    if not isinstance(data, dict):
        return 0
    value = data.get("schema_version")
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def write_project_version(root: Path, version: int) -> None:
    manifest_path = root / "project.yaml"
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RuntimeError("project.yaml is not a YAML mapping; refusing to stamp schema_version.")
    data["schema_version"] = version
    manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def pending_migrations(current: int) -> list[MigrationStep]:
    return [m for m in MIGRATIONS if current < m.version <= CURRENT_VERSION]


def migrate_document(doc: MigratableDocument, from_version: int) -> MigratableDocument:
    """Apply the document-scoped subladder from `from_version` to CURRENT_VERSION,
    in version order, over one body — no root, no service (ADR-0071 §4). The
    isolated entry point behind the snapshot restore (slice 3) and the project
    document pass (slice 2)."""
    for step in MIGRATIONS:
        if isinstance(step, DocumentMigration) and from_version < step.version <= CURRENT_VERSION:
            doc = step.fn(doc)
    return doc


def backup_project(root: Path, from_version: int) -> Path:
    backup_dir = root / BACKUP_DIRNAME
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_path = backup_dir / f"v{from_version}-{timestamp}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            top = relative.parts[0]
            if top in SKIP_FROM_BACKUP:
                continue
            archive.write(path, relative)
    prune_old_backups(root)
    return archive_path


def prune_old_backups(root: Path, keep: int = KEEP_BACKUPS) -> None:
    backup_dir = root / BACKUP_DIRNAME
    if not backup_dir.exists():
        return
    archives = sorted(
        backup_dir.glob("v*-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for stale in archives[keep:]:
        try:
            stale.unlink()
        except OSError:
            logger.warning("Could not prune stale migration backup: %s", stale)


def migrate_project(root: Path) -> list[str]:
    """Run pending migrations on the project.

    Returns a list of human-readable descriptions of applied migrations.
    Empty list means the project was already at the current version.
    """
    if not (root / "project.yaml").exists():
        return []

    current = read_project_version(root)
    pending = pending_migrations(current)

    if pending:
        backup_project(root, current)

    applied: list[str] = []
    for step in pending:
        if isinstance(step, RootMigration):
            try:
                step.fn(root)
            except Exception:
                logger.exception("Migration to v%s failed", step.version)
                raise
        else:  # DocumentMigration
            # Document-scoped steps are run by the ProjectService document pass over
            # every owned document (ADR-0071 §4, slice 2), not by this root runner.
            # None may be registered before that pass lands — fail loud if one is.
            raise RuntimeError(
                f"DocumentMigration v{step.version} cannot run in migrate_project — "
                "the ProjectService document pass (ADR-0071 §4, #366 slice 2) is not wired yet."
            )
        write_project_version(root, step.version)
        applied.append(f"v{step.version}: {step.description}")

    # No migrations ran but the stamp was behind (e.g., pre-framework project
    # under CURRENT_VERSION=1 with empty registry). Stamp it forward so future
    # registrations behave correctly.
    if current < CURRENT_VERSION and not pending:
        write_project_version(root, CURRENT_VERSION)

    return applied
