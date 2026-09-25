"""Native `/api/chat` transport for Ollama (#1957).

Ollama's OpenAI-compat `/v1` shim can't set `num_ctx` and reloads the model at
its full trained context every call. These tests pin the native transport that
replaces it: the `/api/chat` endpoint (not `/v1`), a `num_ctx` sized to the turn
and clamped to the model's trained max (discovered via `/api/show`, #1956), the
NDJSON stream decode, and the failure modes.

All three internal `httpx.Client`s (the `/api/show` sizing probe and the
`/api/chat` call) are forced onto a `MockTransport`, so nothing hits the network.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.ai.call_resolver import OLLAMA_DEFAULT_MAX_TOKENS
from app.services.ai.profiles import ollama as ollama_mod
from app.services.ai.profiles.base import (
    ChatCall,
    ProviderError,
    StreamDelta,
    StreamFinal,
    StreamThinking,
)
from app.services.ai.profiles.ollama import OllamaProfile, _ceil_bucket

# A model whose GGUF metadata reports a 128k trained context.
_SHOW_128K = {
    "model_info": {
        "general.architecture": "llama",
        "llama.context_length": 131072,
    },
    "capabilities": ["completion"],
}


def _show(context_length: int) -> dict:
    return {
        "model_info": {
            "general.architecture": "llama",
            "llama.context_length": context_length,
        },
        "capabilities": ["completion"],
    }


def _ndjson(frames: list[dict]) -> bytes:
    return b"".join(json.dumps(f).encode() + b"\n" for f in frames)


class _Router:
    """Answers `/api/show` and `/api/chat` from canned data, recording each
    request so a test can assert what reached the wire."""

    def __init__(
        self,
        *,
        show: dict | None,
        chat_json: dict | None = None,
        chat_frames: list[dict] | None = None,
        chat_status: int = 200,
        ps: dict | None = None,
    ) -> None:
        self.show = show
        self.ps = ps
        self.chat_json = chat_json
        self.chat_frames = chat_frames
        self.chat_status = chat_status
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/show":
            if self.show is None:
                return httpx.Response(500)
            return httpx.Response(200, json=self.show)
        if path == "/api/ps" and self.ps is not None:
            return httpx.Response(200, json=self.ps)
        if path == "/api/chat":
            self.bodies.append(json.loads(request.content))
            if self.chat_status != 200:
                # Ollama reports a bad model / request as an HTTP error whose
                # body carries the reason (applies to both stream and non-stream).
                return httpx.Response(self.chat_status, json=self.chat_json or {})
            if self.bodies[-1].get("stream"):
                return httpx.Response(200, content=_ndjson(self.chat_frames or []))
            return httpx.Response(200, json=self.chat_json or {})
        return httpx.Response(404)


@pytest.fixture
def route(monkeypatch):
    """Install a `_Router` and force every `httpx.Client` the profile opens onto
    a `MockTransport` answering it (mirrors test_updates._mock_github)."""
    real_client = httpx.Client

    def install(router: _Router) -> _Router:
        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(router)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(ollama_mod.httpx, "Client", factory)
        return router

    return install


def _call(**over) -> ChatCall:
    base = {
        "model": "llama3.2:latest",
        "system_prompt": "",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 256,
        "temperature": None,
    }
    base.update(over)
    return ChatCall(**base)


# -- num_ctx sizing ------------------------------------------------------------


def test_ceil_bucket_rounds_up_and_passes_through_top() -> None:
    assert _ceil_bucket(1) == 2048
    assert _ceil_bucket(2048) == 2048
    assert _ceil_bucket(2049) == 4096
    assert _ceil_bucket(9000) == 16384
    # Above the largest bucket: pass through (the caller clamps to model max).
    assert _ceil_bucket(999_999) == 999_999


def test_chat_sizes_num_ctx_to_the_turn_not_the_model_max(route) -> None:
    router = route(_Router(show=_SHOW_128K, chat_json={"message": {"content": "hi"}}))
    OllamaProfile("http://box:11434").chat(_call())

    body = router.bodies[0]
    # A tiny prompt + a 256-token reply fits the smallest bucket — nowhere near
    # the 131072 the /v1 shim would have forced.
    assert body["options"]["num_ctx"] == 2048
    assert body["options"]["num_predict"] == 256


def _ps(name: str, context_length: int) -> dict:
    return {"models": [{"name": name, "model": name, "context_length": context_length}]}


def test_chat_reuses_a_larger_loaded_window_instead_of_shrinking(route) -> None:
    # #2203: the model is loaded at 32768 by a long chat; this 2048-sized turn (an
    # AI commit) must not ask for less — a different num_ctx reloads the model.
    router = route(
        _Router(
            show=_SHOW_128K,
            chat_json={"message": {"content": "hi"}},
            ps=_ps("llama3.2:latest", 32768),
        )
    )
    OllamaProfile("http://box:11434").chat(_call())
    assert router.bodies[0]["options"]["num_ctx"] == 32768


def test_chat_grows_past_a_smaller_loaded_window(route) -> None:
    router = route(
        _Router(
            show=_SHOW_128K,
            chat_json={"message": {"content": "hi"}},
            ps=_ps("llama3.2:latest", 2048),
        )
    )
    OllamaProfile("http://box:11434").chat(_call(max_tokens=8192))
    assert router.bodies[0]["options"]["num_ctx"] == 16384


def test_chat_ignores_another_models_loaded_window(route) -> None:
    router = route(
        _Router(
            show=_SHOW_128K,
            chat_json={"message": {"content": "hi"}},
            ps=_ps("qwen3:8b", 32768),
        )
    )
    OllamaProfile("http://box:11434").chat(_call())
    assert router.bodies[0]["options"]["num_ctx"] == 2048


def test_chat_matches_a_loaded_model_named_without_its_tag(route) -> None:
    # `/api/ps` reports "name:latest"; an assistant may name the model bare.
    router = route(
        _Router(
            show=_SHOW_128K,
            chat_json={"message": {"content": "hi"}},
            ps=_ps("llama3.2:latest", 32768),
        )
    )
    OllamaProfile("http://box:11434").chat(_call(model="llama3.2"))
    assert router.bodies[0]["options"]["num_ctx"] == 32768


def test_chat_reserves_reply_headroom_in_num_ctx(route) -> None:
    # num_ctx is the WHOLE window (prompt + generated), so the reply length
    # (num_predict) must fit inside it or the model truncates. An EXPLICIT
    # max_tokens=32768 still buckets to 64k — the profile honors what it's given.
    # (#1959 stops the *default* from being 32768 for Ollama at the resolver, so a
    # default chat never reaches this; see test_chat_default_reply_budget_*.) Pin
    # this so the headroom can't be "optimized" below num_predict (→ truncation).
    router = route(_Router(show=_SHOW_128K, chat_json={"message": {"content": "ok"}}))
    OllamaProfile("http://box:11434").chat(_call(max_tokens=32768))

    assert router.bodies[0]["options"]["num_ctx"] == 65536


def test_chat_default_reply_budget_yields_a_small_num_ctx(route) -> None:
    # The #1959 payoff: with Ollama's resolver default (8192) rather than 32768,
    # a plain chat lands num_ctx at 16k — on the GPU — instead of 64k. This pins
    # the downstream half; the resolver half is in test_ai_call_resolver.py.
    router = route(_Router(show=_SHOW_128K, chat_json={"message": {"content": "ok"}}))
    OllamaProfile("http://box:11434").chat(_call(max_tokens=OLLAMA_DEFAULT_MAX_TOKENS))

    assert router.bodies[0]["options"]["num_predict"] == 8192
    assert router.bodies[0]["options"]["num_ctx"] == 16384


def test_chat_clamps_num_ctx_to_model_trained_max(route) -> None:
    # A 4096-context model with a reply headroom that alone exceeds it: the
    # bucketed need is clamped down to the trained max, never above it.
    router = route(
        _Router(show=_show(4096), chat_json={"message": {"content": "ok"}})
    )
    OllamaProfile("http://box:11434").chat(_call(max_tokens=8000))

    assert router.bodies[0]["options"]["num_ctx"] == 4096


def test_chat_omits_num_ctx_when_context_is_undiscoverable(route) -> None:
    # /api/show fails (older Ollama, daemon race): degrade to the daemon default
    # rather than guessing a cap — no num_ctx on the wire.
    router = route(_Router(show=None, chat_json={"message": {"content": "ok"}}))
    OllamaProfile("http://box:11434").chat(_call())

    options = router.bodies[0]["options"]
    assert "num_ctx" not in options
    assert options["num_predict"] == 256


def test_chat_targets_native_endpoint_and_carries_temperature(route) -> None:
    router = route(_Router(show=_SHOW_128K, chat_json={"message": {"content": "ok"}}))
    OllamaProfile("http://box:11434").chat(_call(temperature=0.7))

    # Native /api/chat, never the /v1 shim.
    chat_paths = [r.url.path for r in router.requests if r.url.path == "/api/chat"]
    assert chat_paths == ["/api/chat"]
    assert all("/v1" not in str(r.url) for r in router.requests)
    assert router.bodies[0]["options"]["temperature"] == 0.7


def test_chat_carries_response_schema_as_native_format(route) -> None:
    # #2199: a `response_schema` on the call rides onto Ollama's native
    # `format` key (constrained decoding) — never sent when absent.
    router = route(_Router(show=_SHOW_128K, chat_json={"message": {"content": "ok"}}))
    schema = {"type": "object", "properties": {"fields": {"type": "object"}}}
    OllamaProfile("http://box:11434").chat(_call(response_schema=schema))

    assert router.bodies[0]["format"] == schema


def test_chat_omits_format_when_no_response_schema(route) -> None:
    router = route(_Router(show=_SHOW_128K, chat_json={"message": {"content": "ok"}}))
    OllamaProfile("http://box:11434").chat(_call())

    assert "format" not in router.bodies[0]


# -- non-streaming response ----------------------------------------------------


def test_chat_returns_content_and_done_reason(route) -> None:
    route(
        _Router(
            show=_SHOW_128K,
            chat_json={
                "message": {"content": "the reply"},
                "done_reason": "stop",
                "prompt_eval_count": 12,
                "eval_count": 5,
            },
        )
    )
    outcome = OllamaProfile("http://box:11434").chat(_call())

    assert outcome.content == "the reply"
    assert outcome.stop_reason == "stop"
    # The raw native dict flows to extract_usage.
    usage = OllamaProfile("http://box:11434").extract_usage(outcome.raw, "llama3.2")
    assert (usage.input_tokens, usage.output_tokens) == (12, 5)


def test_chat_raises_on_error_object(route) -> None:
    route(_Router(show=_SHOW_128K, chat_json={"error": "model 'x' not found"}))
    with pytest.raises(ProviderError, match="not found"):
        OllamaProfile("http://box:11434").chat(_call())


def test_chat_surfaces_ollama_message_on_http_error(route) -> None:
    # A 404 carrying Ollama's own reason must surface that reason, not a bare
    # "Client error 404".
    route(
        _Router(
            show=_SHOW_128K,
            chat_status=404,
            chat_json={"error": "model 'llama3.2' not found"},
        )
    )
    with pytest.raises(ProviderError, match="model 'llama3.2' not found"):
        OllamaProfile("http://box:11434").chat(_call())


# -- streaming -----------------------------------------------------------------


def test_stream_yields_content_thinking_and_final_usage(route) -> None:
    frames = [
        {"message": {"content": "Hello "}, "done": False},
        {"message": {"content": "<think>reasoning</think>"}, "done": False},
        {"message": {"content": "world"}, "done": False},
        {
            "message": {"content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 20,
            "eval_count": 8,
        },
    ]
    route(_Router(show=_SHOW_128K, chat_frames=frames))
    events = list(OllamaProfile("http://box:11434").chat_stream(_call()))

    text = "".join(e.text for e in events if isinstance(e, StreamDelta))
    thinking = "".join(e.text for e in events if isinstance(e, StreamThinking))
    finals = [e for e in events if isinstance(e, StreamFinal)]

    assert text == "Hello world"
    assert thinking == "reasoning"
    assert len(finals) == 1
    assert finals[0].stop_reason == "stop"
    assert finals[0].usage is not None
    assert (finals[0].usage.input_tokens, finals[0].usage.output_tokens) == (20, 8)


def test_stream_surfaces_thinking_field(route) -> None:
    # A thinking-capable model splits reasoning onto a `thinking` field.
    frames = [
        {"message": {"thinking": "pondering", "content": ""}, "done": False},
        {"message": {"content": "answer"}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": "stop"},
    ]
    route(_Router(show=_SHOW_128K, chat_frames=frames))
    events = list(OllamaProfile("http://box:11434").chat_stream(_call()))

    thinking = "".join(e.text for e in events if isinstance(e, StreamThinking))
    text = "".join(e.text for e in events if isinstance(e, StreamDelta))
    assert thinking == "pondering"
    assert text == "answer"


def test_stream_empty_output_raises_with_diagnostic_detail(route) -> None:
    frames = [{"message": {"content": ""}, "done": True, "done_reason": "stop"}]
    route(_Router(show=_SHOW_128K, chat_frames=frames))
    with pytest.raises(ProviderError, match="no output") as exc:
        list(OllamaProfile("http://box:11434").chat_stream(_call()))
    # The user-facing message stays plain; the diagnostic rides as `detail`
    # (errors.log, never the UI), restoring the /v1 path's #1601 behavior.
    assert exc.value.detail is not None
    assert "done_reason='stop'" in exc.value.detail


def test_stream_error_frame_raises(route) -> None:
    frames = [{"error": "context canceled"}]
    route(_Router(show=_SHOW_128K, chat_frames=frames))
    with pytest.raises(ProviderError, match="context canceled"):
        list(OllamaProfile("http://box:11434").chat_stream(_call()))


def test_stream_surfaces_ollama_message_on_http_error(route) -> None:
    # A non-200 opening the stream must surface Ollama's reason from the body,
    # read even though the response was opened for streaming.
    route(
        _Router(
            show=_SHOW_128K,
            chat_status=400,
            chat_json={"error": "invalid options.num_ctx"},
        )
    )
    with pytest.raises(ProviderError, match="invalid options.num_ctx"):
        list(OllamaProfile("http://box:11434").chat_stream(_call()))


def test_stream_sends_num_ctx_and_stream_flag(route) -> None:
    router = route(
        _Router(
            show=_SHOW_128K,
            chat_frames=[
                {"message": {"content": "x"}, "done": False},
                {"message": {"content": ""}, "done": True, "done_reason": "stop"},
            ],
        )
    )
    list(OllamaProfile("http://box:11434").chat_stream(_call()))

    body = router.bodies[0]
    assert body["stream"] is True
    assert body["options"]["num_ctx"] == 2048
