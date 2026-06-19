from __future__ import annotations

import unittest

from app.services.ai import providers as ai_providers


class ThinkTagSplitterTests(unittest.TestCase):
    def _drain(self, events, dest=None):
        """Append events to dest, merging adjacent same-type entries.

        The splitter holds back trailing chars across chunks in case they're
        a partial tag, so a single logical span can arrive as several events.
        Consumers concatenate by type anyway — we model that here.
        """
        out = dest if dest is not None else []
        for ev in events:
            kind = "d" if isinstance(ev, ai_providers.StreamDelta) else (
                "t" if isinstance(ev, ai_providers.StreamThinking) else None
            )
            if kind is None:
                continue
            if out and out[-1][0] == kind:
                out[-1] = (kind, out[-1][1] + ev.text)
            else:
                out.append((kind, ev.text))
        return out

    def test_no_tags_emits_text_only(self) -> None:
        s = ai_providers._ThinkTagSplitter()
        out = self._drain(s.feed("Hello, world!"))
        self._drain(s.flush(), out)
        self.assertEqual(out, [("d", "Hello, world!")])

    def test_single_think_block_inline(self) -> None:
        s = ai_providers._ThinkTagSplitter()
        text = "prefix <think>reasoning here</think> answer."
        out = self._drain(s.feed(text))
        self._drain(s.flush(), out)
        self.assertEqual(
            out,
            [
                ("d", "prefix "),
                ("t", "reasoning here"),
                ("d", " answer."),
            ],
        )

    def test_tag_split_across_chunks(self) -> None:
        s = ai_providers._ThinkTagSplitter()
        out: list = []
        self._drain(s.feed("hi <thi"), out)
        self._drain(s.feed("nk>secret</thi"), out)
        self._drain(s.feed("nk>bye"), out)
        self._drain(s.flush(), out)
        self.assertEqual(
            out,
            [
                ("d", "hi "),
                ("t", "secret"),
                ("d", "bye"),
            ],
        )

    def test_close_tag_not_received_emits_thinking_on_flush(self) -> None:
        s = ai_providers._ThinkTagSplitter()
        out = self._drain(s.feed("text <think>still reasoning"))
        self._drain(s.flush(), out)
        self.assertEqual(
            out,
            [
                ("d", "text "),
                ("t", "still reasoning"),
            ],
        )

    def test_multiple_blocks(self) -> None:
        s = ai_providers._ThinkTagSplitter()
        out = self._drain(s.feed("a<think>one</think>b<think>two</think>c"))
        self._drain(s.flush(), out)
        self.assertEqual(
            out,
            [
                ("d", "a"),
                ("t", "one"),
                ("d", "b"),
                ("t", "two"),
                ("d", "c"),
            ],
        )

    def test_holds_back_potential_partial_tag(self) -> None:
        # Feeding a string that ENDS with the beginning of a potential <think> tag
        # should hold those trailing chars rather than emitting them as content.
        s = ai_providers._ThinkTagSplitter()
        out = self._drain(s.feed("answer <thin"))
        # "<thin" (and the leading space, which could precede a tag) is held;
        # only the safe prefix has been emitted.
        self.assertEqual(out, [("d", "answer")])
        # When the rest of the tag arrives, the held-back space resolves as
        # text and "oops" is recognized as thinking content.
        self._drain(s.feed("k>oops"), out)
        self._drain(s.flush(), out)
        # Final shape: text "answer ", then thinking "oops".
        self.assertEqual(out, [("d", "answer "), ("t", "oops")])


if __name__ == "__main__":
    unittest.main()
