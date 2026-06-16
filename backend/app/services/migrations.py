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
2. Append `(version, "short description", migrator_fn)` to MIGRATIONS.
3. `migrator_fn(root: Path) -> None` mutates files in place; raise on failure.

Defensive reads are still the default for additive changes. Only add a migration
when failing to migrate would break something downstream.
"""

from __future__ import annotations

import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

CURRENT_VERSION = 2
KEEP_BACKUPS = 3
BACKUP_DIRNAME = ".migration-backups"
SKIP_FROM_BACKUP = {".migration-backups", ".cache"}

logger = logging.getLogger(__name__)

MigrationFn = Callable[[Path], None]


def _create_snippets_folder(root: Path) -> None:
    """v1→v2: introduce the snippets/ folder for the snippet node kind."""
    (root / "snippets").mkdir(exist_ok=True)


# Each tuple: (target_version, description, function)
# Migrations run in registry order; gaps are not allowed.
MIGRATIONS: list[tuple[int, str, MigrationFn]] = [
    (2, "create snippets/ folder for snippet node kind", _create_snippets_folder),
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


def pending_migrations(current: int) -> list[tuple[int, str, MigrationFn]]:
    return [m for m in MIGRATIONS if current < m[0] <= CURRENT_VERSION]


def backup_project(root: Path, from_version: int) -> Path:
    backup_dir = root / BACKUP_DIRNAME
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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
    for target_version, description, migrator in pending:
        try:
            migrator(root)
        except Exception:
            logger.exception("Migration to v%s failed", target_version)
            raise
        write_project_version(root, target_version)
        applied.append(f"v{target_version}: {description}")

    # No migrations ran but the stamp was behind (e.g., pre-framework project
    # under CURRENT_VERSION=1 with empty registry). Stamp it forward so future
    # registrations behave correctly.
    if current < CURRENT_VERSION and not pending:
        write_project_version(root, CURRENT_VERSION)

    return applied
