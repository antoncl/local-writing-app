"""Ollama profile — local-only models discovered via the host's `/api/tags`.

Per [docs/ai-model-selection.md](../../../../../docs/ai-model-selection.md):
all Ollama models tier=LOCAL; no auto-rank since everything is free.
Picker just lists what's installed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import httpx

from app.services.ai.profiles.base import (
    Capability,
    CapabilityTier,
    ModelDescriptor,
    UsageMetrics,
    default_token_count,
)
from app.services.ai.profiles.cache_strategy import NO_CACHE, CacheStrategy
from app.services.ai.profiles.openai_compatible import OpenAICompatibleProfile

if TYPE_CHECKING:
    from app.services.machine_settings import MachineSettings

log = logging.getLogger(__name__)

# Fallback when the machine hasn't set a custom Ollama host — the daemon's
# default bind address.
_DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


class OllamaProfile(OpenAICompatibleProfile):
    name = "ollama"
    display_name = "Ollama"
    live_catalog = True  # /api/tags is the authoritative local list.

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

    @classmethod
    def from_settings(cls, settings: MachineSettings) -> OllamaProfile:
        return cls(host=settings.providers.ollama_host or _DEFAULT_OLLAMA_HOST)

    def _chat_base_url(self) -> str:
        # The OpenAI-compat shim lives at /v1 on the native host.
        return f"{self._base}/v1"

    def _chat_api_key(self) -> str:
        # Ollama needs no key; the SDK still wants a non-empty placeholder.
        return "ollama"

    async def list_models(self, *, force_refresh: bool = False) -> list[ModelDescriptor]:
        if not force_refresh and self._cache is not None:
            return self._cache
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(f"{self._base}/api/tags")
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("models") or []
                # /api/tags carries no context window or capability data — that
                # lives in /api/show, one POST per model. Fan them out
                # concurrently; the result is cached in self._cache, so this
                # cost is paid once per catalogue refresh, not on every list.
                shows = await asyncio.gather(
                    *(self._fetch_show(client, _row_name(row)) for row in rows)
                )
        except (httpx.HTTPError, ValueError) as exc:
            # Local Ollama may be down; cache empty list so the picker
            # renders "(no local models)" instead of spinning.
            log.warning("Ollama /api/tags failed: %s", exc)
            self._cache = []
            return []

        descriptors = [
            _row_to_descriptor(row, show)
            for row, show in zip(rows, shows, strict=True)
        ]
        self._cache = descriptors
        return descriptors

    async def _fetch_show(
        self, client: httpx.AsyncClient, name: str
    ) -> dict | None:
        """Fetch `/api/show` metadata for one model, or None if unavailable.

        `/api/show` reads GGUF metadata only — it does not load the model into
        VRAM — so it's cheap. A per-model failure degrades gracefully to a
        descriptor with `context_window=0` rather than failing the whole list.
        """
        if not name:
            return None
        try:
            response = await client.post(
                f"{self._base}/api/show", json={"model": name}
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.debug("Ollama /api/show failed for %s: %s", name, exc)
            return None
        return payload if isinstance(payload, dict) else None

    def ping_host(
        self, *, timeout: float = 4.0, transport: httpx.BaseTransport | None = None
    ) -> tuple[bool, str | None, str | None]:
        """Model-less reachability check — returns (reachable, version, error).

        Hits the native `/api/version` (no model, no key), so it answers the
        firewall/connectivity question — "can this machine reach the daemon?" —
        independent of whether any model has been pulled (#1380). `transport` is
        for tests to inject a mock; production leaves it None.
        """
        try:
            with httpx.Client(timeout=timeout, transport=transport) as client:
                response = client.get(f"{self._base}/api/version")
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            return False, None, f"Host answered with HTTP {exc.response.status_code}."
        except httpx.HTTPError:
            # Connect refused / DNS / timeout — the firewall/address case.
            return (
                False,
                None,
                f"Couldn't reach {self._base} — check the host is running and "
                "reachable (address, port, firewall).",
            )
        except ValueError:
            # Reached something on that address, but it didn't answer like Ollama.
            return True, None, "Reached the host, but it didn't respond like Ollama."
        if not isinstance(payload, dict):
            # Valid JSON, but not Ollama's `{"version": ...}` shape.
            return True, None, "Reached the host, but it didn't respond like Ollama."
        version = str(payload.get("version") or "") or None
        return True, version, None

    def cache_strategy(self, model_id: str) -> CacheStrategy:
        # Ollama doesn't cache server-side via the OpenAI-compat shim.
        return NO_CACHE

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


def _row_name(row: dict) -> str:
    return str(row.get("name") or row.get("model") or "")


def _row_to_descriptor(row: dict, show: dict | None = None) -> ModelDescriptor:
    name = _row_name(row)
    context_window = _context_length_from_show(show) if show else 0
    capabilities = _capabilities_from_show(show) if show else set()
    # The family-name vision guess is additive: it's the sole signal when
    # /api/show is absent (server race, or an older Ollama without a
    # capabilities list), and it never drops a VISION hint we'd have shown
    # before /api/show existed — even when /api/show answered with other
    # capabilities. Not comprehensive, but better than nothing.
    family = str((row.get("details") or {}).get("family") or "").lower()
    if any(token in family for token in ("vision", "llava", "vlm")):
        capabilities = capabilities | {Capability.VISION}
    return ModelDescriptor(
        id=name,
        display_name=name,
        provider="ollama",
        context_window=context_window,
        tier=CapabilityTier.LOCAL,
        capabilities=capabilities,
    )


def _context_length_from_show(show: dict) -> int:
    """Read the model's trained context length from `/api/show` `model_info`.

    The key is architecture-prefixed (`llama.context_length`,
    `qwen2.context_length`, ...), so resolve it via `general.architecture`
    rather than hardcoding a family. Falls back to scanning for any
    `*.context_length` key, then 0 when absent.
    """
    info = show.get("model_info")
    if not isinstance(info, dict):
        return 0
    arch = str(info.get("general.architecture") or "")
    keys = [f"{arch}.context_length"] if arch else []
    keys += [
        key
        for key in info
        if isinstance(key, str) and key.endswith(".context_length")
    ]
    for key in keys:
        value = info.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return 0


# Ollama's /api/show `capabilities` we surface as picker flags. `completion`
# and `embedding` carry no Capability; Ollama caches nothing, so CACHING is
# never added.
_SHOW_CAPABILITY_MAP: dict[str, Capability] = {
    "vision": Capability.VISION,
    "tools": Capability.TOOLS,
    "thinking": Capability.THINKING,
}


def _capabilities_from_show(show: dict) -> set[Capability]:
    """Map Ollama's /api/show `capabilities` list onto our Capability flags."""
    caps: set[Capability] = set()
    for raw in show.get("capabilities") or []:
        mapped = _SHOW_CAPABILITY_MAP.get(str(raw).lower())
        if mapped is not None:
            caps.add(mapped)
    return caps
