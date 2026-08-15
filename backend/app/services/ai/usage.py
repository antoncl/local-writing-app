"""Usage → wire + cost translation (#178 slice 3).

Convert a dispatch-layer `UsageMetrics` into the wire-format `ChatUsage` the API
returns, and price it in USD from the model's descriptor. Extracted from the HTTP
layer as a free async function, matching the `services/ai/` style.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models import ChatUsage
from app.services.ai import tokens as ai_tokens
from app.services.ai.profiles import UsageMetrics, compute_cost

if TYPE_CHECKING:
    from app.services.machine_settings import MachineSettings


async def translate_usage_to_cost(
    usage: UsageMetrics | None,
    *,
    provider: str,
    model: str,
    settings: MachineSettings,
) -> tuple[ChatUsage | None, float | None]:
    """Convert dispatch-layer UsageMetrics + a (provider, model) lookup into
    wire-format ChatUsage and USD cost. Returns (None, None) when usage is
    missing; cost stays None when pricing isn't known."""
    if usage is None:
        return None, None
    wire_usage = ChatUsage(
        input_tokens=usage.input_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        output_tokens=usage.output_tokens,
    )
    if not provider or not model:
        return wire_usage, None
    descriptor = await ai_tokens.descriptor_for(provider=provider, model=model, settings=settings)
    if descriptor is None:
        return wire_usage, None
    cost = compute_cost(usage, descriptor)
    return wire_usage, cost
