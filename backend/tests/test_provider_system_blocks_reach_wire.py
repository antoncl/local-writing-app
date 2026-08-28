"""Every provider must carry every system block to the wire.

The gap this guards: context selection can be perfect (the right lore lands in
`ChatCall.system_blocks`) and still never reach the model, if a provider adapter
drops a block while assembling the request. That is exactly the bug that shipped
in the OpenRouter auto-cache path — the lore block was silently discarded for
deepseek/openai/grok routes, so the model answered as if it had no context.

These tests assert the invariant at the last mile: given `system_blocks` that
include a distinctive "lore" block, the text of EVERY block appears in the
provider's outgoing payload — for each provider family and each caching style.
A future adapter that drops blocks fails here.
"""

from __future__ import annotations

import importlib
import json

import pytest

from app.services.ai.profiles.base import ChatCall

# A distinctive string that only appears in the "lore" (non-first) system block,
# so its presence in the wire proves the block was not dropped.
LORE = "LORE-SENTINEL-9f3a2c"
BASE = "BASE SYSTEM PROMPT"


def _blocks() -> list[dict]:
    # Block 0 is the base prompt (also passed as system_prompt); block 1 is the
    # lore — the one the OpenRouter bug dropped.
    return [{"text": BASE, "tier": "stable"}, {"text": LORE, "tier": "volatile"}]


def _call(model: str = "test-model") -> ChatCall:
    return ChatCall(
        model=model,
        system_prompt=BASE,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=128,
        system_blocks=_blocks(),
    )


def _wire(obj) -> str:
    return json.dumps(obj, default=str)


# --- OpenRouter: the fixed bug. EVERY caching style must carry every block. ---


@pytest.mark.parametrize("style", ["explicit", "auto", "none"])
def test_openrouter_system_messages_carry_every_block(style: str) -> None:
    from app.services.ai.profiles.openrouter import openrouter_system_messages

    wire = _wire(openrouter_system_messages(BASE, _blocks(), style))
    assert LORE in wire, f"lore system block dropped for caching_style={style!r}"
    assert BASE in wire


# --- Every concrete profile's message/system assembly carries the lore. ---
# openrouter (per-model style), openai (auto), ollama (none) build a `messages`
# list; each inherits or overrides `_build_messages`. `object.__new__` skips
# credential config — `_build_messages` needs only the call + caching style.
@pytest.mark.parametrize(
    "cls_path",
    [
        "app.services.ai.profiles.openrouter.OpenRouterProfile",
        "app.services.ai.profiles.openai.OpenAIProfile",
        "app.services.ai.profiles.ollama.OllamaProfile",
    ],
)
def test_profile_build_messages_carry_lore(cls_path: str) -> None:
    module_name, class_name = cls_path.rsplit(".", 1)
    cls = getattr(importlib.import_module(module_name), class_name)
    profile = object.__new__(cls)  # no network/credentials — pure assembly
    messages = profile._build_messages(_call())
    assert LORE in _wire(messages), f"{class_name} dropped the lore system block"
    # sanity: the user turn is still there (we replaced only the system side)
    assert any(m.get("role") == "user" for m in messages)


# --- Anthropic builds `system` separately (explicit cache markers). ---


def test_anthropic_system_blocks_carry_every_block() -> None:
    from app.services.ai.profiles.anthropic import anthropic_system_blocks

    wire = _wire(anthropic_system_blocks(_blocks()))
    assert LORE in wire, "anthropic system payload dropped the lore block"
    assert BASE in wire
