"""Migration v15 (ADR-0097 §10, #2375): one card per scene, a story rank on every
card, and each written card's synopsis seeded into its scene's summary.

The fixture is a v14 project built by hand — scenes with v12 placement, and plot
cards with the pre-v15 shapes the step has to settle: two cards on one scene, an
unwritten card, a card whose scene has no summary, one whose scene already has
one.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from app.services.migration_plot_cards import migrate_layer_plot_cards
from app.services.migrations import CURRENT_VERSION, ChainContext, read_project_version
from app.services.project_service import ProjectService

CH, S1, S2, S3, S4 = (
    "manuscript_ch00000001",
    "manuscript_s100000001",
    "manuscript_s200000001",
    "manuscript_s300000001",
    "manuscript_s400000001",
)


def _write(folder: Path, name: str, front: dict, body: str = "") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    text = "---\n" + yaml.safe_dump(front, sort_keys=False).strip() + "\n---\n\n" + body
    path.write_bytes(text.encode("utf-8"))
    return path


def _read(path: Path) -> tuple[dict, str]:
    _, block, body = path.read_text(encoding="utf-8").split("---\n", 2)
    return yaml.safe_load(block), body


class PlotCardsMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name).resolve() / "writing" / "book"
        ProjectService.created_at(self.root, "Book")
        for path in (self.root / "scenes").glob("*.md"):
            path.unlink()
        scenes = self.root / "scenes"
        # Reading order: S2 (rank 1 of the chapter) comes BEFORE S1 (rank 2); S3, S4 after.
        _write(scenes, "chapter.md", {"id": CH, "title": "Chapter", "entry_type": "manuscript:container", "rank": 1})
        _write(scenes, "s1.md", {"id": S1, "title": "Landing", "entry_type": "manuscript:scene", "status": "draft",
                                 "parent": CH, "rank": 2, "metadata": {}}, "Prose one.\n")
        _write(scenes, "s2.md", {"id": S2, "title": "Arrival", "entry_type": "manuscript:scene", "status": "draft",
                                 "parent": CH, "rank": 1, "metadata": {"summary": "Already summarised."}}, "Prose two.\n")
        _write(scenes, "s3.md", {"id": S3, "title": "Fire", "entry_type": "manuscript:scene", "status": "draft",
                                 "parent": CH, "rank": 3, "metadata": {}}, "Prose three.\n")
        _write(scenes, "s4.md", {"id": S4, "title": "Aftermath", "entry_type": "manuscript:scene", "status": "draft",
                                 "parent": CH, "rank": 4, "metadata": {}}, "Prose four.\n")
        plot = self.root / "plot"
        card = {"entry_type": "plot:card"}
        self.cards = {
            # Two cards on S1: the smaller id keeps it.
            "plot_a": _write(plot, "a.md", {"id": "plot_a", **card, "title": "A", "metadata": {"scene": S1, "page_status": "on_page"}}, "Plan A.\n"),
            "plot_b": _write(plot, "b.md", {"id": "plot_b", **card, "title": "B", "metadata": {"scene": S1, "page_status": "on_page"}}, "Plan B.\n"),
            # S2 already has a summary: both texts stay.
            "plot_c": _write(plot, "c.md", {"id": "plot_c", **card, "title": "C", "metadata": {"scene": S2}}, "Plan C.\n"),
            # S3 has none and the card has no body: nothing to seed.
            "plot_d": _write(plot, "d.md", {"id": "plot_d", **card, "title": "D", "metadata": {"scene": S3}}, ""),
            # Unwritten cards sort by title, case-insensitive.
            "plot_e": _write(plot, "e.md", {"id": "plot_e", **card, "title": "zebra", "metadata": {}}, "Zebra.\n"),
            "plot_f": _write(plot, "f.md", {"id": "plot_f", **card, "title": "Apple", "metadata": {}}, "Apple.\n"),
            "plot_pl": _write(plot, "pl.md", {"id": "plot_pl", "title": "Thread", "entry_type": "plot:plotline", "metadata": {}}),
        }
        manifest = yaml.safe_load((self.root / "project.yaml").read_text(encoding="utf-8"))
        manifest["schema_version"] = 14
        (self.root / "project.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    def _front(self, card_id: str) -> dict:
        return _read(self.cards[card_id])[0]

    def _migrate(self) -> None:
        migrate_layer_plot_cards(self.root, ChainContext())

    def test_current_version_is_15(self) -> None:
        self.assertEqual(CURRENT_VERSION, 15)

    def test_a_scene_held_twice_stays_with_the_smaller_id(self) -> None:
        self._migrate()
        self.assertEqual(self._front("plot_a")["metadata"]["scene"], S1)
        loser = self._front("plot_b")["metadata"]
        self.assertNotIn("scene", loser)
        # `on_page` is derived from a scene; an unwritten card must not keep it.
        self.assertNotIn("page_status", loser)
        # Nothing is deleted and the body stays.
        self.assertEqual(_read(self.cards["plot_b"])[1].strip(), "Plan B.")

    def test_ranks_run_through_the_manuscript_then_the_rest_by_title(self) -> None:
        self._migrate()
        ranks = {cid: self._front(cid).get("story_rank") for cid in self.cards}
        # Written: C (S2, first in reading order), A (S1), D (S3); then unwritten by title: Apple, B, zebra.
        self.assertEqual(
            [cid for cid, _ in sorted(((c, r) for c, r in ranks.items() if r is not None), key=lambda p: p[1])],
            ["plot_c", "plot_a", "plot_d", "plot_f", "plot_b", "plot_e"],
        )
        self.assertEqual(sorted(r for r in ranks.values() if r is not None), [1, 2, 3, 4, 5, 6])
        self.assertNotIn("story_rank", self._front("plot_pl"))

    def test_the_summary_is_seeded_only_where_the_scene_has_none(self) -> None:
        self._migrate()
        scenes = self.root / "scenes"
        self.assertEqual(_read(scenes / "s1.md")[0]["metadata"]["summary"], "Plan A.")
        # Both non-empty: the scene's summary stays, and the card keeps its own text.
        self.assertEqual(_read(scenes / "s2.md")[0]["metadata"]["summary"], "Already summarised.")
        self.assertEqual(_read(self.cards["plot_c"])[1].strip(), "Plan C.")
        # No card body: no summary invented.
        self.assertNotIn("summary", _read(scenes / "s3.md")[0]["metadata"])

    def test_the_scene_keeps_its_placement_and_prose(self) -> None:
        self._migrate()
        front, body = _read(self.root / "scenes" / "s1.md")
        self.assertEqual((front["parent"], front["rank"], front["status"]), (CH, 2, "draft"))
        self.assertEqual(body.strip(), "Prose one.")

    def test_a_rerun_changes_nothing(self) -> None:
        self._migrate()
        snapshot = {p: p.read_bytes() for p in [*self.cards.values(), *(self.root / "scenes").glob("*.md")]}
        self._migrate()
        self.assertEqual(snapshot, {p: p.read_bytes() for p in snapshot})

    def test_a_card_already_ranked_leaves_the_ranking_alone(self) -> None:
        # Some card already has a rank (a re-run, or a hand edit): seed none.
        _write(self.root / "plot", "e.md",
               {"id": "plot_e", "entry_type": "plot:card", "title": "zebra", "metadata": {}, "story_rank": 7}, "Zebra.\n")
        self._migrate()
        self.assertEqual(self._front("plot_e")["story_rank"], 7)
        self.assertNotIn("story_rank", self._front("plot_a"))

    def test_open_runs_the_step_and_the_project_reads_at_the_current_version(self) -> None:
        service = ProjectService.opened_at(self.root)
        self.assertEqual(read_project_version(self.root), CURRENT_VERSION)
        cards = {card.id: card for card in service.list_cards().entries}
        self.assertEqual(cards["plot_c"].story_rank, 1)
        self.assertNotIn("scene", {k for k, v in cards["plot_b"].metadata.items() if v})
        self.assertEqual(service.read_card("plot_a").story_rank, 2)


if __name__ == "__main__":
    unittest.main()
