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

import contextlib
import json
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from app.models import ChatUsage
from app.services.ai import providers as ai_providers
from app.services.ai.usage import chat_usage_from_metrics

if TYPE_CHECKING:
    from app.services.ai.profiles import ModelDescriptor


def _ndjson(line: dict[str, Any]) -> str:
    return json.dumps(line, ensure_ascii=False) + "\n"


def _price_done(
    ev: ai_providers.StreamDone, descriptor: ModelDescriptor | None
) -> tuple[ChatUsage | None, float | None]:
    """The terminal event's usage in wire shape, and its USD cost when a
    pricing descriptor is available. Computed ONCE per stream and shared by
    the `done` line and the `on_done` ledger hook, so the two can't disagree."""
    if ev.usage is None:
        return None, None
    usage = chat_usage_from_metrics(ev.usage)
    if descriptor is None:
        return usage, None
    from app.services.ai.profiles import compute_cost

    return usage, compute_cost(ev.usage, descriptor)


def _done_line(
    ev: ai_providers.StreamDone,
    *,
    policy: str,
    extra_done: dict[str, Any],
    usage: ChatUsage | None,
    cost_usd: float | None,
) -> dict[str, Any]:
    """Assemble the terminal `done` object: base fields + `extra_done`, plus
    `usage` when the stream reported it and `cost_usd` when it was priced.
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
    if usage is not None:
        line["usage"] = usage.model_dump()
        if cost_usd is not None:
            line["cost_usd"] = cost_usd
    return line


def _finish(
    ev: ai_providers.StreamDone,
    *,
    policy: str,
    extra_done: dict[str, Any],
    descriptor: ModelDescriptor | None,
    on_done: Callable[[ai_providers.StreamDone, ChatUsage | None, float | None], None] | None,
) -> str:
    """Price the terminal event once, hand it to the ledger hook, then render
    the `done` line — in that order, so the row exists before the client sees
    `done`. A failing hook never disrupts the stream (mirrors `on_error`)."""
    usage, cost_usd = _price_done(ev, descriptor)
    if on_done is not None:
        with contextlib.suppress(Exception):
            on_done(ev, usage, cost_usd)
    return _ndjson(
        _done_line(ev, policy=policy, extra_done=extra_done, usage=usage, cost_usd=cost_usd)
    )


def _error_line(ev: ai_providers.StreamError, *, policy: str) -> dict[str, Any]:
    """The terminal `error` object. Carries only the user-facing `error`; the
    private `detail` is recorded to errors.log by the endpoint's `on_error` hook
    (#1601), never serialized onto the wire."""
    return {
        "type": "error",
        "error": ev.error,
        "provider": ev.provider,
        "model": ev.model,
        "latency_ms": ev.latency_ms,
        "policy": policy,
    }


def transform_provider_events_to_ndjson(
    events: Iterator[ai_providers.StreamEvent],
    *,
    policy: str,
    extra_done: dict[str, Any] | None = None,
    descriptor: ModelDescriptor | None = None,
    on_error: Callable[[ai_providers.StreamError], None] | None = None,
    on_done: Callable[[ai_providers.StreamDone, ChatUsage | None, float | None], None]
    | None = None,
) -> Iterator[str]:
    """Adapt provider events to NDJSON lines. Suppresses empty deltas.

    When `descriptor` is provided and the terminal StreamDone carries
    usage, the `done` line includes `usage` + `cost_usd`. The descriptor
    is pre-fetched by the endpoint so this sync generator can compute
    cost without an await.

    `on_error`, when given, is called with each `StreamError` before its line is
    emitted — the endpoint uses it to record the failure (message + the private
    `detail`) to the project's errors.log (#1601). The wire line carries only the
    user-facing `error`, never `detail`.

    `on_done`, when given, is called with the terminal `StreamDone` plus the
    priced usage BEFORE the `done` line is emitted — the endpoint uses it to
    record the turn's own `ai_invocations` row (#1877), so the row exists by
    the time the client sees `done` and its next read of the chat already
    projects it. Like `on_error`, a failing hook never disrupts the stream.
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
                yield _finish(
                    ev, policy=policy, extra_done=extra_done, descriptor=descriptor, on_done=on_done
                )
            elif isinstance(ev, ai_providers.StreamError):
                if on_error is not None:
                    # Recording a failure must never disrupt the stream.
                    with contextlib.suppress(Exception):
                        on_error(ev)
                yield _ndjson(_error_line(ev, policy=policy))
    except Exception as exc:  # noqa: BLE001 — last-resort guard so the stream always terminates
        yield _ndjson({
            "type": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "provider": "",
            "model": "",
            "latency_ms": 0,
            "policy": policy,
        })
