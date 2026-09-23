"""ADR-0093 §1/§2: `use(node, snapshot=id)` — the call records a pair and
emits nothing (never reads the store); the preview mirrors what the send
would place, in the stable tier, as the reader's before element.

Fixture pattern copied from `test_lore_gate.py` (`open_test_project` +
`build_preview`); the HTTP-level preview-mirror tests reuse `test_ai_preview.py`'s
`TestClient` pattern.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest
from app.services.ai.helpers import (
    USE_SNAPSHOT_NEEDS_AN_ID,
    USE_SNAPSHOT_NEEDS_ONE_ENTRY,
    USE_SNAPSHOT_UNRESOLVED,
)
from app.services.ai.preview import PreviewRequest, build_preview
from app.services.ai.sessions import default_registry

_SYS = '{% role "system" %}'
_END = "{% endrole %}"


class UseSnapshotRecordTests(unittest.TestCase):
    """`use(node, snapshot=id)` records the pair at render time and emits
    nothing — the render never consults the store (ADR-0093 §1)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Use Snapshot")
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Watch Barracks", entry_type="lore:note")
        )
        self.entry_id = entry.id

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _render(self, template_source: str):
        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=template_source,
                target_scene_id="",
                session_id=None,
                inputs={},
                text_before="",
                text_after="",
                commit=False,
            ),
        )
        return rendered

    def test_records_pair_and_emits_nothing(self) -> None:
        rendered = self._render(
            f'{_SYS}[{{{{ use("{self.entry_id}", snapshot="snap_1") }}}}]{_END}'
        )
        self.assertEqual(rendered.used_snapshots, [(self.entry_id, "snap_1")])
        self.assertEqual(rendered.messages[0].text, "[]")

    def test_used_node_ids_untouched_by_a_snapshot_pick(self) -> None:
        rendered = self._render(
            f'{_SYS}{{{{ use("{self.entry_id}", snapshot="snap_1") }}}}{_END}'
        )
        self.assertEqual(rendered.used_node_ids, [])

    def test_hint_ignored_on_a_snapshot_pick(self) -> None:
        rendered = self._render(
            f'{_SYS}{{{{ use("{self.entry_id}", "stable", snapshot="snap_1") }}}}{_END}'
        )
        self.assertEqual(rendered.used_node_hints, {})
        self.assertEqual(rendered.used_snapshots, [(self.entry_id, "snap_1")])

    def test_empty_string_snapshot_is_a_plain_pick(self) -> None:
        rendered = self._render(
            f'{_SYS}{{{{ use("{self.entry_id}", "stable", snapshot="") }}}}{_END}'
        )
        self.assertEqual(rendered.used_node_ids, [self.entry_id])
        self.assertEqual(rendered.used_node_hints, {self.entry_id: "stable"})
        self.assertEqual(rendered.used_snapshots, [])

    def test_none_snapshot_is_a_plain_pick(self) -> None:
        rendered = self._render(f'{_SYS}{{{{ use("{self.entry_id}") }}}}{_END}')
        self.assertEqual(rendered.used_node_ids, [self.entry_id])
        self.assertEqual(rendered.used_snapshots, [])

    def test_two_element_selection_warns_and_records_nothing(self) -> None:
        other = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Second", entry_type="lore:note")
        )
        rendered = self._render(
            f'{_SYS}{{{{ use([{{"id": "{self.entry_id}"}}, {{"id": "{other.id}"}}], '
            f'snapshot="snap_1") }}}}{_END}'
        )
        self.assertEqual(rendered.used_snapshots, [])
        self.assertIn(USE_SNAPSHOT_NEEDS_ONE_ENTRY, rendered.warnings)

    def test_one_element_picker_shaped_list_resolves(self) -> None:
        # The RECORDING step resolves the one-element list cleanly — no
        # `USE_SNAPSHOT_NEEDS_ONE_ENTRY`/`USE_SNAPSHOT_UNRESOLVED` warning. The
        # snapshot id itself doesn't exist, so the separate PLACEMENT step (the
        # preview mirror computing send-path tiers) adds its own warning —
        # that's `UseSnapshotPreviewMirrorTests`' concern, not this one's.
        rendered = self._render(
            f'{_SYS}{{{{ use([{{"id": "{self.entry_id}"}}], snapshot="snap_1") }}}}{_END}'
        )
        self.assertEqual(rendered.used_snapshots, [(self.entry_id, "snap_1")])
        self.assertNotIn(USE_SNAPSHOT_NEEDS_ONE_ENTRY, rendered.warnings)
        self.assertNotIn(USE_SNAPSHOT_UNRESOLVED, rendered.warnings)

    def test_undefined_snapshot_input_is_a_plain_pick(self) -> None:
        # `inputs.baseline` is never declared/seeded — under StrictUndefined a
        # dict miss becomes an `Undefined` instance, which is fine to hand
        # around as an argument; it only raises when USED (stringified,
        # iterated, compared). `_is_empty_snapshot` merely isinstance-checks
        # it, so this must render with no error.
        rendered = self._render(
            f'{_SYS}{{{{ use("{self.entry_id}", snapshot=inputs.baseline) }}}}{_END}'
        )
        self.assertEqual(rendered.used_node_ids, [self.entry_id])
        self.assertEqual(rendered.used_snapshots, [])

    def test_non_string_snapshot_warns_and_records_nothing(self) -> None:
        # A picker selection (a one-element list) handed to `snapshot=` by
        # mistake is caught at the render, not at the send.
        rendered = self._render(
            f'{_SYS}{{{{ use("{self.entry_id}", snapshot=[{{"id": "{self.entry_id}"}}]) }}}}{_END}'
        )
        self.assertEqual(rendered.used_snapshots, [])
        self.assertEqual(rendered.used_node_ids, [])
        self.assertIn(USE_SNAPSHOT_NEEDS_AN_ID, rendered.warnings)

    def test_unresolved_node_warns(self) -> None:
        rendered = self._render(f'{_SYS}{{{{ use("", snapshot="snap_1") }}}}{_END}')
        self.assertEqual(rendered.used_snapshots, [])
        self.assertIn(USE_SNAPSHOT_UNRESOLVED, rendered.warnings)


