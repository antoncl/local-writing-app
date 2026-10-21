"""Drop one known-benign Windows asyncio traceback, and nothing else (#2576).

On Windows the Proactor event loop's transport calls `socket.shutdown()` from
`_ProactorBasePipeTransport._call_connection_lost` after the client has already
reset the connection (a tab reload, an HMR reconnect, an aborted fetch). Windows
answers with WinError 10054, nothing catches it, and asyncio's default handler
prints an "Exception in callback" traceback for a request that has already ended.

The filter is deliberately narrow, so it can't hide a real problem:
- it matches only a `ConnectionResetError` raised by that exact callback, checked
  by function identity rather than by the text of a repr;
- every other context goes to the previous handler (or the default) unchanged;
- a dropped event is still logged at DEBUG, so it's quieted, not erased.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from asyncio import proactor_events
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Private CPython API, so it's looked up defensively: if a future Python renames
# it, the filter switches itself off instead of breaking backend startup.
_CALL_CONNECTION_LOST = getattr(
    getattr(proactor_events, "_ProactorBasePipeTransport", None), "_call_connection_lost", None
)


def is_benign_connection_reset(context: dict[str, Any]) -> bool:
    """True only for a ConnectionResetError raised by `_call_connection_lost`."""
    if _CALL_CONNECTION_LOST is None:
        return False
    if not isinstance(context.get("exception"), ConnectionResetError):
        return False
    callback = getattr(context.get("handle"), "_callback", None)
    return getattr(callback, "__func__", None) is _CALL_CONNECTION_LOST


def install(loop: asyncio.AbstractEventLoop) -> Callable[[], None]:
    """Wrap `loop`'s exception handler with the filter; returns an undo.

    A no-op off Windows, or when the stdlib callback can't be found.
    """
    previous = loop.get_exception_handler()
    if sys.platform != "win32" or _CALL_CONNECTION_LOST is None:
        return lambda: None

    def handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        if is_benign_connection_reset(context):
            logger.debug("client reset the connection before close: %s", context["exception"])
            return
        if previous is not None:
            previous(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handler)
    return lambda: loop.set_exception_handler(previous)
