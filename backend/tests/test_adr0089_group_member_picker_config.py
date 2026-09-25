from __future__ import annotations

import unittest

from app.models import GroupMember, MetadataGroupDefinition


class Adr0089GroupMemberPickerConfigShapeTests(unittest.TestCase):
    """ADR-0089 §1's worked example writes a member as
    `picker_config: { kinds: [lore] }`. `NodePickerConfig` has no `kinds`
    field — `kinds` is a read-only property REDUCED from `sources`
    (`models_views.py`) — so a bare `kinds` key is silently ignored by
    Pydantic's default `extra="ignore"`, and the member's picker resolves to
    NO membership at all rather than lore. This is a doc bug, not a loader
    gap: #2215 item 6 corrects the ADR example to the real stored `sources`
    shape instead of adding a shim to accept the wrong one."""

    def test_adr_example_shape_does_not_resolve_lore_membership(self) -> None:
        group = MetadataGroupDefinition.model_validate(
            {
                "name": "Relationship",
                "members": [
                    {
                        "key": "to",
                        "name": "Who",
                        "type": "entity_ref",
                        "picker_config": {"kinds": ["lore"]},
                    },
                ],
            }
        )
        member = group.members[0]
        assert member.picker_config is not None
        # The bogus `kinds` key vanished on load — the config carries no
        # sources at all, so it picks nothing. Regression: if a future
        # loader shim starts honouring a bare `kinds` key, this must be
        # updated deliberately, not silently pass.
        self.assertEqual(member.picker_config.sources, [])
        self.assertEqual(member.picker_config.kinds, [])

    def test_stored_sources_shape_resolves_lore_membership(self) -> None:
        # The corrected ADR-0089 §1 example: `sources: [{ kind: lore }]` is
        # the real on-disk shape `NodePickerConfig` serializes (ADR-0023 /
        # #78) — this is what a hand-authored schema.yaml must write to get
        # a member whose picker actually offers Lore.
        member = GroupMember.model_validate(
            {
                "key": "to",
                "name": "Who",
                "type": "entity_ref",
                "picker_config": {"sources": [{"kind": "lore"}]},
            }
        )
        assert member.picker_config is not None
        self.assertEqual(member.picker_config.kinds, ["lore"])


if __name__ == "__main__":
    unittest.main()
