from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.ai import providers as ai_providers
from app.services.ai.profiles.anthropic import AnthropicProfile
from app.services.ai.profiles.base import (
    ChatCall,
    ProviderError,
    StreamDelta,
    StreamFinal,
    StreamThinking,
    ThinkTagSplitter,
)
from app.services.ai.profiles.ollama import OllamaProfile
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


def _error_chunk(*, message, nested=True):
    """A fake OpenRouter in-band error frame (#1581).

    OpenRouter reports rate-limit / no-provider / upstream-5xx failures as an
    `error` object inside a 200 stream. `nested=True` places it on the *choice*
    (the shape the `openai` SDK does NOT raise on, so the adapter must); `False`
    places it at the top level of the chunk.
    """
    err = {"code": 429, "message": message}
    if nested:
        delta = SimpleNamespace(content=None, reasoning=None, reasoning_content=None)
        choice = SimpleNamespace(delta=delta, finish_reason="error", error=err)
        return SimpleNamespace(choices=[choice], usage=None)
    return SimpleNamespace(choices=[], usage=None, error=err)


def _two_choice_chunk(*, idx0=None, idx1=None, finish0=None, finish1=None):
    """A fake chunk with TWO choices (#1588) — models the doubled-choice shape
    deepseek/OpenRouter emits. The adapter reads only choices[0], so content in
    idx1 while idx0 is empty is invisible to the client but must show in diag."""
    def _choice(content, finish):
        delta = SimpleNamespace(
            content=content, reasoning=None, reasoning_content=None, refusal=None
        )
        return SimpleNamespace(delta=delta, finish_reason=finish)

    return SimpleNamespace(
        choices=[_choice(idx0, finish0), _choice(idx1, finish1)], usage=None
    )