class UseSnapshotPreviewMirrorTests(unittest.TestCase):
    """The preview mirrors what the send would place: the before element in
    the stable tier, the door's block shape, the HTTP response's
    `used_snapshots` (ADR-0093 §2)."""

    def setUp(self) -> None:
        default_registry.clear()
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Use Snapshot Preview")
        self.client = TestClient(app)
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Watch Barracks", entry_type="lore:note")
        )
        self.entry_id = entry.id
        existing = self.service.read_lore_entry(entry.id)
        self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Watch Barracks",
                body="Garrison of the city guard.",
                base_revision=existing.revision,
                entry_type="lore:note",
                metadata={},
            ),
        )
        self.snapshot = self.service.capture_snapshot(
            entry.id, kind="lore", origin="propagation"
        )

    def tearDown(self) -> None:
        default_registry.clear()
        self.temp_dir.cleanup()

    def test_preview_places_before_element_in_stable_tier(self) -> None:
        source = f'{_SYS}{{{{ use("{self.entry_id}", snapshot="{self.snapshot.id}") }}}}{_END}'
        response = self.client.post(
            "/api/ai/preview", json={"template_source": source, "target_scene_id": ""}
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["lore_enabled"])
        self.assertEqual(
            body["used_snapshots"],
            [{"entry_id": self.entry_id, "snapshot_id": self.snapshot.id}],
        )
        stable = [b for b in body["cache_blocks"] if b["label"] == "stable lore"]
        self.assertTrue(stable, body["cache_blocks"])
        block = stable[0]
        key = f"{self.entry_id}@{self.snapshot.id}"
        self.assertEqual(len(block["snapshots"]), 1)
        self.assertEqual(block["snapshots"][0]["key"], key)
        self.assertIn(key, block["entry_xml"])
        self.assertNotIn(key, block["entry_ids"])
        self.assertIn(f'snapshot="{self.snapshot.id}"', block["entry_xml"][key])
        self.assertIn("captured=", block["entry_xml"][key])

    def test_missing_snapshot_warns_and_places_nothing(self) -> None:
        source = f'{_SYS}{{{{ use("{self.entry_id}", snapshot="not-a-snap") }}}}{_END}'
        response = self.client.post(
            "/api/ai/preview", json={"template_source": source, "target_scene_id": ""}
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["warnings"]), 1)
        self.assertEqual(
            [b for b in body["cache_blocks"] if b["label"] == "stable lore"], []
        )

    def test_never_policy_source_places_nothing_and_warns_nothing(self) -> None:
        never = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Hidden", entry_type="lore:note")
        )
        existing = self.service.read_lore_entry(never.id)
        self.service.save_lore_entry(
            never.id,
            SaveLoreEntryRequest(
                title="Hidden",
                body="",
                base_revision=existing.revision,
                entry_type="lore:note",
                metadata={"context_policy": "never"},
            ),
        )
        snap = self.service.capture_snapshot(never.id, kind="lore", origin="propagation")
        source = f'{_SYS}{{{{ use("{never.id}", snapshot="{snap.id}") }}}}{_END}'
        response = self.client.post(
            "/api/ai/preview", json={"template_source": source, "target_scene_id": ""}
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["warnings"], [])
        self.assertEqual(
            [b for b in body["cache_blocks"] if b["label"] == "stable lore"], []
        )


if __name__ == "__main__":
    unittest.main()
