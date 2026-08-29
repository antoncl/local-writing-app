"""Unit tests for the extracted assistant-temperature validation (#178 slice 1).

Covers the free functions in `app.services.ai.assistant_validation` and the
registry's credential-less `capability_profile_for` that retired the router's
duplicate profile factory. There was no coverage for this validation before the
extraction — these tests are both the safety net for the move and the gap fill.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.services.ai.assistant_validation import (
    coerce_optional_temperature,
    validate_assistant_temperature,
)
from app.services.ai.profiles.registry import capability_profile_for

# A real Anthropic model whose API rejects `temperature` (see
# `NO_TEMPERATURE_FAMILIES`), and one that accepts it. Sampling was removed on
# the newest families (Opus 5, Sonnet 5, Fable 5, Opus 4.7/4.8) but 4.6 and older
# still accept it, so Sonnet 4.6 is a stable "accepts" pick.
FORBIDS_TEMPERATURE = "claude-opus-4-8"
ACCEPTS_TEMPERATURE = "claude-sonnet-4-6"


class CoerceOptionalTemperatureTests(unittest.TestCase):
    def test_none_empty_and_unparseable_collapse_to_none(self) -> None:
        for raw in (None, "", "   warm  ", "abc", [], {}):
            with self.subTest(raw=raw):
                self.assertIsNone(coerce_optional_temperature(raw))

    def test_numeric_and_numeric_strings_parse(self) -> None:
        self.assertEqual(coerce_optional_temperature("0.7"), 0.7)
        self.assertEqual(coerce_optional_temperature(0.2), 0.2)
        self.assertEqual(coerce_optional_temperature(1), 1.0)


class ValidateAssistantTemperatureTests(unittest.TestCase):
    def test_defers_when_information_is_incomplete(self) -> None:
        # Not enough to judge the (provider, model, temperature) combo →
        # never our error to raise; some other validation owns it.
        cases = [
            None,
            {},
            {"ai_model": ACCEPTS_TEMPERATURE},  # no provider
            {"ai_provider": "anthropic"},  # no model
            {"ai_provider": "", "ai_model": ACCEPTS_TEMPERATURE},  # empty provider
            {"ai_provider": "anthropic", "ai_model": ""},  # empty model
            {"ai_provider": 3, "ai_model": ACCEPTS_TEMPERATURE},  # non-str
            {"ai_provider": "nope", "ai_model": "x", "ai_temperature": 0.7},  # unknown provider
        ]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                self.assertIsNone(validate_assistant_temperature(metadata))

    def test_rejects_temperature_on_a_model_that_forbids_it(self) -> None:
        err = validate_assistant_temperature(
            {"ai_provider": "anthropic", "ai_model": FORBIDS_TEMPERATURE, "ai_temperature": 0.7}
        )
        self.assertIsNotNone(err)
        self.assertIn("does not accept a temperature", err)

    def test_allows_a_forbidding_model_when_no_temperature_is_set(self) -> None:
        self.assertIsNone(
            validate_assistant_temperature(
                {"ai_provider": "anthropic", "ai_model": FORBIDS_TEMPERATURE, "ai_temperature": ""}
            )
        )

    def test_allows_temperature_on_a_model_that_accepts_it(self) -> None:
        self.assertIsNone(
            validate_assistant_temperature(
                {"ai_provider": "anthropic", "ai_model": ACCEPTS_TEMPERATURE, "ai_temperature": 0.7}
            )
        )

    def test_rejects_no_sampling_model_reached_through_openrouter(self) -> None:
        # The same no-sampling model served by OpenRouter as `anthropic/…` must
        # be rejected too — the family rule now backs every provider's
        # capability profile, not just Anthropic direct (#1554).
        err = validate_assistant_temperature(
            {
                "ai_provider": "openrouter",
                "ai_model": "anthropic/claude-opus-4-8",
                "ai_temperature": 0.7,
            }
        )
        self.assertIsNotNone(err)
        self.assertIn("does not accept a temperature", err)

    def test_requires_temperature_branch_rejects_when_absent(self) -> None:
        # No shipping model sets requires_temperature, so drive the
        # forward-compat branch with a stub capability profile.
        stub = mock.Mock()
        stub.requires_temperature.return_value = True
        stub.supports_temperature.return_value = True
        with mock.patch(
            "app.services.ai.assistant_validation.capability_profile_for",
            return_value=stub,
        ):
            err = validate_assistant_temperature(
                {"ai_provider": "anthropic", "ai_model": "future-model"}
            )
        self.assertIsNotNone(err)
        self.assertIn("requires a temperature", err)


class CapabilityProfileForTests(unittest.TestCase):
    def test_known_providers_build_credential_less_profiles(self) -> None:
        for provider in ("anthropic", "openai", "openrouter", "ollama"):
            with self.subTest(provider=provider):
                self.assertIsNotNone(capability_profile_for(provider))

    def test_unknown_provider_returns_none_instead_of_raising(self) -> None:
        self.assertIsNone(capability_profile_for("nope"))


if __name__ == "__main__":
    unittest.main()
