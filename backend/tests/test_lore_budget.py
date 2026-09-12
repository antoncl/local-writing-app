"""ADR-0086 §1/§3: the pure budget fit. `fit_lore_budget` takes the selector's
two sets and a `{id: xml}` map and decides, without a project, which whole
entries a turn sends — so the rule is tested as a function: fit order, first-fit
over an oversized entry, the declared set never walked or counted, `0` = declared
only, and the report the send hands back.
"""

from __future__ import annotations

import unittest

from app.services.ai.lore_budget import (
    DEFAULT_LORE_BUDGET_TOKENS,
    InferredCandidate,
    LoreLimits,
    LoreSelection,
    fit_lore_budget,
)


def _selection(
    declared: set[str] = frozenset(), inferred: list[InferredCandidate] | None = None
) -> LoreSelection:
    """A selection with `inferred` already in fit order (the selector's job)."""
    return LoreSelection(
        frozenset(declared), tuple(sorted(inferred or [], key=lambda c: c.fit_key))
    )


class FitKeyTests(unittest.TestCase):
    def test_fit_order_is_source_then_latest_turn_then_id(self) -> None:
        # ADR-0086 §1: distance from the author's own words first; within a
        # source the entry first noticed latest; then id. No title involved.
        candidates = [
            InferredCandidate("lore_b", "structural_hop"),
            InferredCandidate("lore_c", "depth1_expansion", added_at_turn=3),
            InferredCandidate("lore_d", "user_message", added_at_turn=1),
            InferredCandidate("lore_a", "user_message", added_at_turn=1),
            InferredCandidate("lore_e", "user_message", added_at_turn=4),
            InferredCandidate("lore_f", "scene_prose", added_at_turn=0),
            InferredCandidate("lore_g", "rendered_prompt", added_at_turn=0),
        ]
        ordered = [c.id for c in sorted(candidates, key=lambda c: c.fit_key)]
        self.assertEqual(
            ordered, ["lore_e", "lore_a", "lore_d", "lore_g", "lore_f", "lore_c", "lore_b"]
        )

    def test_ids_face_is_the_id_sorted_union(self) -> None:
        selection = _selection(
            {"lore_z", "lore_m"}, [InferredCandidate("lore_a", "user_message")]
        )
        self.assertEqual(selection.ids, ["lore_a", "lore_m", "lore_z"])

    def test_limits_default_to_the_resolvers_defaults(self) -> None:
        limits = LoreLimits()
        self.assertEqual(limits.budget_tokens, DEFAULT_LORE_BUDGET_TOKENS)
        self.assertEqual(limits.expansion, "one_hop")


