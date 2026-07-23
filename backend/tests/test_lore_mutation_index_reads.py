"""What `build_mutations_index` may and may not read (#440).

All three tests here pin the same one-line decision: the index scans scene
*bodies* directly rather than going through `read_scene`. Two defects rode on
that call, and each of these fails if it comes back.

They are cost/claim tests, not wall-clock tests — the linearity one counts
`read_structure` calls, so it stays honest on a slow CI runner and still goes
red under the quadratic it was written against.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    UpsertMetadataFieldRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


class MutationIndexReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Mutation Index Reads")
        self.client = TestClient(app)
        self.honor = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor", entry_type="lore:character")
        ).id

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _new_scene(self, title: str, body: str = "", status: str = "draft") -> str:
        created = self.client.post("/api/scenes", json={"title": title})
        self.assertEqual(created.status_code, 200, created.text)
        scene_id = created.json()["id"]
        saved = self.client.put(
            f"/api/scenes/{scene_id}",
            json={"title": title, "body": body, "status": status},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        return scene_id

    def _redefine_status(self, options: list[str]) -> None:
        """Narrow the scene status vocabulary through the schema editor.

        `status` rather than a `metadata:` select on purpose: a select whose
        option set narrows is *healed* to empty on read, so it never reaches
        validation. `status` is intrinsic — a top-level front-matter key — and
        is validated rather than healed, which is what makes this the reachable
        trigger.
        """
        layers = self.service.read_metadata_schema_layers()
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layers.layers[-1].id,
                field_id="status",
                field=MetadataFieldDefinition(
                    name="Status",
                    type="select",
                    options=list(options),
                ),
                entry_type="scene:scene",
            )
        )

    # --- the scene the schema no longer accepts ---------------------------

    def test_a_scene_failing_validation_still_contributes_its_markers(self) -> None:
        """Retiring a `status` value leaves every scene still carrying it
        unreadable by `read_scene`. Their markers must keep resolving — the
        alternative is the whole downstream manuscript quietly changing meaning
        because one scene's front matter went stale."""
        opener = self._new_scene(
            "Opener",
            f"<!-- mutate:entity={self.honor};field=title;value=Captain;id=m1 -->",
            status="revised",
        )
        later = self._new_scene("Later", "Nothing happens here.")
        self.assertEqual(
            self.service.effective_state(self.honor, later), {"title": "Captain"}
        )

        # Retire the status the opener is carrying. The scene is now invalid.
        self._redefine_status(["draft", "complete"])
        with self.assertRaises(ProjectServiceError):
            self.service.read_scene(opener)

        self.assertEqual(
            self.service.effective_state(self.honor, later),
            {"title": "Captain"},
            "a scene the schema no longer validates still authored its markers",
        )

    def test_a_scene_failing_validation_still_closes_its_intervals(self) -> None:
        """The sharper half: a dropped scene takes its *close* markers with it,
        so an interval that ended stays open for the rest of the manuscript."""
        self._new_scene(
            "Opener",
            f"<!-- mutate:entity={self.honor};field=title;value=Captain;id=m1 -->",
        )
        closer = self._new_scene(
            "Closer", "<!-- mutate:close;ref=m1;id=c1 -->", status="revised"
        )
        after = self._new_scene("After", "Long afterwards.")
        self.assertEqual(self.service.effective_state(self.honor, after), {})

        self._redefine_status(["draft", "complete"])
        with self.assertRaises(ProjectServiceError):
            self.service.read_scene(closer)

        self.assertEqual(
            self.service.effective_state(self.honor, after),
            {},
            "the close still ends the interval once its scene stops validating",
        )

    # --- linearity --------------------------------------------------------

    def test_the_index_does_not_read_the_structure_once_per_scene(self) -> None:
        """`read_structure` is a full front-matter scan of the project, so one
        per scene is quadratic — 5 s at 50 scenes, 30 s at 150 when this was
        written. The count must not move with the manuscript's size."""
        counts: dict[int, int] = {}
        for scene_count in (4, 16):
            with TemporaryDirectory() as tmp:
                root = Path(tmp).resolve() / "project"
                service = open_test_project(root, "Cost")
                client = TestClient(app)
                honor = service.create_lore_entry(
                    CreateLoreEntryRequest(title="Honor", entry_type="lore:character")
                ).id
                for n in range(scene_count):
                    created = client.post("/api/scenes", json={"title": f"Scene {n}"})
                    scene_id = created.json()["id"]
                    client.put(
                        f"/api/scenes/{scene_id}",
                        json={
                            "title": f"Scene {n}",
                            # No space in the value — marker values are
                            # percent-encoded, so `Rank 0` simply does not match
                            # the pattern and scans to nothing.
                            "body": (
                                f"<!-- mutate:entity={honor};field=title;"
                                f"value=Rank-{n};id=m{n} -->"
                            ),
                        },
                    )

                calls = 0
                original = ProjectService._read_structure

                def counting(self, root, _original=original):  # type: ignore[no-untyped-def]
                    nonlocal calls
                    calls += 1
                    return _original(self, root)

                ProjectService._read_structure = counting  # type: ignore[assignment]
                try:
                    index = service.build_mutations_index()
                finally:
                    ProjectService._read_structure = original  # type: ignore[assignment]

                # Two vacuity guards, because an equality between two numbers
                # this test computed itself is satisfiable by doing nothing.
                # Without them, a manuscript that failed to build (0 == 0) or a
                # patch that stopped intercepting (0 == 0) both read as a pass.
                self.assertEqual(
                    len(index.by_entity.get(honor, [])),
                    scene_count,
                    "the manuscript under measurement did not actually build",
                )
                self.assertGreater(calls, 0, "the patch never intercepted a read")
                counts[scene_count] = calls

        self.assertEqual(
            counts[4],
            counts[16],
            f"structure reads grew with the manuscript: {counts}",
        )


if __name__ == "__main__":
    unittest.main()
