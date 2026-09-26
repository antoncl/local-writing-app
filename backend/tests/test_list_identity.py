"""Beat identity is machine-owned, never model-authored (#2243).

Unit coverage for the pure repair `reconcile_list_identity` — the extraction-
level wiring (a proposed `instance_beats` roster reconciled against the
stored one) is covered in test_ai_extraction.py."""

from __future__ import annotations

import unittest

from app.services.ai.list_identity import (
    reconcile_list_identity,
    reconcile_list_identity_report,
)


class ReconcileListIdentityTests(unittest.TestCase):
    def test_a_matching_id_is_kept(self) -> None:
        stored = [{"id": "beat_1", "title": "Setup", "guidance": "old"}]
        proposed = [{"id": "beat_1", "title": "Setup, revised"}]
        result = reconcile_list_identity(proposed, stored)
        self.assertEqual(result[0]["id"], "beat_1")

    def test_an_invented_id_is_replaced_via_title_match(self) -> None:
        stored = [{"id": "beat_1", "title": "Setup pressure", "guidance": "old"}]
        proposed = [{"id": "setup_pressure", "title": "Setup pressure"}]
        result = reconcile_list_identity(proposed, stored)
        self.assertEqual(result[0]["id"], "beat_1")

    def test_title_match_is_whitespace_and_case_insensitive(self) -> None:
        stored = [{"id": "beat_1", "title": "Setup Pressure"}]
        proposed = [{"id": "made_up", "title": "  setup pressure  "}]
        result = reconcile_list_identity(proposed, stored)
        self.assertEqual(result[0]["id"], "beat_1")

    def test_an_unmatched_id_is_stripped(self) -> None:
        stored = [{"id": "beat_1", "title": "Setup"}]
        proposed = [{"id": "invented", "title": "Something else entirely"}]
        result = reconcile_list_identity(proposed, stored)
        self.assertNotIn("id", result[0])

    def test_omitted_member_is_preserved_on_a_match(self) -> None:
        stored = [{"id": "beat_1", "title": "Setup", "specifics": "The old specifics."}]
        proposed = [{"id": "beat_1", "title": "Setup"}]  # specifics omitted
        result = reconcile_list_identity(proposed, stored)
        self.assertEqual(result[0]["specifics"], "The old specifics.")

    def test_an_explicit_empty_value_wins_over_the_stored_one(self) -> None:
        stored = [{"id": "beat_1", "title": "Setup", "specifics": "The old specifics."}]
        proposed = [{"id": "beat_1", "title": "Setup", "specifics": ""}]
        result = reconcile_list_identity(proposed, stored)
        self.assertEqual(result[0]["specifics"], "")

    def test_two_proposed_beats_sharing_a_title_claim_only_one_existing_id(self) -> None:
        stored = [{"id": "beat_1", "title": "Setup"}]
        proposed = [
            {"id": "made_up_1", "title": "Setup"},
            {"id": "made_up_2", "title": "Setup"},
        ]
        result = reconcile_list_identity(proposed, stored)
        self.assertEqual(result[0]["id"], "beat_1")
        self.assertNotIn("id", result[1])

    def test_reorder_preserves_ids(self) -> None:
        stored = [
            {"id": "beat_1", "title": "First"},
            {"id": "beat_2", "title": "Second"},
        ]
        proposed = [
            {"id": "beat_2", "title": "Second"},
            {"id": "beat_1", "title": "First"},
        ]
        result = reconcile_list_identity(proposed, stored)
        self.assertEqual([item["id"] for item in result], ["beat_2", "beat_1"])

    def test_non_list_stored_value_only_strips_ids(self) -> None:
        proposed = [{"id": "invented", "title": "Setup"}]
        result = reconcile_list_identity(proposed, None)
        self.assertNotIn("id", result[0])

    def test_non_list_proposed_value_passes_through_unchanged(self) -> None:
        self.assertEqual(reconcile_list_identity("not-a-list", []), "not-a-list")

    def test_non_dict_items_pass_through_untouched(self) -> None:
        result = reconcile_list_identity(["not-a-dict"], [{"id": "beat_1", "title": "x"}])
        self.assertEqual(result, ["not-a-dict"])


class ReconcileListIdentityReportTests(unittest.TestCase):
    """The `report` half of `reconcile_list_identity_report` (#2260) — the
    extraction trace's per-item outcome + the stored beats a proposal would
    delete. `reconcile_list_identity` is just `[0]` of the same call
    (asserted at the bottom), so its own behaviour tests above cover the
    reconciled-list half for free."""

    def test_kept_outcome_when_the_proposed_id_matches(self) -> None:
        stored = [{"id": "beat_1", "title": "Setup"}]
        proposed = [{"id": "beat_1", "title": "Setup, revised"}]
        _, report = reconcile_list_identity_report(proposed, stored)
        self.assertEqual(report["items"][0]["outcome"], "kept")
        self.assertEqual(report["items"][0]["matched_id"], "beat_1")
        self.assertEqual(report["unclaimed_stored"], [])

    def test_matched_by_title_outcome_and_backfilled_keys(self) -> None:
        stored = [{"id": "beat_1", "title": "Setup pressure", "specifics": "old"}]
        proposed = [{"id": "setup_pressure", "title": "Setup pressure"}]
        _, report = reconcile_list_identity_report(proposed, stored)
        item = report["items"][0]
        self.assertEqual(item["outcome"], "matched_by_title")
        self.assertEqual(item["matched_id"], "beat_1")
        self.assertIn("specifics", item["backfilled"])

    def test_stripped_outcome_when_nothing_matches(self) -> None:
        stored = [{"id": "beat_1", "title": "Setup"}]
        proposed = [{"id": "invented", "title": "Something else"}]
        _, report = reconcile_list_identity_report(proposed, stored)
        item = report["items"][0]
        self.assertEqual(item["outcome"], "stripped")
        self.assertIsNone(item["matched_id"])

    def test_unclaimed_stored_lists_beats_no_proposed_item_claimed(self) -> None:
        stored = [{"id": "beat_1", "title": "Setup"}, {"id": "beat_2", "title": "Payoff"}]
        proposed = [{"id": "beat_1", "title": "Setup"}]
        _, report = reconcile_list_identity_report(proposed, stored)
        self.assertEqual(report["unclaimed_stored"], [{"id": "beat_2", "title": "Payoff"}])

    def test_non_list_proposed_is_skipped(self) -> None:
        _, report = reconcile_list_identity_report("not-a-list", [])
        self.assertEqual(report, {"skipped": "not a list"})

    def test_counts_reflect_both_sides(self) -> None:
        stored = [{"id": "beat_1", "title": "Setup"}]
        proposed = [{"id": "beat_1", "title": "Setup"}, {"title": "New beat"}]
        _, report = reconcile_list_identity_report(proposed, stored)
        self.assertEqual(report["proposed_count"], 2)
        self.assertEqual(report["stored_count"], 1)

    def test_reconcile_list_identity_is_just_the_reports_first_element(self) -> None:
        stored = [{"id": "beat_1", "title": "Setup"}]
        proposed = [{"id": "made_up", "title": "Setup"}]
        reconciled, report = reconcile_list_identity_report(proposed, stored)
        self.assertEqual(reconcile_list_identity(proposed, stored), reconciled)


if __name__ == "__main__":
    unittest.main()
