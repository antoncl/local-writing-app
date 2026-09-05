"""Token counting + cost-estimation facade.

Single entry point for callers with a (provider, model) pair that need
to estimate token counts, look up the pricing descriptor, or compute
an input-side cost estimate. Wraps the registry + ProviderProfile so
callers don't have to import the registry plumbing themselves.

For actuals (response → cost), call `profile.extract_usage` and
`compute_cost` directly from the dispatch layer — those don't need
this facade.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.ai.profiles import ModelDescriptor
from app.services.ai.profiles.base import _CACHE_WRITE_MULTIPLIER, CapabilityTier
from app.services.ai.profiles.registry import profile_for
from app.services.machine_settings import MachineSettings


def count_tokens(
    text: str,
    *,
    provider: str,
    model: str,
    settings: MachineSettings,
) -> int:
    """Estimate tokens for `text` under the given provider+model.

    Returns 0 for empty text or unknown provider — callers that care
    about provider validation should check upstream.
    """

    if not text or not provider:
        return 0
    try:
        profile = profile_for(provider, settings)
    except ValueError:
        return 0
    return profile.count_tokens(text, model)


def count_tokens_per_block(
    blocks: list[str],
    *,
    provider: str,
    model: str,
    settings: MachineSettings,
) -> list[int]:
    """Per-block token counts — powers the cache-strip display where the
    UI shows `Sys 2.1k · Lore 5.4k · Tail 0.8k`. Output length matches
    input length; unknown providers return all-zeros.
    """

    if not provider:
        return [0] * len(blocks)
    try:
        profile = profile_for(provider, settings)
    except ValueError:
        return [0] * len(blocks)
    return [profile.count_tokens(b or "", model) for b in blocks]


async def descriptor_for(
    *,
    provider: str,
    model: str,
    settings: MachineSettings,
) -> ModelDescriptor | None:
    """Look up the pricing descriptor for a (provider, model).

    Async because `list_models` may hit the network on cold start;
    cached per-profile-instance thereafter. Returns None when the
    provider is unknown or the model id isn't in the catalogue.
    """

    if not provider or not model:
        return None
    try:
        profile = profile_for(provider, settings)
    except ValueError:
        return None
    descriptors = await profile.list_models()
    return next((d for d in descriptors if d.id == model), None)


def apply_manual_fill(
    descriptor: ModelDescriptor | None,
    *,
    provider: str,
    model: str,
    manual_in: float | None,
    manual_out: float | None,
) -> ModelDescriptor | None:
    """Fill an author-set price into the pricing descriptor when nothing else
    prices the model (ADR-0083 Amendment 1 — fill semantics: oracle → baked →
    manual).

    No-op when no manual price is set, or when the descriptor already carries a
    price: the oracle or baked seed wins, so a manual value is a fallback that
    auto-heals the moment the oracle lists the model. When the model has no
    catalogue entry at all (e.g. a local Ollama model), synthesize a minimal
    priced descriptor so `compute_cost` can still bill the call.
    """

    if manual_in is None and manual_out is None:
        return descriptor
    already_priced = descriptor is not None and not (
        descriptor.cost_in_per_mtok is None and descriptor.cost_out_per_mtok is None
    )
    if already_priced:
        return descriptor
    if descriptor is not None:
        return replace(descriptor, cost_in_per_mtok=manual_in, cost_out_per_mtok=manual_out)
    return ModelDescriptor(
        id=model,
        display_name=model,
        provider=provider,
        context_window=0,
        tier=CapabilityTier.BALANCED,
        cost_in_per_mtok=manual_in,
        cost_out_per_mtok=manual_out,
        verified=False,
    )


def estimate_input_cost(
    tokens: int,
    descriptor: ModelDescriptor | None,
) -> float | None:
    """Pre-send input-only USD cost. Output cost depends on the response
    size and isn't known until the model replies — use `compute_cost`
    on the actuals for that.

    Returns None when pricing is unknown (a local Ollama model, or live
    discovery didn't supply an input rate) — "cost unknown", which the
    preview surface hides rather than showing a fabricated "€0.00" (the
    display contract reserves a confident zero for a truly free call,
    #697). A known input rate with a zero-token prompt is a real 0.0.
    """

    if descriptor is None or descriptor.cost_in_per_mtok is None:
        return None
    if tokens <= 0:
        return 0.0
    return tokens * descriptor.cost_in_per_mtok / 1_000_000


def estimate_send_cost(
    stable_tokens: int,
    other_tokens: int,
    descriptor: ModelDescriptor | None,
    caches: bool,
) -> tuple[float | None, float | None]:
    """Cache-aware input-cost estimate (#1052): `(settled, first)`.

    `stable_tokens` are the cacheable prefix (the system prompt + stable lore);
    `other_tokens` are the never-cached rest (volatile lore + the conversation
    turns). On a model that caches, the stable prefix prices as a cache **read**
    on a settled repeat send (the cache is warm) and as a cache **write** on the
    first send — or after any change invalidates the prefix; everything else is
    full rate in both. When the model does not cache — or has no input price —
    both figures collapse to the flat estimate (`settled == first`), so callers
    can treat an equal pair as "no cache effect to surface". Mirrors the cache
    model `compute_cost` uses on the actuals; output cost is excluded (unknown
    pre-send), as with `estimate_input_cost`.
    """
    if descriptor is None or descriptor.cost_in_per_mtok is None:
        return None, None
    cost_in = descriptor.cost_in_per_mtok / 1_000_000
    other = other_tokens * cost_in
    if not caches:
        flat = stable_tokens * cost_in + other
        return flat, flat
    read_mult = (
        descriptor.cache_read_multiplier
        if descriptor.cache_read_multiplier is not None
        else 1.0
    )
    stable = stable_tokens * cost_in
    return stable * read_mult + other, stable * _CACHE_WRITE_MULTIPLIER + other


__all__ = [
    "apply_manual_fill",
    "count_tokens",
    "count_tokens_per_block",
    "descriptor_for",
    "estimate_input_cost",
    "estimate_send_cost",
]
