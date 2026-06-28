"""Ollama profile — local-only models discovered via the host's `/api/tags`.

Per [docs/ai-model-selection.md](../../../../../docs/ai-model-selection.md):
all Ollama models tier=LOCAL; no auto-rank since everything is free.
Picker just lists what's installed.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.ai.profiles.base import (
    CachingStyle,
    Capability,
    CapabilityTier,
    ModelDescriptor,
    ProviderProfile,
    UsageMetrics,
    default_token_count,
)

log = logging.getLogger(__name__)


class OllamaProfile(ProviderProfile):
    name = "ollama"
    display_name = "Ollama"

    def __init__(self, host: str) -> None:
        # Host is per-machine from MachineSettings.providers.ollama_host
        # (e.g. http://127.0.0.1:11434). Strip a trailing /v1 if present
        # — that's the OpenAI-compat suffix and not used for the native
        # tags endpoint.
        base = host.rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        self._base = base
        self._cache: list[ModelDescriptor] | None = None

    async def list_models(self, *, force_refresh: bool = False) -> list[ModelDescriptor]:
        if not force_refresh and self._cache is not None:
            return self._cache
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(f"{self._base}/api/tags")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Local Ollama may be down; cache empty list so the picker
            # renders "(no local models)" instead of spinning.
            log.warning("Ollama /api/tags failed: %s", exc)
            self._cache = []
            return []

        descriptors = [
            _row_to_descriptor(row) for row in payload.get("models") or []
        ]
        self._cache = descriptors
        return descriptors

    def caching_style(self, model_id: str) -> CachingStyle:
        # Ollama doesn't cache server-side via the OpenAI-compat shim.
        return "none"

    def count_tokens(self, text: str, model_id: str) -> int:
        # Ollama hosts many model families (llama, mistral, qwen, ...).
        # cl100k_base is wrong for all of them in detail but close enough
        # for budgeting — and Ollama is free, so cost estimates are mostly
        # a curiosity here anyway.
        return default_token_count(text)

    def extract_usage(self, raw_response: Any, model_id: str) -> UsageMetrics:
        # OpenAI-compat shim (/v1/chat/completions) returns OpenAI-shaped
        # usage. Native /api/chat returns prompt_eval_count / eval_count
        # on a dict. Probe both.
        usage = getattr(raw_response, "usage", None)
        if usage is not None:
            return UsageMetrics(
                input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            )
        if isinstance(raw_response, dict):
            return UsageMetrics(
                input_tokens=int(raw_response.get("prompt_eval_count", 0) or 0),
                output_tokens=int(raw_response.get("eval_count", 0) or 0),
            )
        return UsageMetrics()

    def model_for_tier(self, tier, models):
        # Auto-rank doesn't apply: local models are all free, and there's
        # no objective "fast vs premium" within a single user's install.
        # The picker shows the explicit list under tier=LOCAL.
        return None


def _row_to_descriptor(row: dict) -> ModelDescriptor:
    name = str(row.get("name") or row.get("model") or "")
    details = row.get("details") or {}
    family = str(details.get("family") or "").lower()
    capabilities: set[Capability] = set()
    # Vision models tend to have "vision" or "llava" in the family. Not
    # comprehensive but better than nothing for the picker hint.
    if any(token in family for token in ("vision", "llava", "vlm")):
        capabilities.add(Capability.VISION)
    return ModelDescriptor(
        id=name,
        display_name=name,
        provider="ollama",
        # Ollama doesn't publish a per-model context window via /api/tags;
        # the user would need to /api/show each model. Leave 0 — the
        # picker can show "unknown" when 0.
        context_window=0,
        tier=CapabilityTier.LOCAL,
        capabilities=capabilities,
    )
