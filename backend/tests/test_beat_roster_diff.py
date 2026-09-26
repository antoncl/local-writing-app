"""`diff_beat_list` (#2260): the pure structural diff behind the
`plot_beats_saved` trace record. End-to-end coverage through a real save is
in `test_plot_beats.py`; this is the diff logic in isolation."""

from __future__ import annotations

import unittest

from app.services.project.beat_roster_diff import diff_beat_list


class DiffBeatListTests(unittest.TestCase):
    def test_no_change_is_none(self) -> None:
        beats = [{"id": "b1", "title": "Setup"}]
        self.assertIsNone(diff_beat_list(beats, beats))

    def test_added_beat(self) -> None:
        before = [{"id": "b1", "title": "Setup"}]
        after = [{"id": "b1", "title": "Setup"}, {"id": "b2", "title": "Twist"}]
        diff = diff_beat_list(before, after)
        self.assertEqual(diff["added"], [{"id": "b2", "title": "Twist"}])
        self.assertEqual(diff["removed"], [])
        self.assertFalse(diff["reordered"])

    def test_removed_beat(self) -> None:
        before = [{"id": "b1", "title": "Setup"}, {"id": "b2", "title": "Twist"}]
        after = [{"id": "b1", "title": "Setup"}]
        diff = diff_beat_list(before, after)
        self.assertEqual(diff["removed"], [{"id": "b2", "title": "Twist"}])
        self.assertEqual(diff["added"], [])

    def test_reorder_of_survivors_is_flagged(self) -> None:
        before = [{"id": "b1", "title": "First"}, {"id": "b2", "title": "Second"}]
        after = [{"id": "b2", "title": "Second"}, {"id": "b1", "title": "First"}]
        diff = diff_beat_list(before, after)
        self.assertTrue(diff["reordered"])
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])

    def test_changed_member_keys_only_names_keys_not_values(self) -> None:
        before = [{"id": "b1", "title": "Setup", "specifics": "old"}]
        after = [{"id": "b1", "title": "Setup", "specifics": "new"}]
        diff = diff_beat_list(before, after)
        self.assertEqual(diff["changed"], {"b1": ["specifics"]})
        self.assertNotIn("old", str(diff))
        self.assertNotIn("new", str(diff))

    def test_minted_ids_are_reported_when_present_in_after(self) -> None:
        before: list = []
        after = [{"id": "beat_abc", "title": "Fresh"}]
        diff = diff_beat_list(before, after, minted={"beat_abc"})
        self.assertEqual(diff["minted"], ["beat_abc"])
        self.assertEqual(diff["added"], [{"id": "beat_abc", "title": "Fresh"}])

    def test_minted_set_from_a_sibling_field_does_not_bleed_in(self) -> None:
        before = [{"id": "b1", "title": "Setup"}]
        after = [{"id": "b1", "title": "Setup"}]
        diff = diff_beat_list(before, after, minted={"beat_unrelated"})
        self.assertIsNone(diff)

    def test_non_list_values_behave_as_empty(self) -> None:
        self.assertIsNone(diff_beat_list(None, None))
        diff = diff_beat_list(None, [{"id": "b1", "title": "Setup"}])
        self.assertEqual(diff["added"], [{"id": "b1", "title": "Setup"}])


if __name__ == "__main__":
    unittest.main()
