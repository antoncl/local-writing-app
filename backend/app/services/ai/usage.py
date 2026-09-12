"""Usage → wire + cost translation (#178 slice 3).

Convert a dispatch-layer `UsageMetrics` into the wire-format `ChatUsage` the API
returns, and price it in USD from the model's descriptor. Extracted from the HTTP
layer as a free async function, matching the `services/ai/` style.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models import ChatUsage
from app.services.ai import tokens as ai_tokens
from app.services.ai.profiles import ModelDescriptor, UsageMetrics, compute_cost

if TYPE_CHECKING:
    from app.services.machine_settings import MachineSettings


def chat_usage_from_metrics(usage: UsageMetrics) -> ChatUsage:
    """The one dispatch-layer → wire mapping. `UsageMetrics` carries the
    1h/5m cache-write split; `ChatUsage` (the API, the transcript, the
    invocation ledger) carries the total only, so the split is folded here
    and nowhere else."""
    return ChatUsage(
        input_tokens=usage.input_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        output_tokens=usage.output_tokens,
    )


async def translate_usage_to_cost(
    usage: UsageMetrics | None,
    *,
    provider: str,
    model: str,
    settings: MachineSettings,
    manual_price_in_usd_per_mtok: float | None = None,
    manual_price_out_usd_per_mtok: float | None = None,
) -> tuple[ChatUsage | None, float | None]:
    """Convert dispatch-layer UsageMetrics + a (provider, model) lookup into
    wire-format ChatUsage and USD cost. Returns (None, None) when usage is
    missing; cost stays None when pricing isn't known.

    An author-set per-assistant price (ADR-0083 Amendment 1) is applied as a
    FILL: it prices the call only when neither the oracle nor the baked seed
    does, so the oracle auto-heals once it lists the model."""
    if usage is None:
        return None, None
    if not provider or not model:
        return chat_usage_from_metrics(usage), None
    descriptor = await ai_tokens.priced_descriptor_for(
        provider=provider,
        model=model,
        settings=settings,
        manual_in=manual_price_in_usd_per_mtok,
        manual_out=manual_price_out_usd_per_mtok,
    )
    return price_usage(usage, descriptor)


def price_usage(
    usage: UsageMetrics | None, descriptor: ModelDescriptor | None
) -> tuple[ChatUsage | None, float | None]:
    """The one pricing policy, sync, for a caller that already holds the
    descriptor (the stream pre-fetches it so its sync generator can price the
    terminal event without an await): no usage → nothing; no descriptor → the
    usage, unpriced (None, never a fabricated 0.0 — #697); else `compute_cost`
    (an explicit 0-rate descriptor is a KNOWN free call and prices as 0.0)."""
    if usage is None:
        return None, None
    wire_usage = chat_usage_from_metrics(usage)
    if descriptor is None:
        return wire_usage, None
    return wire_usage, compute_cost(usage, descriptor)
