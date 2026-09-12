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
from app.services.ai.usage import price_usage

if TYPE_CHECKING:
    from app.services.ai.profiles import ModelDescriptor


def _ndjson(line: dict[str, Any]) -> str:
    return json.dumps(line, ensure_ascii=False) + "\n"


OnDone = Callable[
    [ai_providers.StreamDone, ChatUsage | None, float | None], dict[str, Any] | None
]


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
    on_done: OnDone | None,
) -> str:
    """Price the terminal event once, hand it to the finaliser, then render
    the `done` line — in that order, so the ledger row exists before the
    client sees `done`, and whatever the finaliser returns (the chat's new
    `cost_usd_total`, #1877) rides on that same line: the one number the
    client shows, delivered on the event that changed it. A failing finaliser
    never disrupts the stream (mirrors `on_error`)."""
    usage, cost_usd = price_usage(ev.usage, descriptor)
    merged = dict(extra_done)
    if on_done is not None:
        with contextlib.suppress(Exception):
            merged.update(on_done(ev, usage, cost_usd) or {})
    return _ndjson(
        _done_line(ev, policy=policy, extra_done=merged, usage=usage, cost_usd=cost_usd)
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
    on_done: OnDone | None = None,
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

    `on_done`, when given, is the turn's finaliser: called with the terminal
    `StreamDone` plus the priced usage BEFORE the `done` line is emitted, and
    whatever dict it returns is merged onto that line. The endpoint uses it to
    record the turn's own `ai_invocations` row and hand back the chat's new
    `cost_usd_total` (#1877), so the client learns the total on the event
    that changed it. Like `on_error`, a failing hook never disrupts the stream.
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