class _FakeSdkStream:
    """Fake `openai.Stream`: iterable over `chunks`, and records `.close()` (#1570)
    the way the real SDK `Stream.close()` closes the upstream httpx response."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.closed = False

    def __iter__(self):
        return iter(self._chunks)

    def close(self):
        self.closed = True


_DIAG_LOGGER = "app.services.ai.profiles.openai_compatible"


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
                    completions=SimpleNamespace(create=lambda **_kw: _FakeSdkStream(chunks))
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

    def _run_capturing_create(self, profile, call):
        """Like `_run`, but capture the kwargs passed to `completions.create`
        so the temperature gate on the STREAMING send path can be asserted."""
        captured: dict = {}

        def _create(**kw):
            captured.update(kw)
            return _FakeSdkStream([_chunk(content="ok", finish="stop")])

        class _FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=_create)
                )

        with patch("openai.OpenAI", _FakeOpenAI):
            list(profile.chat_stream(call))
        return captured

    def _run_capturing_chat(self, profile, call):
        """Capture the kwargs of the NON-streaming `chat()` create call, so its
        temperature gate is locked independently of the streaming path."""
        captured: dict = {}

        def _create(**kw):
            captured.update(kw)
            choice = SimpleNamespace(
                message=SimpleNamespace(content="ok"), finish_reason="stop"
            )
            return SimpleNamespace(choices=[choice])

        class _FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=_create)
                )

        with patch("openai.OpenAI", _FakeOpenAI):
            profile.chat(call)
        return captured

    def test_non_streaming_chat_omits_temperature_for_no_sampling_model(self):
        # The same gate as the stream path, on chat() (openai_compatible.py:97).
        call = ChatCall(
            model="anthropic/claude-opus-4-8",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
            temperature=0.9,
        )
        captured = self._run_capturing_chat(OpenRouterProfile(api_key="sk-or"), call)
        self.assertNotIn("temperature", captured)

    def test_non_streaming_chat_sends_temperature_for_a_temp_ok_model(self):
        call = ChatCall(
            model="openai/gpt-4o",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
            temperature=0.3,
        )
        captured = self._run_capturing_chat(OpenRouterProfile(api_key="sk-or"), call)
        self.assertEqual(captured["temperature"], 0.3)

    def test_temperature_sent_for_a_temp_ok_openrouter_model(self):
        call = ChatCall(
            model="openai/gpt-4o",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
            temperature=0.3,
        )
        captured = self._run_capturing_create(OpenRouterProfile(api_key="sk-or"), call)
        self.assertEqual(captured["temperature"], 0.3)

    def test_temperature_omitted_for_no_sampling_model_via_openrouter(self):
        # The same model the family rule forbids, reached as `anthropic/…`, must
        # not put temperature on the wire — the OpenAI-compatible send path used
        # to send it unconditionally, 400ing at runtime (#1554).
        call = ChatCall(
            model="anthropic/claude-opus-4-8",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
            temperature=0.9,
        )
        captured = self._run_capturing_create(OpenRouterProfile(api_key="sk-or"), call)
        self.assertNotIn("temperature", captured)

    def test_openrouter_stream_surfaces_reasoning_and_keeps_content_plain(self):
        # #1588: reasoning routes stream chain-of-thought on the `reasoning`
        # field; it must surface as thinking (dropping it made reasoning-only /
        # truncated turns blank). Content stays PLAIN — no <think>-tag splitting.
        # Timeout/base_url unchanged.
        chunks = [
            _chunk(reasoning="pondering", content="Hi"),
            _chunk(finish="stop"),
            _chunk(
                usage=SimpleNamespace(
                    prompt_tokens=3, completion_tokens=1, prompt_tokens_details=None
                )
            ),
        ]
        events, captured = self._run(OpenRouterProfile(api_key="sk-or"), chunks)
        thinking = [e.text for e in events if isinstance(e, StreamThinking)]
        deltas = [e.text for e in events if isinstance(e, StreamDelta)]
        self.assertEqual(thinking, ["pondering"])
        self.assertEqual("".join(deltas), "Hi")
        self.assertEqual(captured["timeout"], 300.0)
        self.assertEqual(captured["base_url"], "https://openrouter.ai/api/v1")

    def test_openrouter_content_is_not_think_tag_split(self):
        # The content-only property the original override protected: literal
        # <think> markers inside content must NOT be re-parsed as thinking.
        chunks = [_chunk(content="a<think>b</think>c", finish="stop")]
        events, _ = self._run(OpenRouterProfile(api_key="sk-or"), chunks)
        thinking = [e for e in events if isinstance(e, StreamThinking)]
        deltas = [e.text for e in events if isinstance(e, StreamDelta)]
        self.assertEqual(thinking, [])
        self.assertEqual("".join(deltas), "a<think>b</think>c")

    def test_openrouter_reasoning_only_turn_is_not_empty(self):
        # The deepseek-v4-pro failure (#1588): the model burns the whole budget
        # reasoning and finishes on 'length' with no content. Reasoning must
        # still reach the client as thinking so the turn is not a blank
        # "Model returned empty output".
        chunks = [
            _chunk(reasoning="thinking and thinking", finish="length"),
            _chunk(usage=SimpleNamespace(
                prompt_tokens=3, completion_tokens=4096, prompt_tokens_details=None)),
        ]
        with self.assertNoLogs(_DIAG_LOGGER, level="WARNING"):
            events, _ = self._run(OpenRouterProfile(api_key="sk-or"), chunks)
        thinking = [e.text for e in events if isinstance(e, StreamThinking)]
        self.assertEqual("".join(thinking), "thinking and thinking")
        self.assertEqual([e for e in events if isinstance(e, StreamDelta)], [])

    # ---- in-band error surfacing (#1581) --------------------------------
    # OpenRouter's rate-limit / no-provider / upstream-5xx failures ride inside a
    # 200 stream as an `error` object. A choice-nested one does not make the SDK
    # raise, so the adapter used to end the stream with empty content and a fake
    # "success" ("Model returned empty output" in the UI). It must surface.

    def test_stream_surfaces_choice_nested_error(self):
        chunks = [_error_chunk(message="Rate limited by upstream provider")]
        with self.assertRaises(ProviderError) as ctx:
            self._run(OpenRouterProfile(api_key="sk-or"), chunks)
        self.assertIn("Rate limited by upstream provider", str(ctx.exception))

    def test_stream_surfaces_top_level_error_chunk(self):
        # Defensive: a top-level error frame the SDK let through must also surface.
        chunks = [_error_chunk(message="No available provider", nested=False)]
        with self.assertRaises(ProviderError) as ctx:
            self._run(OpenRouterProfile(api_key="sk-or"), chunks)
        self.assertIn("No available provider", str(ctx.exception))

    def test_partial_deltas_then_error_still_surfaces(self):
        # Content can arrive before the error frame; the deltas seen so far are
        # kept, then the error is raised (not swallowed after some output).
        chunks = [
            _chunk(content="Hel"),
            _error_chunk(message="Upstream 502"),
        ]
        with self.assertRaises(ProviderError) as ctx:
            self._run(OpenRouterProfile(api_key="sk-or"), chunks)
        self.assertIn("Upstream 502", str(ctx.exception))

    def test_choice_nested_error_reaches_wire_as_stream_error(self):
        # End-to-end through the dispatcher: the surfaced error must reach the
        # client as a StreamError carrying OpenRouter's message — the event the
        # frontend renders (cf. #1546, "test what reaches the wire").
        chunks = [_error_chunk(message="No endpoints found for your data policy")]

        class _FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=lambda **_kw: _FakeSdkStream(chunks))
                )

        call = ChatCall(
            model="deepseek/deepseek-v4-pro-0813",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
        )
        with patch("openai.OpenAI", _FakeOpenAI), patch.object(
            ai_providers, "profile_for",
            lambda *_a, **_k: OpenRouterProfile(api_key="sk-or-test"),
        ), patch.object(ai_providers, "_ensure_provider_key", lambda *_a, **_k: None):
            events = list(
                ai_providers.chat_stream(
                    call, provider_name="openrouter", settings=None, policy="cloud"
                )
            )
        errors = [e for e in events if isinstance(e, ai_providers.StreamError)]
        self.assertEqual(len(errors), 1)
        self.assertIn("No endpoints found for your data policy", errors[0].error)
        # And no fake terminal "success" alongside the error.
        self.assertFalse([e for e in events if isinstance(e, ai_providers.StreamDone)])

    # ---- non-stream chat() mirror guard (#1581) -------------------------

    def _run_chat(self, profile, response):
        class _FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=lambda **_kw: response)
                )

        call = ChatCall(
            model="deepseek/deepseek-v4-pro-0813",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
        )
        with patch("openai.OpenAI", _FakeOpenAI):
            return profile.chat(call)

    def test_non_stream_chat_surfaces_choice_nested_error(self):
        choice = SimpleNamespace(
            message=SimpleNamespace(content=None),
            finish_reason="error",
            error={"code": 429, "message": "Rate limited"},
        )
        response = SimpleNamespace(choices=[choice])
        with self.assertRaises(ProviderError) as ctx:
            self._run_chat(OpenRouterProfile(api_key="sk-or"), response)
        self.assertIn("Rate limited", str(ctx.exception))

    def test_non_stream_chat_surfaces_top_level_error(self):
        # OpenRouter's non-stream failures arrive as a 200 whose body IS the
        # error object (no choices). The response-level guard must surface that
        # message rather than falling through to the generic "no choices" text.
        response = SimpleNamespace(
            choices=[], error={"code": 402, "message": "Insufficient credits"}
        )
        with self.assertRaises(ProviderError) as ctx:
            self._run_chat(OpenRouterProfile(api_key="sk-or"), response)
        self.assertIn("Insufficient credits", str(ctx.exception))

    def test_non_stream_chat_guards_empty_choices(self):
        # A 200 with no choices and no error must be a clean ProviderError, not
        # an IndexError on `response.choices[0]`.
        response = SimpleNamespace(choices=[])
        with self.assertRaises(ProviderError):
            self._run_chat(OpenRouterProfile(api_key="sk-or"), response)

    # ---- empty-stream diagnostics (#1588) -------------------------------
    # When a stream yields no visible content, log ONE line naming the cause so
    # the intermittent "Model returned empty output" stops being invisible.

    def test_empty_stream_surfaces_as_error_with_diagnostic_in_detail(self):
        # choices[0] empty, choices[1] carries the text: the adapter (choices[0]
        # only) yields nothing → surfaced as a ProviderError (#1601), not a silent
        # empty completion. The idx0/other split lands in `detail` (→ errors.log),
        # never in the user-facing message. It's still logged as a WARNING.
        chunks = [_two_choice_chunk(idx0=None, idx1="hi", finish0="stop", finish1="stop")]
        with self.assertLogs(_DIAG_LOGGER, level="WARNING"), \
                self.assertRaises(ProviderError) as ctx:
            self._run(OpenRouterProfile(api_key="sk-or"), chunks)
        self.assertIn("no output", str(ctx.exception))
        detail = ctx.exception.detail or ""
        self.assertIn("content_idx0=0", detail)
        self.assertIn("content_other=2", detail)
        self.assertIn("max_choices=2", detail)
        # The user-facing message must NOT carry the raw diagnostic.
        self.assertNotIn("content_idx0", str(ctx.exception))

    def test_empty_stream_detail_captures_refusal_and_finish(self):
        delta = SimpleNamespace(
            content=None, reasoning=None, reasoning_content=None,
            refusal="I can't help with that.",
        )
        choice = SimpleNamespace(delta=delta, finish_reason="content_filter")
        chunks = [SimpleNamespace(choices=[choice], usage=None)]
        with self.assertLogs(_DIAG_LOGGER, level="WARNING"), \
                self.assertRaises(ProviderError) as ctx:
            self._run(OpenRouterProfile(api_key="sk-or"), chunks)
        detail = ctx.exception.detail or ""
        self.assertIn("can't help", detail)
        self.assertIn("content_filter", detail)

    def test_non_empty_stream_does_not_log(self):
        chunks = [
            _chunk(content="Hello", finish="stop"),
            _chunk(usage=SimpleNamespace(
                prompt_tokens=1, completion_tokens=1, prompt_tokens_details=None)),
        ]
        with self.assertNoLogs(_DIAG_LOGGER, level="WARNING"):
            self._run(OpenRouterProfile(api_key="sk-or"), chunks)

    def test_stream_diag_accumulates_signals(self):
        # Pin the diagnostic accumulator directly: reasoning chars, the
        # per-choice content split, choice count, and finish reasons.
        from app.services.ai.profiles.openai_compatible import _StreamDiag

        diag = _StreamDiag()
        diag.observe(_chunk(reasoning="think", finish="stop"))
        diag.observe(_two_choice_chunk(idx0=None, idx1="hi"))
        self.assertEqual(diag.reasoning, len("think"))
        self.assertEqual(diag.content_idx0, 0)
        self.assertEqual(diag.content_other, len("hi"))
        self.assertEqual(diag.max_choices, 2)
        self.assertIn((0, "stop"), diag.finishes)

    def test_thinking_only_stream_does_not_log(self):
        # Reasoning surfaced as thinking (no content) IS visible output — an
        # OpenAI turn that emits StreamThinking must NOT log "empty". Pins that
        # `emitted` counts thinking, not just content deltas.
        chunks = [_chunk(reasoning="pondering", finish="stop")]
        with self.assertNoLogs(_DIAG_LOGGER, level="WARNING"):
            events, _ = self._run(OpenAIProfile(api_key="sk-openai"), chunks)
        self.assertTrue([e for e in events if isinstance(e, StreamThinking)])

    # ---- upstream teardown on early stop (#1570) -------------------------
    # Closing the outer NDJSON generator early (the wrapper's cascade on client
    # Stop) must reach the SDK `Stream` — proving the `finally: stream.close()`
    # in `chat_stream` actually runs when the generator unwinds via GeneratorExit
    # rather than draining to completion.

    def test_openai_stream_closes_upstream_on_early_stop(self):
        chunks = [
            _chunk(content="a"),
            _chunk(content="b"),
            _chunk(content="c", finish="stop"),
        ]
        fake_stream = _FakeSdkStream(chunks)

        class _FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=lambda **_kw: fake_stream)
                )

        call = ChatCall(
            model="m",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
        )
        with patch("openai.OpenAI", _FakeOpenAI):
            gen = OpenAIProfile(api_key="sk-openai").chat_stream(call)
            next(gen)  # consume one event — don't drain the stream
            gen.close()
        self.assertTrue(fake_stream.closed)

    def test_ollama_stream_closes_upstream_on_early_stop(self):
        # Ollama has no chat_stream override — this proves the teardown is
        # inherited from OpenAICompatibleProfile, not reimplemented per provider.
        chunks = [
            _chunk(content="a"),
            _chunk(content="b"),
            _chunk(content="c", finish="stop"),
        ]
        fake_stream = _FakeSdkStream(chunks)

        class _FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=lambda **_kw: fake_stream)
                )

        call = ChatCall(
            model="m",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
        )
        with patch("openai.OpenAI", _FakeOpenAI):
            gen = OllamaProfile(host="http://127.0.0.1:11434").chat_stream(call)
            next(gen)  # consume one event — don't drain the stream
            gen.close()
        self.assertTrue(fake_stream.closed)


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
        # anthropic 1.x dropped `temperature` from the typed create/stream params,
        # so it rides in `extra_body`, never top-level (a top-level kwarg raises
        # TypeError: unexpected keyword argument 'temperature').
        self.assertNotIn("temperature", create)
        self.assertEqual(create["extra_body"]["temperature"], 1.0)

    def test_thinking_on_newest_model_uses_adaptive_no_budget_no_temperature(self):
        # 4.7+/5 families removed both the fixed thinking budget and sampling:
        # `{"type": "enabled", "budget_tokens": N}` and any temperature each 400.
        # Thinking must go out as adaptive with NO budget_tokens and NO temperature
        # (top-level or extra_body), or an assistant with ai_thinking enabled on
        # one of these models fails on send (#1559).
        call = ChatCall(
            model="claude-opus-4-8",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=2048,
            thinking_enabled=True,
        )
        _out, captured = self._run(call, [], usage=_a_usage())
        create = captured["create"]
        self.assertEqual(
            create["thinking"], {"type": "adaptive", "display": "summarized"}
        )
        self.assertNotIn("budget_tokens", create["thinking"])
        self.assertNotIn("temperature", create)
        self.assertNotIn("temperature", create.get("extra_body", {}))

    def test_temperature_rides_in_extra_body_not_top_level(self):
        # Regression: a temp-ok model (Haiku 4.5) with an explicit temperature
        # must send it via extra_body, or the anthropic 1.x SDK raises
        # "TypeError: ... unexpected keyword argument 'temperature'".
        call = ChatCall(
            model="claude-haiku-4-5",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
            temperature=0.3,
        )
        _out, captured = self._run(call, [], usage=_a_usage())
        create = captured["create"]
        self.assertNotIn("temperature", create)
        self.assertEqual(create["extra_body"]["temperature"], 0.3)

    def test_temperature_omitted_for_no_sampling_models(self):
        # Opus 5 (and the other newest families) 400 on temperature — it must not
        # be sent at all, not even via extra_body.
        call = ChatCall(
            model="claude-opus-5",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
            temperature=0.9,
        )
        _out, captured = self._run(call, [], usage=_a_usage())
        create = captured["create"]
        self.assertNotIn("temperature", create)
        self.assertNotIn("temperature", create.get("extra_body", {}))

    # ---- upstream teardown on early stop (#1570) -------------------------

    def test_anthropic_stream_closes_upstream_on_early_stop(self):
        # `with client.messages.stream(...) as stream:`'s __exit__ must run even
        # when the generator is closed early (the GeneratorExit cascade from a
        # client Stop) — confirms Anthropic already tears down the upstream,
        # unlike OpenAI-compat's un-closed `Stream` (fixed in openai_compatible.py).
        captured: dict = {}

        class _FakeStream:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                captured["exited"] = True
                return False

            def __iter__(self):
                return iter([
                    _a_delta_event("text_delta", text="a"),
                    _a_delta_event("text_delta", text="b"),
                    _a_delta_event("text_delta", text="c"),
                ])

            def get_final_message(self):
                return SimpleNamespace(stop_reason="end_turn", usage=None)

        class _FakeAnthropic:
            def __init__(self, **_kwargs):
                self.messages = SimpleNamespace(stream=lambda **_kw: _FakeStream())

        call = ChatCall(
            model="claude-sonnet-4-6",
            system_prompt="",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=64,
        )
        with patch("anthropic.Anthropic", _FakeAnthropic):
            gen = AnthropicProfile(api_key="sk-ant").chat_stream(call)
            next(gen)  # consume one event — don't drain the stream
            gen.close()
        self.assertTrue(captured.get("exited"))


if __name__ == "__main__":
    unittest.main()
