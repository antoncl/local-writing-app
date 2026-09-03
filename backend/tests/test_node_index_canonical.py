"""`NodeIndex.canonical_id` / `redirects_to` (ADR-0082 §5).

Pure `NodeIndex`/`NodeIndexEntry` unit tests — no project, no disk — pinning
the chain-follow, the cycle guard, and the dangling-survivor rule directly
against `resolve()`, the one place they are derived.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from app.services.project.node_index import NodeIndex, NodeIndexEntry


def _tag(node_id: str, *, merged_into: str | None = None) -> NodeIndexEntry:
    return NodeIndexEntry(
        id=node_id,
        kind="tag",
        entry_type="tag:tag",
        path=Path(f"/tags/{node_id}.md"),
        title=node_id,
        source_layer_id="root",
        source_layer_label="root",
        merged_into=merged_into,
    )


class CanonicalIdTests(unittest.TestCase):
    def test_unmerged_id_is_its_own_canonical(self) -> None:
        index = NodeIndex()
        index.add(_tag("mirrors"))
        index.resolve()
        self.assertEqual(index.canonical_id("mirrors"), "mirrors")
        self.assertEqual(index.canonical_id("unknown_id"), "unknown_id")

    def test_single_hop_resolves_to_the_survivor(self) -> None:
        index = NodeIndex()
        index.add(_tag("mirror", merged_into="mirrors"))
        index.add(_tag("mirrors"))
        index.resolve()
        self.assertEqual(index.canonical_id("mirror"), "mirrors")
        self.assertEqual(index.redirects_to.get("mirrors"), ["mirror"])

    def test_chain_resolves_to_the_end(self) -> None:
        # a -> b -> c: canonical_id(a) follows every hop, not just the first.
        index = NodeIndex()
        index.add(_tag("a", merged_into="b"))
        index.add(_tag("b", merged_into="c"))
        index.add(_tag("c"))
        index.resolve()
        self.assertEqual(index.canonical_id("a"), "c")
        self.assertEqual(index.canonical_id("b"), "c")
        self.assertEqual(index.canonical_id("c"), "c")

    def test_cycle_stops_at_the_first_repeat_and_does_not_hang(self) -> None:
        # a -> b -> a: a malformed loop degrades to "resolves to itself"
        # rather than looping forever.
        index = NodeIndex()
        index.add(_tag("a", merged_into="b"))
        index.add(_tag("b", merged_into="a"))
        index.resolve()
        self.assertIn(index.canonical_id("a"), ("a", "b"))
        self.assertIn(index.canonical_id("b"), ("a", "b"))

    def test_dangling_survivor_stops_at_the_last_existing_id(self) -> None:
        # mirror -> ghost, and ghost is not in the index at all.
        index = NodeIndex()
        index.add(_tag("mirror", merged_into="ghost"))
        index.resolve()
        self.assertEqual(index.canonical_id("mirror"), "mirror")

    def test_dangling_survivor_two_hops_in_stops_at_the_last_existing_id(self) -> None:
        # a -> b -> ghost: b exists, ghost does not, so a resolves to b.
        index = NodeIndex()
        index.add(_tag("a", merged_into="b"))
        index.add(_tag("b", merged_into="ghost"))
        index.resolve()
        self.assertEqual(index.canonical_id("a"), "b")
        self.assertEqual(index.canonical_id("b"), "b")

    def test_by_id_keeps_the_redirect_entry_itself(self) -> None:
        """`by_id` maps a merged id to ITS OWN entry — listers (the governance
        pane) must still see the redirect record; only `canonical_id` follows
        it. Redirect-following is the explicit accessor, never a `by_id`
        rewrite."""
        index = NodeIndex()
        index.add(_tag("mirror", merged_into="mirrors"))
        index.add(_tag("mirrors"))
        index.resolve()
        self.assertEqual(index.by_id["mirror"].id, "mirror")
        self.assertIsNotNone(index.by_id["mirror"].merged_into)

    def test_non_tag_kind_never_redirects(self) -> None:
        """A `merged_into` value is only ever read for kind `tag` — an
        unrelated entry sharing the field id (impossible in practice, since
        the field only lives on `tag:base`) must not be followed."""
        index = NodeIndex()
        lore_entry = NodeIndexEntry(
            id="lore_a",
            kind="lore",
            entry_type="lore:note",
            path=Path("/lore/a.md"),
            title="a",
            source_layer_id="root",
            source_layer_label="root",
            merged_into="lore_b",
        )
        index.add(lore_entry)
        index.add(
            NodeIndexEntry(
                id="lore_b",
                kind="lore",
                entry_type="lore:note",
                path=Path("/lore/b.md"),
                title="b",
                source_layer_id="root",
                source_layer_label="root",
            )
        )
        index.resolve()
        self.assertEqual(index.canonical_id("lore_a"), "lore_a")
        self.assertEqual(index.redirects_to, {})


if __name__ == "__main__":
    unittest.main()
