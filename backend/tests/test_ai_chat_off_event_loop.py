"""#2293: the blocking provider call never runs on the event loop.

`ai_providers.chat` is synchronous and a local-model generation can take
minutes. Awaited on the loop (the commit extraction and `/api/ai/chat` go
through `run_chat_turn`) it froze the single-process server — every other
request stalled until the model finished. These tests prove the call runs on a
worker thread and that the loop keeps serving other work meanwhile.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

from app.models import AIChatRequest, ChatMessage
from app.services.ai import chat as chat_module
from app.services.ai import providers as ai_providers
from app.services.ai.call_resolver import ResolvedCall

_SLOW_SECONDS = 0.4


def _loop_running_in_this_thread() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _slow_fake_chat(seen: dict):
    def _fake_chat(call, **kw):
        seen["on_loop_thread"] = _loop_running_in_this_thread()
        time.sleep(_SLOW_SECONDS)  # a blocking wire call, like httpx.Client.post
        return SimpleNamespace(
            content="ok", stop_reason="stop", provider="ollama", model="llama3.2",
            latency_ms=1, ok=True, error=None, usage=None,
        )

    return _fake_chat


async def _count_ticks_while(coro) -> tuple[object, int]:
    """Run `coro` alongside a ticker; return its result and how often the loop
    got to run the ticker meanwhile. A blocked loop yields ~0 ticks."""
    ticks = 0
    done = asyncio.Event()

    async def _ticker() -> None:
        nonlocal ticks
        while not done.is_set():
            ticks += 1
            await asyncio.sleep(0.01)

    ticker = asyncio.create_task(_ticker())
    try:
        result = await coro
    finally:
        done.set()
        await ticker
    return result, ticks


def test_achat_runs_the_provider_call_off_the_event_loop() -> None:
    seen: dict = {}
    with patch.object(ai_providers, "chat", _slow_fake_chat(seen)):
        result, ticks = asyncio.run(
            _count_ticks_while(
                ai_providers.achat(
                    SimpleNamespace(), provider_name="ollama", settings=SimpleNamespace(), policy="local-only"
                )
            )
        )
    assert result.content == "ok"
    assert seen["on_loop_thread"] is False
    # 0.4 s at a 10 ms cadence ≈ 40 ticks when the loop is free; a blocked loop
    # manages one or two. Generous margin for a loaded CI box.
    assert ticks >= 10


def test_run_chat_turn_keeps_the_loop_free_during_the_provider_call() -> None:
    # The commit extraction and /api/ai/chat both await run_chat_turn.
    seen: dict = {}
    resolved = ResolvedCall(provider="ollama", model="llama3.2", temperature=None, max_tokens=512)
    settings = SimpleNamespace(providers=SimpleNamespace(ollama_host="http://127.0.0.1:11434"))
    prepared = chat_module.PreparedChatTurn(None, None, [], None, None)

    async def _fake_cost(*a, **k):
        return None, None

    request = AIChatRequest(
        provider="ollama", model="llama3.2", messages=[ChatMessage(role="user", content="hello")]
    )
    project = SimpleNamespace(ai_policy=lambda: "local-only")

    with patch.object(chat_module.machine_settings_service, "load_settings", return_value=settings), \
         patch.object(chat_module, "resolve_call_params", return_value=resolved), \
         patch.object(chat_module, "expand_and_prepare_chat_blocks", lambda *a, **k: prepared), \
         patch.object(ai_providers, "chat", _slow_fake_chat(seen)), \
         patch.object(chat_module, "translate_usage_to_cost", _fake_cost):
        response, ticks = asyncio.run(
            _count_ticks_while(chat_module.run_chat_turn(project, request, lore_mode="used"))
        )

    assert response.content == "ok"
    assert seen["on_loop_thread"] is False
    assert ticks >= 10
