from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.ai import providers as ai_providers
from app.services.ai.profiles.anthropic import AnthropicProfile
from app.services.ai.profiles.base import (
    ChatCall,
    StreamDelta,
    StreamFinal,
    StreamThinking,
    ThinkTagSplitter,
)
from app.services.ai.profiles.openai import OpenAIProfile
from app.services.ai.profiles.openrouter import OpenRouterProfile


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
        s = ThinkTagSplitter()
        out = self._drain(s.feed("Hello, world!"))
        self._drain(s.flush(), out)
        self.assertEqual(out, [("d", "Hello, world!")])

    def test_single_think_block_inline(self) -> None:
        s = ThinkTagSplitter()
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
        s = ThinkTagSplitter()
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
        s = ThinkTagSplitter()
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
        s = ThinkTagSplitter()
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
        s = ThinkTagSplitter()
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


def _chunk(*, content=None, reasoning=None, finish=None, usage=None):
    """Build one fake OpenAI-SDK stream chunk. A usage-only chunk has no
    choices (the final chunk carrying token counts)."""
    delta = SimpleNamespace(content=content, reasoning=reasoning, reasoning_content=None)
    choice = SimpleNamespace(delta=delta, finish_reason=finish)
    empty = content is None and reasoning is None and finish is None and usage is not None
    return SimpleNamespace(choices=([] if empty else [choice]), usage=usage)


class OpenAICompatibleStreamTests(unittest.TestCase):
    """Exercise the real chat_stream skeleton by faking the openai SDK, so the
    delta handling, timeout, and OpenRouter override are covered (the endpoint
    tests mock chat_stream away)."""

    def _run(self, profile, chunks):
        captured: dict = {}

        class _FakeOpenAI:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=lambda **_kw: iter(chunks))
                )

        call = ChatCall(
            model="m",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
        )
        with patch("openai.OpenAI", _FakeOpenAI):
            events = list(profile.chat_stream(call))
        return events, captured

    def test_openai_stream_splits_reasoning_and_content_and_reports_usage(self):
        chunks = [
            _chunk(reasoning="thinking..."),
            _chunk(content="Hello"),
            _chunk(content=" world", finish="stop"),
            _chunk(
                usage=SimpleNamespace(
                    prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None
                )
            ),
        ]
        events, captured = self._run(OpenAIProfile(api_key="sk-openai"), chunks)
        thinking = [e.text for e in events if isinstance(e, StreamThinking)]
        deltas = [e.text for e in events if isinstance(e, StreamDelta)]
        finals = [e for e in events if isinstance(e, StreamFinal)]
        self.assertEqual(thinking, ["thinking..."])
        self.assertEqual("".join(deltas), "Hello world")
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0].stop_reason, "stop")
        self.assertIsNotNone(finals[0].usage)
        self.assertEqual(finals[0].usage.output_tokens, 5)
        self.assertEqual(captured["timeout"], 180.0)

    def test_openrouter_stream_is_plain_content_only_with_longer_timeout(self):
        # OpenRouter deliberately does NOT surface reasoning fields as thinking
        # (byte-identical to the pre-reshape openrouter stream) and uses 300s.
        chunks = [
            _chunk(reasoning="ignored", content="Hi"),
            _chunk(finish="stop"),
            _chunk(
                usage=SimpleNamespace(
                    prompt_tokens=3, completion_tokens=1, prompt_tokens_details=None
                )
            ),
        ]
        events, captured = self._run(OpenRouterProfile(api_key="sk-or"), chunks)
        thinking = [e for e in events if isinstance(e, StreamThinking)]
        deltas = [e.text for e in events if isinstance(e, StreamDelta)]
        self.assertEqual(thinking, [])
        self.assertEqual("".join(deltas), "Hi")
        self.assertEqual(captured["timeout"], 300.0)
        self.assertEqual(captured["base_url"], "https://openrouter.ai/api/v1")


def _a_delta_event(dtype, *, text=None, thinking=None):
    """One Anthropic content_block_delta stream event."""
    delta = SimpleNamespace(type=dtype, text=text, thinking=thinking)
    return SimpleNamespace(type="content_block_delta", delta=delta)


def _a_usage(*, input_tokens=12, cache_read=0, cache_write=0, output_tokens=7):
    return SimpleNamespace(
        input_tokens=input_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
        output_tokens=output_tokens,
    )


class AnthropicStreamTests(unittest.TestCase):
    """Exercise the real AnthropicProfile.chat_stream by faking the anthropic
    SDK, so the delta routing (_stream_text_events), the thinking budget
    (_apply_thinking), and the terminal usage/stop-reason are covered — the
    endpoint/cost tests mock chat_stream away entirely."""

    def _run(self, call, events, *, stop_reason="end_turn", usage=None):
        captured: dict = {}
        final_msg = SimpleNamespace(stop_reason=stop_reason, usage=usage)

        class _FakeStream:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def __iter__(self):
                return iter(events)

            def get_final_message(self):
                return final_msg

        class _FakeAnthropic:
            def __init__(self, **kwargs):
                captured["client"] = kwargs

                def _stream(**kw):
                    captured["create"] = kw
                    return _FakeStream()

                self.messages = SimpleNamespace(stream=_stream)

        with patch("anthropic.Anthropic", _FakeAnthropic):
            out = list(AnthropicProfile(api_key="sk-ant").chat_stream(call))
        return out, captured

    def test_routes_text_and_thinking_deltas_and_ignores_other_events(self):
        events = [
            SimpleNamespace(type="message_start", delta=None),  # ignored
            _a_delta_event("thinking_delta", thinking="pondering"),
            _a_delta_event("text_delta", text="Hello"),
            _a_delta_event("text_delta", text=""),  # empty → dropped
            _a_delta_event("text_delta", text=" world"),
        ]
        call = ChatCall(
            model="claude-sonnet-4-6",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
        )
        out, captured = self._run(
            call, events, stop_reason="end_turn", usage=_a_usage(output_tokens=9)
        )
        thinking = [e.text for e in out if isinstance(e, StreamThinking)]
        deltas = [e.text for e in out if isinstance(e, StreamDelta)]
        finals = [e for e in out if isinstance(e, StreamFinal)]
        self.assertEqual(thinking, ["pondering"])
        self.assertEqual("".join(deltas), "Hello world")
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0].stop_reason, "end_turn")
        self.assertEqual(finals[0].usage.output_tokens, 9)
        # No thinking requested → no thinking kwarg on the wire.
        self.assertNotIn("thinking", captured["create"])

    def test_thinking_enabled_sets_budget_and_temperature(self):
        call = ChatCall(
            model="claude-sonnet-4-6",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=2048,
            thinking_enabled=True,
        )
        _out, captured = self._run(call, [], usage=_a_usage())
        create = captured["create"]
        self.assertEqual(
            create["thinking"], {"type": "enabled", "budget_tokens": 1024}
        )
        # Anthropic requires temperature=1 when thinking is on (temp-ok model).
        self.assertEqual(create["temperature"], 1.0)


if __name__ == "__main__":
    unittest.main()
