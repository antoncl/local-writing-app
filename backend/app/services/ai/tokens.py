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

from app.services.ai.profiles import ModelDescriptor
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


def estimate_input_cost(
    tokens: int,
    descriptor: ModelDescriptor | None,
) -> float:
    """Pre-send input-only USD cost. Output cost depends on the response
    size and isn't known until the model replies — use `compute_cost`
    on the actuals for that.

    Returns 0.0 when pricing is unknown (Ollama, or live discovery
    didn't supply prices).
    """

    if descriptor is None or descriptor.cost_in_per_mtok is None:
        return 0.0
    if tokens <= 0:
        return 0.0
    return tokens * descriptor.cost_in_per_mtok / 1_000_000


__all__ = [
    "count_tokens",
    "count_tokens_per_block",
    "descriptor_for",
    "estimate_input_cost",
]
