"""Round-2 review of #1785 (PR #1807), Z10(a): the FastAPI `lifespan` hook
actually runs `migrate_assistant_tags_once` on startup — not just when a
project is opened (`MigrationRunnerMixin._run_migrations`'s own trigger,
covered by `test_migrations_tags.py`)."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from app.main import app


def test_lifespan_runs_the_machine_tag_migration_once(tmp_path) -> None:
    from app.services import machine_settings as ms

    # `_isolate_machine_settings` (conftest.py, autouse) already redirected
    # `config_path()` into this test's own tempdir — seed it with the
    # pre-migration machine state (v1 config + a legacy assistant-tags.yaml)
    # before the app ever starts.
    config_path = ms.config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump({"version": 1}, sort_keys=False), encoding="utf-8")
    (config_path.parent / "assistant-tags.yaml").write_text(
        yaml.safe_dump({"tags": [{"name": "Editor"}]}, sort_keys=False), encoding="utf-8"
    )

    with TestClient(app):
        pass  # entering the `with` block runs the lifespan startup hook

    tags_dir = config_path.parent / "tags"
    minted = list(tags_dir.glob("*.md"))
    assert len(minted) == 1
    front_matter = yaml.safe_load(minted[0].read_text(encoding="utf-8").split("---\n", 2)[1])
    assert front_matter["title"] == "Editor"
    assert front_matter["entry_type"] == "tag:assistant_tag"

    assert ms.load_settings().version == 2
    assert not (config_path.parent / "assistant-tags.yaml").exists()
    assert (config_path.parent / "assistant-tags.yaml.migrated").exists()
