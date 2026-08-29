"""AI stream failures reach errors.log; diagnostics ride in `detail`, off the wire (#1601).

The invariant: the user-facing wire line carries only `error` (a plain message);
the developer diagnostic travels in `StreamError.detail` and is recorded to the
project's `errors.log`, never serialized to the client.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.ai import providers as ai_providers
from app.services.ai.profiles.base import ChatCall
from app.services.ai.profiles.openrouter import OpenRouterProfile
from app.services.ai.streaming import transform_provider_events_to_ndjson


def _err(**kw) -> ai_providers.StreamError:
    base = {"provider": "openrouter", "model": "m", "latency_ms": 5,
            "error": "boom", "detail": "diag dump x=1"}
    base.update(kw)
    return ai_providers.StreamError(**base)


def test_on_error_receives_the_event_but_detail_stays_off_the_wire() -> None:
    seen: list[ai_providers.StreamError] = []
    lines = list(transform_provider_events_to_ndjson(
        iter([_err()]), policy="cloud", on_error=seen.append,
    ))
    # The hook sees the full StreamError, detail included...
    assert len(seen) == 1
    assert seen[0].detail == "diag dump x=1"
    # ...but the wire line carries only the user-facing `error`, never `detail`.
    payload = json.loads(lines[-1])
    assert payload["type"] == "error"
    assert payload["error"] == "boom"
    assert "detail" not in payload


def test_transform_without_a_hook_still_emits_the_error_line() -> None:
    lines = list(transform_provider_events_to_ndjson(iter([_err()]), policy="cloud"))
    assert json.loads(lines[-1])["error"] == "boom"


def test_a_throwing_on_error_hook_does_not_disrupt_the_error_line() -> None:
    def _boom(_ev):
        raise RuntimeError("sink broke")

    lines = list(transform_provider_events_to_ndjson(
        iter([_err()]), policy="cloud", on_error=_boom))
    # The recorder failed, but the user still gets the real error, not a generic one.
    assert json.loads(lines[-1])["error"] == "boom"


def _empty_chunk() -> SimpleNamespace:
    delta = SimpleNamespace(content=None, reasoning=None, reasoning_content=None,
                            refusal=None)
    choice = SimpleNamespace(delta=delta, finish_reason="length")
    return SimpleNamespace(choices=[choice], usage=None)


class _ClosableStream:
    """Fake `openai.Stream` — iterable with a `.close()` the adapter calls on
    every exit (#1570), including when the empty-stream ProviderError raises."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __iter__(self):
        return iter(self._chunks)

    def close(self):
        pass


def test_empty_stream_reaches_the_wire_as_error_with_message_only() -> None:
    class _FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(
                create=lambda **_kw: _ClosableStream([_empty_chunk()])))

    call = ChatCall(model="deepseek/deepseek-v4-pro-0813", system_prompt="",
                    messages=[{"role": "user", "content": "hi"}], max_tokens=64)
    with patch("openai.OpenAI", _FakeOpenAI), patch.object(
        ai_providers, "profile_for",
        lambda *_a, **_k: OpenRouterProfile(api_key="sk-or-test"),
    ), patch.object(ai_providers, "_ensure_provider_key", lambda *_a, **_k: None):
        events = list(ai_providers.chat_stream(
            call, provider_name="openrouter", settings=None, policy="cloud"))
    errors = [e for e in events if isinstance(e, ai_providers.StreamError)]
    assert len(errors) == 1
    assert "no output" in errors[0].error            # plain user message
    assert "errors.log" in errors[0].error           # names where to look
    assert errors[0].detail and "empty provider stream" in errors[0].detail  # diag in detail
    # No phantom terminal success alongside the error.
    assert not [e for e in events if isinstance(e, ai_providers.StreamDone)]


def test_record_ai_error_writes_message_and_detail_to_errors_log(tmp_path: Path) -> None:
    from app.services.project.client_errors import ErrorLogMixin

    class _Project(ErrorLogMixin):
        root_path = tmp_path

    _Project().record_ai_error(
        message="The model returned no output.",
        provider="openrouter",
        model="deepseek/deepseek-v4-pro-0813",
        detail="reasoning=19848 finishes=[(0,'length')]",
    )
    log = (tmp_path / "errors.log").read_text(encoding="utf-8")
    assert "backend error: The model returned no output." in log
    assert "reasoning=19848" in log                        # diagnostic detail recorded...
    assert "ai openrouter/deepseek/deepseek-v4-pro-0813" in log  # ...with provider/model context


def test_router_adapter_forwards_stream_error_to_record_ai_error() -> None:
    from app.routers.ai import _record_stream_error

    calls = []
    project = SimpleNamespace(record_ai_error=lambda **kw: calls.append(kw))
    _record_stream_error(project, _err(error="boom", detail="diag x=1"))
    assert calls == [{
        "message": "boom", "provider": "openrouter", "model": "m", "detail": "diag x=1",
    }]
