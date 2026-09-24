"""The pure half of tree placement (ADR-0094 §2, §5, §6): rank arithmetic, the
write plan a placement makes, the one-line text edit, and the tree builder's
rules for a placement it cannot honour."""

from __future__ import annotations

import unittest
from decimal import Decimal

from app.services.project.placement import (
    Sibling,
    content_without_placement,
    parse_parent,
    parse_rank,
    plan_placement,
    rank_between,
    rank_sort_key,
    set_placement_in_text,
)
from app.services.project.tree_build import TreeEntry, build_tree


def _order(group: list[Sibling], writes: list[tuple[str, Decimal]]) -> list[str]:
    """The group's order after applying `writes` one at a time — asserting at
    every intermediate state is what the crash-safety claim is about."""
    ranks = {sibling.id: sibling.rank for sibling in group}
    for node_id, rank in writes:
        ranks[node_id] = float(rank)
    return sorted(ranks, key=lambda i: rank_sort_key(i, ranks[i]))


class RankBetweenTests(unittest.TestCase):
    def test_the_adr_sequence(self) -> None:
        self.assertEqual(rank_between(2, 3), Decimal("2.5"))
        self.assertEqual(rank_between(2, 2.5), Decimal("2.3"))
        self.assertEqual(rank_between(2, 2.3), Decimal("2.2"))
        self.assertEqual(rank_between(2, 2.2), Decimal("2.1"))
        self.assertEqual(rank_between(2, 2.1), Decimal("2.05"))

    def test_whole_numbers_when_they_fit(self) -> None:
        self.assertEqual(rank_between(1, 4), Decimal("3"))

    def test_no_room_past_six_decimals_or_out_of_order(self) -> None:
        self.assertIsNone(rank_between(1, 1.000001))
        self.assertIsNone(rank_between(2, 2))
        self.assertIsNone(rank_between(3, 2))


class ParseTests(unittest.TestCase):
    def test_a_boolean_or_a_string_is_not_a_rank(self) -> None:
        self.assertIsNone(parse_rank(True))
        self.assertIsNone(parse_rank("3"))
        self.assertIsNone(parse_rank(float("nan")))
        self.assertEqual(parse_rank(3), 3.0)
        self.assertEqual(parse_rank(2.5), 2.5)

    def test_parent(self) -> None:
        self.assertIsNone(parse_parent(""))
        self.assertIsNone(parse_parent(7))
        self.assertEqual(parse_parent(" manuscript_a "), "manuscript_a")


class PlanPlacementTests(unittest.TestCase):
    def test_between_neighbours_is_one_write(self) -> None:
        group = [Sibling("a", 1), Sibling("b", 2), Sibling("c", 3), Sibling("d", 4)]
        writes = plan_placement(group, "d", 1)
        self.assertEqual(writes, [("d", Decimal("1.5"))])
        self.assertEqual(_order(group, writes), ["a", "d", "b", "c"])

    def test_first_and_last(self) -> None:
        group = [Sibling("a", 1), Sibling("b", 2)]
        self.assertEqual(plan_placement(group, "x", 0), [("x", Decimal(0))])
        self.assertEqual(plan_placement(group, "x", 2), [("x", Decimal(3))])
        self.assertEqual(plan_placement([], "x", 0), [("x", Decimal(1))])

    def test_already_there_writes_nothing(self) -> None:
        group = [Sibling("a", 1), Sibling("b", 2), Sibling("c", 3)]
        self.assertEqual(plan_placement(group, "b", 1), [])
        self.assertEqual(plan_placement(group, "c", 2), [])

    def test_the_renumber_is_correct_at_every_step_mover_included(self) -> None:
        """The case that breaks a renumber which leaves the mover out:
        A=1, B=1, C=2; move C between A and B."""
        group = [Sibling("a", 1), Sibling("b", 1), Sibling("c", 2)]
        writes = plan_placement(group, "c", 1)
        before = _order(group, [])
        for step in range(len(writes) - 1):
            # Until the final write places the mover, the order is the old one.
            self.assertEqual(_order(group, writes[: step + 1]), before)
        self.assertEqual(_order(group, writes), ["a", "c", "b"])
        self.assertEqual([node_id for node_id, _ in writes[:3]], ["c", "b", "a"])

    def test_a_missing_neighbour_rank_renumbers(self) -> None:
        group = [Sibling("a", 1), Sibling("b", None)]
        writes = plan_placement(group, "x", 1)
        self.assertEqual(_order(group + [Sibling("x", None)], writes), ["a", "x", "b"])

    def test_a_worn_out_gap_renumbers_above_the_highest(self) -> None:
        group = [Sibling("a", 1), Sibling("b", 1.000001), Sibling("c", 2)]
        writes = plan_placement(group, "x", 1)
        self.assertTrue(all(rank > 2 for _, rank in writes))
        self.assertEqual(_order(group + [Sibling("x", None)], writes), ["a", "x", "b", "c"])