class FitLoreBudgetTests(unittest.TestCase):
    # `count=len` makes each entry's size its XML length, so the arithmetic is
    # legible: "a" * 40 is a 40-token entry.

    def test_keeps_whole_entries_in_fit_order_until_the_budget_is_spent(self) -> None:
        selection = _selection(
            inferred=[
                InferredCandidate("lore_1", "user_message", added_at_turn=2, title="One"),
                InferredCandidate("lore_2", "user_message", added_at_turn=1, title="Two"),
                InferredCandidate("lore_3", "structural_hop", title="Three"),
            ]
        )
        rendered = {"lore_1": "a" * 40, "lore_2": "b" * 40, "lore_3": "c" * 40}
        fitted = fit_lore_budget(selection, rendered, 80, count=len)
        self.assertEqual(fitted.kept_ids, ["lore_1", "lore_2"])
        self.assertEqual([e.id for e in fitted.report.left_out], ["lore_3"])
        self.assertEqual(fitted.report.left_out[0].title, "Three")
        self.assertEqual(fitted.report.left_out[0].source, "structural_hop")
        self.assertEqual(fitted.report.left_out[0].tokens, 40)
        self.assertEqual(fitted.report.used_tokens, 80)
        self.assertEqual(fitted.report.budget_tokens, 80)
        self.assertEqual(fitted.report.kept, 2)

    def test_an_exact_fit_is_kept(self) -> None:
        # `<=`, not `<`: an entry exactly the size of what remains fits.
        selection = _selection(inferred=[InferredCandidate("lore_1", "user_message")])
        fitted = fit_lore_budget(selection, {"lore_1": "a" * 16}, 16, count=len)
        self.assertEqual(fitted.kept_ids, ["lore_1"])
        self.assertEqual(fitted.report.left_out, [])

    def test_first_fit_skips_an_oversized_entry_and_keeps_a_smaller_lower_one(self) -> None:
        # ADR-0086 §3: an oversized entry does not block the smaller ones ordered
        # below it — cut-at-first-overflow was rejected for exactly this.
        selection = _selection(
            inferred=[
                InferredCandidate("lore_big", "user_message", added_at_turn=2),
                InferredCandidate("lore_small", "depth1_expansion", added_at_turn=1),
            ]
        )
        rendered = {"lore_big": "a" * 500, "lore_small": "b" * 30}
        fitted = fit_lore_budget(selection, rendered, 100, count=len)
        self.assertEqual(fitted.kept_ids, ["lore_small"])
        self.assertEqual([e.id for e in fitted.report.left_out], ["lore_big"])
        self.assertEqual(fitted.report.left_out[0].tokens, 500)
        self.assertEqual(fitted.report.used_tokens, 30)

    def test_declared_entries_are_never_walked_nor_counted(self) -> None:
        # A declared set of 300 and a budget of 100 is legal and sends both the
        # declared entries and up to 100 of inferred (§3).
        selection = _selection(
            {"lore_pick", "lore_always"},
            [InferredCandidate("lore_seen", "user_message")],
        )
        rendered = {"lore_pick": "p" * 200, "lore_always": "q" * 100, "lore_seen": "s" * 90}
        fitted = fit_lore_budget(selection, rendered, 100, count=len)
        self.assertEqual(fitted.kept_ids, ["lore_always", "lore_pick", "lore_seen"])
        self.assertEqual(fitted.report.declared_tokens, 300)
        self.assertEqual(fitted.report.used_tokens, 90)
        self.assertEqual(fitted.report.left_out, [])

    def test_declared_over_budget_leaves_the_inferred_fit_unchanged_and_is_reported(self) -> None:
        # The report says the declared set alone exceeds the budget; the fit on
        # the inferred set runs exactly as it otherwise would.
        selection = _selection(
            {"lore_pick"},
            [
                InferredCandidate("lore_a", "user_message", added_at_turn=1),
                InferredCandidate("lore_b", "scene_prose", added_at_turn=1),
            ],
        )
        rendered = {"lore_pick": "p" * 1000, "lore_a": "a" * 60, "lore_b": "b" * 60}
        fitted = fit_lore_budget(selection, rendered, 100, count=len)
        self.assertGreater(fitted.report.declared_tokens, fitted.report.budget_tokens)
        self.assertEqual(fitted.kept_ids, ["lore_a", "lore_pick"])
        self.assertEqual([e.id for e in fitted.report.left_out], ["lore_b"])

    def test_zero_budget_sends_only_declared_entries(self) -> None:
        selection = _selection(
            {"lore_pick"}, [InferredCandidate("lore_seen", "user_message", title="Seen")]
        )
        rendered = {"lore_pick": "p" * 10, "lore_seen": "s" * 10}
        fitted = fit_lore_budget(selection, rendered, 0, count=len)
        self.assertEqual(fitted.kept_ids, ["lore_pick"])
        self.assertEqual([e.id for e in fitted.report.left_out], ["lore_seen"])
        self.assertEqual(fitted.report.used_tokens, 0)
        self.assertEqual(fitted.report.budget_tokens, 0)

    def test_an_unrenderable_candidate_is_skipped_on_both_sides(self) -> None:
        # An id `_render_lore_entries` could not read is not sendable: it is
        # neither kept nor reported as left out, and a declared one adds nothing.
        selection = _selection(
            {"lore_gone_pick"}, [InferredCandidate("lore_gone", "user_message")]
        )
        fitted = fit_lore_budget(selection, {}, 100, count=len)
        self.assertEqual(fitted.kept_ids, [])
        self.assertEqual(fitted.report.left_out, [])
        self.assertEqual(fitted.report.declared_tokens, 0)
        self.assertEqual(fitted.report.kept, 0)

    def test_title_of_fills_only_an_unnamed_left_out_entry(self) -> None:
        # A journal candidate carries its title snapshot; a structural-hop id
        # does not, and only THAT one asks the caller — never a kept entry.
        asked: list[str] = []

        def title_of(entry_id: str) -> str:
            asked.append(entry_id)
            return f"Title of {entry_id}"

        selection = _selection(
            inferred=[
                InferredCandidate("lore_kept", "user_message", added_at_turn=1),
                InferredCandidate("lore_named", "depth1_expansion", title="Named"),
                InferredCandidate("lore_hop", "structural_hop"),
            ]
        )
        rendered = {"lore_kept": "k" * 10, "lore_named": "n" * 50, "lore_hop": "h" * 50}
        fitted = fit_lore_budget(selection, rendered, 20, count=len, title_of=title_of)
        self.assertEqual(fitted.kept_ids, ["lore_kept"])
        self.assertEqual(
            [(e.id, e.title) for e in fitted.report.left_out],
            [("lore_named", "Named"), ("lore_hop", "Title of lore_hop")],
        )
        self.assertEqual(asked, ["lore_hop"])

    def test_kept_ids_are_id_sorted_for_the_wire(self) -> None:
        # The fit order is for the fit only; the wire stays id-sorted (anti-goal:
        # no tiering / wire-order change).
        selection = _selection(
            {"lore_z"},
            [
                InferredCandidate("lore_y", "user_message", added_at_turn=3),
                InferredCandidate("lore_a", "user_message", added_at_turn=1),
            ],
        )
        rendered = {"lore_z": "z", "lore_y": "y", "lore_a": "a"}
        fitted = fit_lore_budget(selection, rendered, 10, count=len)
        self.assertEqual(fitted.kept_ids, ["lore_a", "lore_y", "lore_z"])


if __name__ == "__main__":
    unittest.main()
