"""The search excerpt is a window around the match, not the whole line
(#1868). A hit is emitted per occurrence (ADR-0085 §2), so a long paragraph
with fifty matches used to ship fifty copies of itself — 24k hits and 14 MB
for a one-letter query on a real project, and a frozen tab. These tests pin
the helper's edges and the invariant that matters at the service level: the
excerpt payload stays linear in the number of hits, and every excerpt still
contains its own match.
"""

from __future__ import annotations

from test_search_corpus import SearchCorpusTestCase

from app.models import SearchRequest
from app.services.project.search import (
    ELLIPSIS,
    EXCERPT_AFTER,
    EXCERPT_BEFORE,
    EXCERPT_MAX_LINE,
    excerpt_window,
)

WORD = "lorem "
# A paragraph well past `EXCERPT_MAX_LINE` with the match in the middle. The
# left context has a 23-char period so the raw cut `EXCERPT_BEFORE` back from
# the match lands INSIDE a word ("beta") — a test on "lorem " × n would pass
# with no word snapping at all, since 60 is a multiple of 6.
LEFT = "alpha beta gamma delta " * 12
LONG_LINE = LEFT + "Aetheria" + " ipsum" * 40


class ExcerptWindowTests(SearchCorpusTestCase):
    def test_a_short_line_is_sent_whole_as_before(self) -> None:
        line = "  The Aetheria gate  "
        start = line.index("Aetheria")

        self.assertEqual(excerpt_window(line, start, start + len("Aetheria")), "The Aetheria gate")

    def test_a_line_at_the_limit_is_still_whole(self) -> None:
        line = "x" * EXCERPT_MAX_LINE

        self.assertEqual(excerpt_window(line, 10, 12), line)

    def test_a_long_line_is_clipped_to_a_window_on_word_boundaries(self) -> None:
        start = LONG_LINE.index("Aetheria")
        end = start + len("Aetheria")

        excerpt = excerpt_window(LONG_LINE, start, end)

        self.assertIn("Aetheria", excerpt)
        self.assertTrue(excerpt.startswith(ELLIPSIS), excerpt)
        self.assertTrue(excerpt.endswith(ELLIPSIS), excerpt)
        inner = excerpt.strip(ELLIPSIS)
        # Snapped to whole words: the raw left cut fell inside "beta", the raw
        # right cut inside an "ipsum"; neither fragment may leak.
        self.assertTrue(LONG_LINE[start - EXCERPT_BEFORE - 1 : start - EXCERPT_BEFORE + 1].strip().isalpha())
        self.assertTrue(inner.startswith("gamma delta "), inner)
        self.assertTrue(inner.endswith(" ipsum"), inner)
        self.assertNotIn("ipsu ", inner + " ")
        self.assertLessEqual(len(excerpt), EXCERPT_BEFORE + EXCERPT_AFTER + len("Aetheria") + 2)

    def test_a_match_at_the_start_has_no_leading_ellipsis(self) -> None:
        line = "Aetheria" + " ipsum" * 60

        excerpt = excerpt_window(line, 0, len("Aetheria"))

        self.assertTrue(excerpt.startswith("Aetheria"), excerpt)
        self.assertTrue(excerpt.endswith(ELLIPSIS), excerpt)

    def test_a_match_at_the_end_has_no_trailing_ellipsis(self) -> None:
        line = WORD * 60 + "Aetheria"

        excerpt = excerpt_window(line, len(line) - len("Aetheria"), len(line))

        self.assertTrue(excerpt.startswith(ELLIPSIS), excerpt)
        self.assertTrue(excerpt.endswith("Aetheria"), excerpt)

    def test_a_match_longer_than_the_window_is_never_clipped(self) -> None:
        match = "Z" * (EXCERPT_BEFORE + EXCERPT_AFTER + 50)
        line = WORD * 30 + match + " ipsum" * 30
        start = line.index(match)

        excerpt = excerpt_window(line, start, start + len(match))

        self.assertIn(match, excerpt)

    def test_a_clipped_edge_without_a_space_keeps_the_raw_cut(self) -> None:
        # One unbroken token on each side: nothing to snap to, so the window
        # falls back to the character cut rather than swallowing the token.
        line = "a" * 500 + "Aetheria" + "b" * 500
        start = line.index("Aetheria")

        excerpt = excerpt_window(line, start, start + len("Aetheria"))

        self.assertEqual(excerpt, ELLIPSIS + "a" * EXCERPT_BEFORE + "Aetheria" + "b" * EXCERPT_AFTER + ELLIPSIS)


class ExcerptPayloadTests(SearchCorpusTestCase):
    def test_body_excerpts_stay_linear_in_hits_and_each_holds_its_match(self) -> None:
        # Forty occurrences in one 2,000-character paragraph: before #1868
        # this shipped forty copies of the paragraph (80 KB for one line).
        paragraph = ("The Aetheria gate stood open, " + "and the wind came through it, " * 1) * 40
        self._new_scene("Scene", paragraph)

        hits = [h for h in self._search("aetheria") if h.field == "body"]

        self.assertEqual(len(hits), 40, len(hits))
        window = EXCERPT_BEFORE + EXCERPT_AFTER + len("Aetheria") + 2
        for hit in hits:
            self.assertLessEqual(len(hit.excerpt), window, hit.excerpt)
            self.assertIn(hit.text, hit.excerpt)
            self.assertEqual(paragraph[hit.start : hit.end], hit.text)
        self.assertLess(sum(len(h.excerpt) for h in hits), len(paragraph) * 40 // 4)

    def test_an_excerpt_never_crosses_a_line_break(self) -> None:
        body = "first line only\n" + LONG_LINE + "\nthird line only"
        self._new_scene("Scene", body)

        hit = next(h for h in self._search("aetheria") if h.field == "body")

        self.assertEqual(hit.line, 2)
        self.assertNotIn("first", hit.excerpt)
        self.assertNotIn("third", hit.excerpt)
        self.assertIn("Aetheria", hit.excerpt)

    def test_a_metadata_excerpt_keeps_its_label_and_windows_the_value(self) -> None:
        # `title` is a metadata value in the corpus without needing a schema
        # field; any long value takes the same path.
        entry_id = self._new_lore(LONG_LINE, "body without the word")

        hits = [
            h
            for h in self.service.search(SearchRequest(query="aetheria")).hits
            if h.field == "metadata" and h.file_id == entry_id
        ]

        self.assertEqual(len(hits), 1, hits)
        excerpt = hits[0].excerpt
        self.assertTrue(excerpt.startswith(f"title: {ELLIPSIS}"), excerpt)
        self.assertIn("Aetheria", excerpt)
        self.assertLess(len(excerpt), len(LONG_LINE) // 2)
