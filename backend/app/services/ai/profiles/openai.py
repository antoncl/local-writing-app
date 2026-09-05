"""OpenAI profile.

Mirrors AnthropicProfile: live `/v1/models` confirms existence; bake-in
supplies tier + capability data because OpenAI doesn't publish pricing on the
models endpoint. Per-token COST is overlaid from OpenRouter's public feed via
the price oracle (ADR-0083); `_baked_in.yaml` is the offline price seed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from app.services.ai.profiles._loader import baked_in_for, merge_live_catalogue
from app.services.ai.profiles.base import (
    CachingStyle,
    ModelDescriptor,
    UsageMetrics,
    default_token_count,
)
from app.services.ai.profiles.openai_compatible import OpenAICompatibleProfile
from app.services.ai.profiles.price_oracle import priced_with_oracle

if TYPE_CHECKING:
    from app.services.machine_settings import MachineSettings

log = logging.getLogger(__name__)


class OpenAIProfile(OpenAICompatibleProfile):
    name = "openai"
    display_name = "OpenAI"
    key_prefixes = ("sk-",)
    live_catalog = True

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._cache: list[ModelDescriptor] | None = None

    @classmethod
    def from_settings(cls, settings: MachineSettings) -> OpenAIProfile:
        return cls(api_key=settings.providers.openai_api_key or "")

    def _chat_base_url(self) -> str:
        return "https://api.openai.com/v1"

    async def list_models(self, *, force_refresh: bool = False) -> list[ModelDescriptor]:
        if not force_refresh and self._cache is not None:
            return self._cache
        baked = baked_in_for("openai")
        if not self._api_key:
            result = baked
        else:
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    response = await client.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                    )
                    response.raise_for_status()
                    payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("OpenAI /v1/models failed (%s); using bake-in", exc)
                result = baked
            else:
                # Bake-in stays the tier truth; live_catalog (ADR-0073 S4)
                # surfaces models newer than the audit file as unverified rows.
                result = merge_live_catalogue(
                    "openai",
                    baked,
                    payload.get("data") or [],
                    surface_live_only=self.live_catalog,
                )

        # Overlay per-token COST from the OpenRouter price oracle (ADR-0083);
        # fail-soft to the baked seed when the oracle is cold/offline.
        self._cache = await priced_with_oracle(result)
        return self._cache

    def caching_style(self, model_id: str) -> CachingStyle:
        # OpenAI caches input transparently for prompts ≥ 1024 tokens;
        # no request markup needed. Dispatch layer sends as-is.
        return "auto"

    def count_tokens(self, text: str, model_id: str) -> int:
        return default_token_count(text)

    def extract_usage(self, raw_response: Any, model_id: str) -> UsageMetrics:
        # OpenAI's usage.prompt_tokens INCLUDES cached tokens; subtract to
        # get the fresh full-rate slice. Cached subfield lives at
        # usage.prompt_tokens_details.cached_tokens.
        usage = getattr(raw_response, "usage", None)
        if usage is None:
            return UsageMetrics()
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        details = getattr(usage, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
        return UsageMetrics(
            input_tokens=max(0, prompt_tokens - cached),
            cached_input_tokens=cached,
            output_tokens=completion_tokens,
        )
