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
from app.services.ai.profiles.cache_strategy import (
    ANTHROPIC_BREAKPOINTS,
    NO_CACHE,
    PREFIX_CACHE,
)

# A distinctive string that only appears in the "lore" (non-first) system block,
# so its presence in the wire proves the block was not dropped.
LORE = "LORE-SENTINEL-9f3a2c"
BASE = "BASE SYSTEM PROMPT"

# ADR-0084 Slice 1: the old caching_style string param is now a CacheStrategy
# instance; this table keeps the parametrization's cases the same three shapes
# (markers / collapse-cached / collapse-uncached).
_STRATEGY_BY_STYLE = {"explicit": ANTHROPIC_BREAKPOINTS, "auto": PREFIX_CACHE, "none": NO_CACHE}


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

    plan = _STRATEGY_BY_STYLE[style].plan(_blocks())
    wire = _wire(openrouter_system_messages(plan))
    assert LORE in wire, f"lore system block dropped for cache strategy kind={style!r}"
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

    plan = ANTHROPIC_BREAKPOINTS.plan(_blocks())
    wire = _wire(anthropic_system_blocks(plan))
    assert LORE in wire, "anthropic system payload dropped the lore block"
    assert BASE in wire


# --- ADR-0092 §7.1: a pick-only chat's commit turn reaches the wire too. ---


def test_a_pick_only_chats_commit_turn_reaches_the_provider_system_blocks(tmp_path, monkeypatch) -> None:
    # A chat with the flag off but a `use()` pick still commits that pick on
    # the `"used"` turn (keyed on the picks, never on the flag) — and the real
    # system_blocks the send path builds must reach the provider's wire, the
    # same invariant the synthetic cases above guard.
    monkeypatch.setattr(
        "app.services.machine_settings.config_path",
        lambda: tmp_path / "machine_settings.yaml",
    )
    from app.models import (
        CreateChatSessionRequest,
        CreateLoreEntryRequest,
        SaveChatSessionRequest,
        SaveLoreEntryRequest,
    )
    from app.services.ai.chat import expand_and_prepare_chat_blocks
    from app.services.ai.profiles.openai import OpenAIProfile
    from app.services.project_service import ProjectService

    service = ProjectService.created_at(tmp_path / "project", "Wire Picks")
    entry = service.create_lore_entry(
        CreateLoreEntryRequest(title="Sidebar", entry_type="lore:note")
    )
    entry = service.save_lore_entry(
        entry.id,
        SaveLoreEntryRequest(
            title="Sidebar",
            body="A picked aside.",
            base_revision=entry.revision,
            entry_type="lore:note",
            metadata={},
        ),
    )
    chat = service.create_chat_session(
        CreateChatSessionRequest(title="Picks only", prompt_entry_id="p")
    )
    service.save_chat_session(
        chat.id,
        SaveChatSessionRequest(
            title="Picks only",
            prompt_entry_id="p",
            lore_enabled=False,
            used_node_ids=[entry.id],
        ),
    )
    prepared = expand_and_prepare_chat_blocks(
        service,
        chat.id,
        "SYSTEM PROMPT",
        [{"role": "user", "content": "commit"}],
        lore_mode="used",
    )
    assert prepared.system_blocks
    call = ChatCall(
        model="test-model",
        system_prompt="SYSTEM PROMPT",
        messages=[{"role": "user", "content": "commit"}],
        max_tokens=128,
        system_blocks=prepared.system_blocks,
    )
    profile = object.__new__(OpenAIProfile)
    wire = _wire(profile._build_messages(call))
    # The wire is JSON-encoded (quotes escaped), so check the id and body text
    # rather than the raw XML attribute syntax.
    assert entry.id in wire
    assert "A picked aside" in wire


# --- ADR-0093 §2: a snapshot pick's before element reaches the wire too. ---


def test_a_snapshot_picks_before_element_reaches_the_provider_system_blocks(
    tmp_path, monkeypatch
) -> None:
    # `use(node, snapshot=id)`'s before element rides the stable tier on every
    # turn — the same last-mile invariant the pick-only case above guards,
    # for the before's own `snapshot=` attribute.
    monkeypatch.setattr(
        "app.services.machine_settings.config_path",
        lambda: tmp_path / "machine_settings.yaml",
    )
    from app.models import (
        CreateChatSessionRequest,
        CreateLoreEntryRequest,
        SaveChatSessionRequest,
        SaveLoreEntryRequest,
        SnapshotPick,
    )
    from app.services.ai.chat import expand_and_prepare_chat_blocks
    from app.services.ai.profiles.openai import OpenAIProfile
    from app.services.project_service import ProjectService

    service = ProjectService.created_at(tmp_path / "project", "Wire Snapshot")
    entry = service.create_lore_entry(
        CreateLoreEntryRequest(title="Marek Vell", entry_type="lore:character")
    )
    entry = service.save_lore_entry(
        entry.id,
        SaveLoreEntryRequest(
            title="Marek Vell",
            body="A captain.",
            base_revision=entry.revision,
            entry_type="lore:character",
            metadata={},
        ),
    )
    snapshot = service.capture_snapshot(entry.id, kind="lore", origin="propagation")
    chat = service.create_chat_session(
        CreateChatSessionRequest(title="Follow a change", prompt_entry_id="p")
    )
    service.save_chat_session(
        chat.id,
        SaveChatSessionRequest(
            title="Follow a change",
            prompt_entry_id="p",
            lore_enabled=False,
            used_snapshots=[SnapshotPick(entry_id=entry.id, snapshot_id=snapshot.id)],
        ),
    )
    prepared = expand_and_prepare_chat_blocks(
        service, chat.id, "SYSTEM PROMPT", [{"role": "user", "content": "hi"}]
    )
    assert prepared.system_blocks
    stable = [b for b in prepared.system_blocks if b.get("tier") == "stable"]
    assert any(f'snapshot=\\"{snapshot.id}\\"' in json.dumps(b) for b in stable), stable
    call = ChatCall(
        model="test-model",
        system_prompt="SYSTEM PROMPT",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=128,
        system_blocks=prepared.system_blocks,
    )
    profile = object.__new__(OpenAIProfile)
    wire = _wire(profile._build_messages(call))
    assert entry.id in wire
    assert snapshot.id in wire
