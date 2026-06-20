"""Anthropic profile.

Live discovery via `/v1/models` confirms which model ids exist; tier +
cost data come from `_baked_in.yaml` (Anthropic doesn't publish pricing
on the models endpoint). When discovery fails (offline, bad key), fall
back to the bake-in catalogue alone.
"""

from __future__ import annotations

import logging

import httpx

from app.services.ai.profiles._loader import baked_in_for, mark_deprecated
from app.services.ai.profiles.base import (
    CachingStyle,
    CapabilityTier,
    ModelDescriptor,
    ProviderProfile,
)


log = logging.getLogger(__name__)


class AnthropicProfile(ProviderProfile):
    name = "anthropic"
    display_name = "Anthropic"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._cache: list[ModelDescriptor] | None = None

    async def list_models(self, *, force_refresh: bool = False) -> list[ModelDescriptor]:
        if not force_refresh and self._cache is not None:
            return self._cache
        baked = baked_in_for("anthropic")
        if not self._api_key:
            # No key → can't discover, just use bake-in.
            self._cache = baked
            return baked
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                response = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Anthropic /v1/models failed (%s); using bake-in", exc)
            self._cache = baked
            return baked

        live_ids = {row["id"] for row in payload.get("data") or [] if row.get("id")}
        # Merge: bake-in is the source of tier/cost truth; live confirms
        # existence. A baked-in model that no longer appears live is marked
        # deprecated (gives the picker a chance to suggest the successor).
        # A live model not in bake-in is hidden until someone adds tier
        # data — the alternative is showing a model with no tier in the
        # picker, which breaks the resolver.
        merged: list[ModelDescriptor] = []
        for descriptor in baked:
            if descriptor.id in live_ids or descriptor.deprecated:
                merged.append(descriptor)
                continue
            # Live API says this model no longer exists. Mark deprecated
            # in-place so the picker shows a warning.
            merged.append(mark_deprecated(descriptor))
        self._cache = merged
        return merged

    def caching_style(self, model_id: str) -> CachingStyle:
        # All current Anthropic models support explicit prompt caching via
        # `cache_control: ephemeral`. We don't gate per-model because every
        # production model in the bake-in supports it.
        return "explicit"
