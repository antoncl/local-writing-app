"""AI roleplay/character helpers: the per-character thread reconstruction and its
interiority (ADR-0070). Split out of test_ai_helpers.py to keep both under the
file-size cap; these are the `character_turns`/`roleplay_beats` family, distinct
from the general prompt-context helpers that remain there.
"""

from __future__ import annotations

import unittest

from app.services.ai.helpers import (
    _role_block,
    _roleplay_beats,
    _scene_body_text,
    _split_body_by_character_markers,
    _thread_parts,
)


class _Obj:
    def __init__(self, **kw: object) -> None:
        self.__dict__.update(kw)


class SceneBodyTextTests(unittest.TestCase):
    def test_reads_body_attribute(self) -> None:
        self.assertEqual(_scene_body_text(_Obj(body="hello")), "hello")

    def test_reads_dict_body(self) -> None:
        self.assertEqual(_scene_body_text({"body": "hi"}), "hi")

    def test_none_scene_is_empty(self) -> None:
        self.assertEqual(_scene_body_text(None), "")

    def test_object_without_str_body_is_empty(self) -> None:
        self.assertEqual(_scene_body_text(_Obj(body=None)), "")
        self.assertEqual(_scene_body_text({"other": "x"}), "")


class ThreadPartsTests(unittest.TestCase):
    """The roleplay thread builder's core: the focus character's spans become
    `assistant`, other characters' `user` prefixed `[Name]: `, untagged
    narration plain `user`; consecutive same-role spans coalesce into one turn.
    """

    def test_routes_by_focus_and_coalesces_same_role(self) -> None:
        segments = [
            (None, "Narr. ", ""),
            ("c1", "Hi ", ""),
            ("c1", "there ", ""),
            ("c2", "Yo", ""),
            (None, " end", ""),
        ]
        parts = _thread_parts(segments, focus_id="c1", titles={"c2": "Bob"})
        self.assertEqual(
            parts,
            [
                _role_block("user", "Narr."),
                _role_block("assistant", "Hi there"),
                _role_block("user", "[Bob]: Yo end"),
            ],
        )

    def test_other_character_falls_back_to_id_without_title(self) -> None:
        parts = _thread_parts([("c9", "hey", "")], focus_id="c1", titles={})
        self.assertEqual(parts, [_role_block("user", "[c9]: hey")])

    def test_whitespace_only_turn_is_dropped(self) -> None:
        self.assertEqual(_thread_parts([(None, "   ", "")], focus_id="c1", titles={}), [])


class InteriorityPrivacyTests(unittest.TestCase):
    """ADR-0070: a beat's interiority is per-character private. The focus
    character's own interiority is folded back into their `assistant` turns;
    every other character's is stripped from their `[Name]: ` turns.
    """

    def test_focus_character_keeps_own_interiority(self) -> None:
        segments = [("c1", "She fired.", "I can't miss now.")]
        parts = _thread_parts(segments, focus_id="c1", titles={})
        self.assertEqual(
            parts,
            [_role_block("assistant", "She fired.\n\n[[interiority]]\n\nI can't miss now.")],
        )

    def test_other_character_interiority_is_stripped(self) -> None:
        # Bill's private thought must never reach Annie's (c1's) reconstruction.
        segments = [("c2", "He tips his hat.", "She'll never outdraw me.")]
        parts = _thread_parts(segments, focus_id="c1", titles={"c2": "Bill"})
        self.assertEqual(parts, [_role_block("user", "[Bill]: He tips his hat.")])
        self.assertNotIn("outdraw", parts[0])

    def test_no_interiority_leaves_focus_prose_unchanged(self) -> None:
        parts = _thread_parts([("c1", "She fired.", "")], focus_id="c1", titles={})
        self.assertEqual(parts, [_role_block("assistant", "She fired.")])

    def test_consecutive_focus_beats_keep_interiority_separated(self) -> None:
        # Two beats in a row for the same character (a normal roleplay flow):
        # the first beat's interiority must not run into the second's prose.
        segments = [("c1", "She aims.", "Steady."), ("c1", "She fires.", "Now.")]
        parts = _thread_parts(segments, focus_id="c1", titles={})
        self.assertEqual(
            parts,
            [
                _role_block(
                    "assistant",
                    "She aims.\n\n[[interiority]]\n\nSteady.\n\nShe fires.\n\n[[interiority]]\n\nNow.",
                ),
            ],
        )

    def test_split_body_captures_and_decodes_interiority(self) -> None:
        body = (
            "Narration. "
            "<!-- character:id=c1;internal=I%20can%27t%20miss. -->She fired.<!-- /character -->"
            "<!-- character:id=c2 -->He grins.<!-- /character -->"
        )
        self.assertEqual(
            _split_body_by_character_markers(body),
            [
                (None, "Narration. ", ""),
                ("c1", "She fired.", "I can't miss."),
                ("c2", "He grins.", ""),
            ],
        )


class RoleplayBeatsTests(unittest.TestCase):
    """ADR-0070 S3: `roleplay_beats` lays a scene out for a finalize prompt —
    each beat's speaker, observable text, and decoded private interiority."""

    class _NoLore:
        """A project whose lore reads all miss, so names fall back to ids."""

        def read_node(self, node_id: str) -> None:
            raise KeyError(node_id)

    def test_lays_out_beats_with_decoded_interiority(self) -> None:
        body = (
            "Narration here. "
            "<!-- character:id=annie;internal=Steady%20now. -->She fired.<!-- /character -->"
            "<!-- character:id=bill -->He grins.<!-- /character -->"
        )
        out = _roleplay_beats(self._NoLore(), {"body": body})
        self.assertIn("[Narration] Narration here.", out)
        self.assertIn("[annie] She fired.", out)
        self.assertIn("[annie — interiority] Steady now.", out)  # %20 decoded
        self.assertIn("[bill] He grins.", out)
        # Bill has no interiority marker, so no interiority line for him.
        self.assertNotIn("[bill — interiority]", out)

    def test_scene_without_beats_returns_body_unchanged(self) -> None:
        self.assertEqual(
            _roleplay_beats(self._NoLore(), {"body": "Just plain narration."}),
            "Just plain narration.",
        )


if __name__ == "__main__":
    unittest.main()