class TextEditTests(unittest.TestCase):
    SCENE = "---\nid: manuscript_a\ntitle: The Landing\nentry_type: manuscript:scene\nstatus: draft\nmetadata: {}\n---\n\nBody.\n"

    def test_a_placement_adds_two_lines_after_entry_type_and_nothing_else(self) -> None:
        placed = set_placement_in_text(self.SCENE, "manuscript_ch", Decimal("2.5"))
        self.assertEqual(
            placed,
            "---\nid: manuscript_a\ntitle: The Landing\nentry_type: manuscript:scene\n"
            "parent: manuscript_ch\nrank: 2.5\nstatus: draft\nmetadata: {}\n---\n\nBody.\n",
        )

    def test_a_move_changes_one_line(self) -> None:
        placed = set_placement_in_text(self.SCENE, "manuscript_ch", 3)
        moved = set_placement_in_text(placed, "manuscript_ch", 1)
        changed = [(a, b) for a, b in zip(placed.splitlines(), moved.splitlines(), strict=True) if a != b]
        self.assertEqual(changed, [("rank: 3", "rank: 1")])

    def test_moving_to_the_top_drops_parent(self) -> None:
        placed = set_placement_in_text(self.SCENE, "manuscript_ch", 3)
        self.assertNotIn("parent:", set_placement_in_text(placed, None, 3))

    def test_crlf_files_keep_crlf(self) -> None:
        crlf = self.SCENE.replace("\n", "\r\n")
        placed = set_placement_in_text(crlf, "manuscript_ch", 1)
        self.assertNotIn("\n", placed.replace("\r\n", ""))

    def test_the_revision_content_ignores_placement(self) -> None:
        a = set_placement_in_text(self.SCENE, "manuscript_ch", 1).encode()
        b = set_placement_in_text(self.SCENE, None, 7).encode()
        self.assertEqual(content_without_placement(a), content_without_placement(b))
        self.assertEqual(content_without_placement(a), self.SCENE.encode())

    def test_an_indented_parent_key_in_metadata_is_content(self) -> None:
        text = self.SCENE.replace("metadata: {}", "metadata:\n  parent: someone")
        self.assertIn(b"  parent: someone", content_without_placement(text.encode()))


class BuildTreeTests(unittest.TestCase):
    @staticmethod
    def _build(*entries: TreeEntry):
        return build_tree(entries, root_title="Manuscript", is_leaf_type=lambda t: t == "manuscript:scene")

    def test_groups_by_parent_in_rank_order_ties_by_id_missing_last(self) -> None:
        built = self._build(
            TreeEntry("act", "manuscript:act", "Act", None, 1),
            TreeEntry("s2", "manuscript:scene", "S2", "act", 2),
            TreeEntry("s1b", "manuscript:scene", "S1b", "act", 1),
            TreeEntry("s1a", "manuscript:scene", "S1a", "act", 1),
            TreeEntry("s0", "manuscript:scene", "S0", "act", None),
        )
        act = built.document.root.children[0]
        self.assertEqual([child.id for child in act.children], ["s1a", "s1b", "s2", "s0"])
        self.assertEqual(act.children[0].scene_id, "s1a")
        self.assertEqual(built.problems, [])

    def test_an_unhonourable_parent_sits_at_the_top_with_a_problem(self) -> None:
        built = self._build(
            TreeEntry("scene", "manuscript:scene", "Scene", None, 1),
            TreeEntry("dangling", "manuscript:scene", "Dangling", "manuscript_gone", 1),
            TreeEntry("under_leaf", "manuscript:scene", "Under leaf", "scene", 1),
        )
        top = {child.id for child in built.document.root.children}
        self.assertEqual(top, {"scene", "dangling", "under_leaf"})
        self.assertEqual({problem.node_id for problem in built.problems}, {"dangling", "under_leaf"})
        self.assertIsNone(built.honoured_parent["dangling"])

    def test_every_node_on_a_cycle_goes_to_the_top_keeping_children(self) -> None:
        built = self._build(
            TreeEntry("a", "manuscript:act", "A", "b", 1),
            TreeEntry("b", "manuscript:act", "B", "a", 1),
            TreeEntry("s", "manuscript:scene", "S", "a", 1),
        )
        top = {child.id: child for child in built.document.root.children}
        self.assertEqual(set(top), {"a", "b"})
        self.assertEqual([child.id for child in top["a"].children], ["s"])
        self.assertEqual({problem.node_id for problem in built.problems}, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
