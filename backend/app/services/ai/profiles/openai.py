"""OpenAI profile.

Mirrors AnthropicProfile: live `/v1/models` confirms existence; bake-in
supplies tier + cost + capability data because OpenAI doesn't publish
pricing on the models endpoint.
"""

from __future__ import annotations

import logging

import httpx

from app.services.ai.profiles._loader import baked_in_for, mark_deprecated
from app.services.ai.profiles.base import (
    CachingStyle,
    ModelDescriptor,
    ProviderProfile,
)


log = logging.getLogger(__name__)


class OpenAIProfile(ProviderProfile):
    name = "openai"
    display_name = "OpenAI"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._cache: list[ModelDescriptor] | None = None

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

        live_ids = {row["id"] for row in payload.get("data") or [] if row.get("id")}
        merged: list[ModelDescriptor] = []
        for descriptor in baked:
            if descriptor.id in live_ids or descriptor.deprecated:
                merged.append(descriptor)
                continue
            merged.append(mark_deprecated(descriptor))
        self._cache = merged
        return merged

    def caching_style(self, model_id: str) -> CachingStyle:
        # OpenAI caches input transparently for prompts ≥ 1024 tokens;
        # no request markup needed. Dispatch layer sends as-is.
        return "auto"
