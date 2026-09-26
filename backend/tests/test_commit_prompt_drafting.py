"""Built-in commit prompts must make the model write its draft out (#2261).

A brainstorm commit extracts ONLY from the conversation. A model that says
"we'll refine the Midpoint beat — ready to commit" without writing the new
beat has given the extraction nothing new, so the commit returns the old
roster or invents one (seen with Gemma4 on a revise-plotline chat). These
checks pin the two sentences that close that gap: every commit prompt says a
described-but-unwritten change is lost, and the two roster prompts require
the full roster before "ready to commit".
"""

from __future__ import annotations

import unittest
from pathlib import Path

import app

PROMPTS = Path(app.__file__).parent / "builtin_library" / "prompts"

# Every built-in whose output commits through the extraction step.
COMMIT_PROMPTS = (
    "revise-plotline.md",
    "revise-character-arc.md",
    "revise-entry.md",
    "revise-plot-card.md",
    "follow-a-change.md",
)
ROSTER_PROMPTS = ("revise-plotline.md", "revise-character-arc.md")


class CommitPromptDraftingTests(unittest.TestCase):
    def test_every_commit_prompt_says_unwritten_changes_are_lost(self) -> None:
        for name in COMMIT_PROMPTS:
            body = (PROMPTS / name).read_text(encoding="utf-8")
            with self.subTest(prompt=name):
                self.assertIn("it can only use what is actually written here", body)

    def test_roster_prompts_require_the_whole_roster_before_ready(self) -> None:
        for name in ROSTER_PROMPTS:
            body = (PROMPTS / name).read_text(encoding="utf-8")
            with self.subTest(prompt=name):
                self.assertIn("the complete roster", body)
                self.assertIn("never before the whole roster is written out", body)
                self.assertIn("is removed from the roster", body)
                self.assertIn("ready to commit", body)


if __name__ == "__main__":
    unittest.main()
