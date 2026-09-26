"""Beat identity is machine-owned, never model-authored (#2243).

Unit coverage for the pure repair `reconcile_list_identity` — the extraction-
level wiring (a proposed `instance_beats` roster reconciled against the
stored one) is covered in test_ai_extraction.py."""

from __future__ import annotations

import unittest

from app.services.ai.list_identity import reconcile_list_identity


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


if __name__ == "__main__":
    unittest.main()
