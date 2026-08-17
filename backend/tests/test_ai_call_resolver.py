"""Unit tests for the extracted call-parameter resolver (#178 slice 2).

`resolve_call_params` is the shared leaf six AI routes depend on, so its
override → assistant-metadata → settings-default priority chain is covered
directly here (the HTTP money-path tests exercise only the assistant branch).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from app.services.ai.call_resolver import ResolvedCall, resolve_call_params


def _project(assistant: object | None) -> mock.Mock:
    project = mock.Mock()
    project.resolve_assistant.return_value = assistant
    return project


def _settings(*, default_provider: str = "openai", default_models: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        default_provider=default_provider,
        default_models=default_models or {},
    )


class ResolveCallParamsTests(unittest.TestCase):
    def test_resolves_every_field_from_assistant_metadata(self) -> None:
        assistant = SimpleNamespace(
            metadata={
                "ai_provider": "anthropic",
                "ai_model": "claude-sonnet-5",
                "ai_temperature": 0.3,
                "ai_max_tokens": 2048,
                "ai_thinking": True,
            }
        )
        resolved = resolve_call_params(
            _project(assistant),
            _settings(),
            assistant_id="a1",
            provider_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        self.assertEqual(resolved.provider, "anthropic")
        self.assertEqual(resolved.model, "claude-sonnet-5")
        self.assertEqual(resolved.temperature, 0.3)
        self.assertEqual(resolved.max_tokens, 2048)
        self.assertTrue(resolved.thinking_enabled)

    def test_overrides_beat_assistant_metadata(self) -> None:
        assistant = SimpleNamespace(
            metadata={"ai_provider": "anthropic", "ai_model": "claude-sonnet-5", "ai_max_tokens": 2048}
        )
        resolved = resolve_call_params(
            _project(assistant),
            _settings(),
            assistant_id="a1",
            provider_override="openai",
            model_override="gpt-5",
            max_tokens_override=512,
        )
        self.assertEqual(resolved.provider, "openai")
        self.assertEqual(resolved.model, "gpt-5")
        self.assertEqual(resolved.max_tokens, 512)

    def test_invalid_assistant_max_tokens_falls_back_to_default(self) -> None:
        assistant = SimpleNamespace(
            metadata={"ai_provider": "anthropic", "ai_model": "claude-sonnet-5", "ai_max_tokens": "lots"}
        )
        resolved = resolve_call_params(
            _project(assistant),
            _settings(),
            assistant_id="a1",
            provider_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        self.assertEqual(resolved.max_tokens, 4096)

    def test_empty_assistant_temperature_coerces_to_none(self) -> None:
        assistant = SimpleNamespace(
            metadata={"ai_provider": "anthropic", "ai_model": "claude-sonnet-5", "ai_temperature": ""}
        )
        resolved = resolve_call_params(
            _project(assistant),
            _settings(),
            assistant_id="a1",
            provider_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        self.assertIsNone(resolved.temperature)

    def test_falls_back_to_settings_defaults_without_an_assistant(self) -> None:
        resolved = resolve_call_params(
            _project(None),
            _settings(default_provider="ollama", default_models={"ollama": "llama3"}),
            assistant_id=None,
            provider_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        self.assertEqual(resolved.provider, "ollama")
        self.assertEqual(resolved.model, "llama3")
        self.assertIsNone(resolved.temperature)
        self.assertEqual(resolved.max_tokens, 4096)

    def test_override_without_an_assistant_still_wins(self) -> None:
        resolved = resolve_call_params(
            _project(None),
            _settings(default_provider="ollama", default_models={"openai": "gpt-5"}),
            assistant_id=None,
            provider_override="openai",
            model_override=None,
            max_tokens_override=1024,
        )
        self.assertEqual(resolved.provider, "openai")
        self.assertEqual(resolved.model, "gpt-5")
        self.assertEqual(resolved.max_tokens, 1024)


class ResolvedCallToCallTests(unittest.TestCase):
    """`to_call` is the single bridge from resolved provider params + this
    turn's content into the provider-agnostic ChatCall the dispatch boundary
    takes. Each field must land in the right slot — a swap here would send the
    wrong model or silently drop thinking on the streaming path."""

    def test_merges_resolved_params_with_turn_content(self) -> None:
        resolved = ResolvedCall(
            provider="anthropic",
            model="claude-sonnet-5",
            temperature=0.4,
            max_tokens=2048,
            thinking_enabled=True,
        )
        messages = [{"role": "user", "content": "hi"}]
        blocks = [{"text": "sys", "tier": "stable"}]
        call = resolved.to_call(
            system_prompt="You are X.",
            messages=messages,
            system_blocks=blocks,
            session_id="sess-1",
        )
        # Provider params come from the ResolvedCall...
        self.assertEqual(call.model, "claude-sonnet-5")
        self.assertEqual(call.max_tokens, 2048)
        self.assertEqual(call.temperature, 0.4)
        self.assertTrue(call.thinking_enabled)
        # ...this turn's content from the arguments.
        self.assertEqual(call.system_prompt, "You are X.")
        self.assertIs(call.messages, messages)
        self.assertEqual(call.system_blocks, blocks)
        self.assertEqual(call.session_id, "sess-1")

    def test_optional_content_defaults_to_none(self) -> None:
        resolved = ResolvedCall(
            provider="ollama", model="llama3", temperature=None, max_tokens=4096
        )
        call = resolved.to_call(system_prompt="", messages=[])
        self.assertIsNone(call.system_blocks)
        self.assertIsNone(call.session_id)
        self.assertFalse(call.thinking_enabled)
        self.assertIsNone(call.temperature)


if __name__ == "__main__":
    unittest.main()
