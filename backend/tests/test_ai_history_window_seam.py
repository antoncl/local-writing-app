"""#1958: the history window at the run_chat_turn send seam.

Proves what actually reaches the wire (per the "test what reaches the wire"
lesson, #1546): the provider gets the TRIMMED history, journal numbering still
sees the FULL list, the response carries history_fit, and the `used` commit turn
is exempt. The provider call, block prep, cost, and settings are stubbed so the
real apply_history_window / fit_history_window run against real count_tokens.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from app.models import AIChatRequest, ChatMessage
from app.services.ai import chat as chat_module
from app.services.ai.call_resolver import ResolvedCall


def _request(rounds: int) -> AIChatRequest:
    msgs: list[ChatMessage] = []
    for k in range(rounds):
        msgs.append(ChatMessage(role="user", content=f"user turn {k} with several words here"))
        msgs.append(ChatMessage(role="assistant", content=f"assistant reply {k} with several words"))
    msgs.append(ChatMessage(role="user", content="the current question with several words here"))
    return AIChatRequest(provider="ollama", model="llama3.2", messages=msgs)


def _run(request: AIChatRequest, *, budget: int | None, lore_mode: str):
    captured: dict = {}
    resolved = ResolvedCall(
        provider="ollama",
        model="llama3.2",
        temperature=None,
        max_tokens=8192,
        history_budget_tokens=budget,
    )
    settings = SimpleNamespace(
        providers=SimpleNamespace(ollama_host="http://127.0.0.1:11434")
    )
    prepared = chat_module.PreparedChatTurn(None, None, [], None, None)

    def _fake_expand(project, chat_id, system_prompt, messages_list, **kw):
        captured["expand_messages"] = list(messages_list)
        return prepared

    def _fake_chat(call, **kw):
        captured["call_messages"] = list(call.messages)
        return SimpleNamespace(
            content="ok", stop_reason="stop", provider="ollama", model="llama3.2",
            latency_ms=1, ok=True, error=None, usage=None,
        )

    async def _fake_cost(*a, **k):
        return None, None

    project = SimpleNamespace(ai_policy=lambda: "local-only")

    with patch.object(chat_module.machine_settings_service, "load_settings", return_value=settings), \
         patch.object(chat_module, "resolve_call_params", return_value=resolved), \
         patch.object(chat_module, "expand_and_prepare_chat_blocks", _fake_expand), \
         patch.object(chat_module.ai_providers, "chat", _fake_chat), \
         patch.object(chat_module, "translate_usage_to_cost", _fake_cost):
        response = asyncio.run(chat_module.run_chat_turn(project, request, lore_mode=lore_mode))
    return response, captured


def test_seam_trims_the_history_sent_to_the_provider() -> None:
    response, captured = _run(_request(4), budget=5, lore_mode="implicit")
    # Budget 5 is below any round → only the current turn reaches the provider…
    assert captured["call_messages"] == [
        {"role": "user", "content": "the current question with several words here"}
    ]
    # …but journal numbering still saw the full transcript (9 messages).
    assert len(captured["expand_messages"]) == 9
    assert response.history_fit is not None
    assert response.history_fit.dropped_rounds == 4
    assert response.history_fit.kept_rounds == 0


def test_seam_forwards_full_history_when_unlimited() -> None:
    response, captured = _run(_request(4), budget=None, lore_mode="implicit")
    assert captured["call_messages"] == captured["expand_messages"]  # untouched
    assert len(captured["call_messages"]) == 9
    assert response.history_fit is None


def test_commit_used_turn_is_exempt_from_the_window() -> None:
    # The extraction/commit turn (lore_mode="used") must send the full transcript
    # even with a tiny budget set on the assistant.
    response, captured = _run(_request(4), budget=5, lore_mode="used")
    assert captured["call_messages"] == captured["expand_messages"]
    assert len(captured["call_messages"]) == 9
    assert response.history_fit is None
