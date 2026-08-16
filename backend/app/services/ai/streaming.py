"""Provider stream → NDJSON transform (#178 slice 5).

`transform_provider_events_to_ndjson` adapts the dispatch layer's StreamEvents
into the NDJSON line protocol the streaming endpoints emit. Extracted from the
HTTP layer; the endpoints pre-fetch the pricing descriptor so this sync
generator can price the terminal `done` line without an await mid-stream.

Line protocol (one JSON object per line):
  {"type":"delta","text":"..."}                            (zero or more)
  {"type":"thinking","text":"..."}                         (zero or more)
  {"type":"done","provider":"...","model":"...","latency_ms":N,
   "stop_reason":"...","truncated":bool,"policy":"...", ...extra_done}  (one, on success)
  {"type":"error","error":"...","provider":"...","model":"...",
   "latency_ms":N,"policy":"..."}                          (one, on failure)
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from app.services.ai import providers as ai_providers

if TYPE_CHECKING:
    from app.services.ai.profiles import ModelDescriptor


def _ndjson(line: dict[str, Any]) -> str:
    return json.dumps(line, ensure_ascii=False) + "\n"


def _done_line(
    ev: ai_providers.StreamDone,
    *,
    policy: str,
    extra_done: dict[str, Any],
    descriptor: ModelDescriptor | None,
) -> dict[str, Any]:
    """Assemble the terminal `done` object: base fields + `extra_done`, plus
    `usage` when the stream reported it and `cost_usd` when a pricing
    descriptor is available to price that usage.
    """
    line: dict[str, Any] = {
        "type": "done",
        "provider": ev.provider,
        "model": ev.model,
        "latency_ms": ev.latency_ms,
        "stop_reason": ev.stop_reason,
        "truncated": ev.truncated,
        "policy": policy,
        **extra_done,
    }
    if ev.usage is not None:
        line["usage"] = {
            "input_tokens": ev.usage.input_tokens,
            "cached_input_tokens": ev.usage.cached_input_tokens,
            "cache_write_tokens": ev.usage.cache_write_tokens,
            "output_tokens": ev.usage.output_tokens,
        }
        if descriptor is not None:
            from app.services.ai.profiles import compute_cost
            line["cost_usd"] = compute_cost(ev.usage, descriptor)
    return line


def transform_provider_events_to_ndjson(
    events: Iterator[ai_providers.StreamEvent],
    *,
    policy: str,
    extra_done: dict[str, Any] | None = None,
    descriptor: ModelDescriptor | None = None,
) -> Iterator[str]:
    """Adapt provider events to NDJSON lines. Suppresses empty deltas.

    When `descriptor` is provided and the terminal StreamDone carries
    usage, the `done` line includes `usage` + `cost_usd`. The descriptor
    is pre-fetched by the endpoint so this sync generator can compute
    cost without an await.
    """
    extra_done = extra_done or {}
    try:
        for ev in events:
            if isinstance(ev, ai_providers.StreamDelta):
                if ev.text:
                    yield _ndjson({"type": "delta", "text": ev.text})
            elif isinstance(ev, ai_providers.StreamThinking):
                if ev.text:
                    yield _ndjson({"type": "thinking", "text": ev.text})
            elif isinstance(ev, ai_providers.StreamDone):
                yield _ndjson(_done_line(
                    ev, policy=policy, extra_done=extra_done, descriptor=descriptor
                ))
            elif isinstance(ev, ai_providers.StreamError):
                yield _ndjson({
                    "type": "error",
                    "error": ev.error,
                    "provider": ev.provider,
                    "model": ev.model,
                    "latency_ms": ev.latency_ms,
                    "policy": policy,
                })
    except Exception as exc:  # noqa: BLE001 — last-resort guard so the stream always terminates
        yield _ndjson({
            "type": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "provider": "",
            "model": "",
            "latency_ms": 0,
            "policy": policy,
        })
