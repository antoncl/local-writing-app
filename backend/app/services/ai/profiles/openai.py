"""OpenAI profile.

Mirrors AnthropicProfile: live `/v1/models` confirms existence; bake-in
supplies tier + cost + capability data because OpenAI doesn't publish
pricing on the models endpoint.
"""

from __future__ import annotations

import logging
import re
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

if TYPE_CHECKING:
    from app.services.machine_settings import MachineSettings

log = logging.getLogger(__name__)


# OpenAI reasoning models (o1 / o3 / o4 families) don't sample and 400 on a
# `temperature` parameter — the same shape as the Anthropic no-sampling families
# the base rule already excludes (see family_supports_temperature). Anchored
# `o<digit>` so it catches o1 / o3-mini / o4-mini but not a sampling model whose
# id merely contains an "o" (gpt-4o, chatgpt-4o-latest).
_OPENAI_REASONING_RE = re.compile(r"^o\d", re.IGNORECASE)


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
            self._cache = baked
            return baked
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
            self._cache = baked
            return baked

        # Bake-in stays the tier/cost truth; live_catalog (ADR-0073 S4) surfaces
        # models newer than the audit file as unverified rows.
        merged = merge_live_catalogue(
            "openai",
            baked,
            payload.get("data") or [],
            surface_live_only=self.live_catalog,
        )
        self._cache = merged
        return merged

    def caching_style(self, model_id: str) -> CachingStyle:
        # OpenAI caches input transparently for prompts ≥ 1024 tokens;
        # no request markup needed. Dispatch layer sends as-is.
        return "auto"

    def supports_temperature(self, model_id: str) -> bool:
        # o1/o3/o4 reject `temperature`; every other OpenAI model accepts it.
        # One override covers both send paths — chat() and _open_stream() each
        # gate on self.supports_temperature (openai_compatible.py). Strip any
        # `provider/` route segment so a routed id is caught like the native one.
        if _OPENAI_REASONING_RE.match(model_id.split("/", 1)[-1]):
            return False
        return super().supports_temperature(model_id)

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
