"""The Windows connection-reset filter drops one benign case and nothing else (#2576)."""

from __future__ import annotations

import asyncio
import logging
import types
from asyncio import proactor_events

import pytest

from app.services import connection_reset_filter

_CALL_CONNECTION_LOST = proactor_events._ProactorBasePipeTransport._call_connection_lost


def _context(loop: asyncio.AbstractEventLoop, func, exc: BaseException) -> dict:
    # A bound method on a stand-in transport: the filter checks `__func__`, the
    # same identity a real `_ProactorSocketTransport` callback carries.
    handle = asyncio.Handle(types.MethodType(func, object()), (), loop)
    return {"message": "Exception in callback", "exception": exc, "handle": handle}


def _other_callback(self) -> None:
    pass


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def test_matches_reset_from_call_connection_lost(loop) -> None:
    ctx = _context(loop, _CALL_CONNECTION_LOST, ConnectionResetError(10054, "reset"))
    assert connection_reset_filter.is_benign_connection_reset(ctx)


@pytest.mark.parametrize(
    ("func", "exc"),
    [
        # The right error from any other callback is a real problem.
        (_other_callback, ConnectionResetError(10054, "reset")),
        # Any other error from the right callback is a real problem.
        (_CALL_CONNECTION_LOST, OSError(10038, "not a socket")),
        (_CALL_CONNECTION_LOST, RuntimeError("boom")),
    ],
)
def test_does_not_match_anything_else(loop, func, exc) -> None:
    assert not connection_reset_filter.is_benign_connection_reset(_context(loop, func, exc))


def test_context_without_handle_or_exception_is_not_matched() -> None:
    assert not connection_reset_filter.is_benign_connection_reset({"message": "x"})
    assert not connection_reset_filter.is_benign_connection_reset(
        {"message": "x", "exception": ConnectionResetError()}
    )


def test_installed_handler_drops_benign_and_forwards_the_rest(loop, monkeypatch, caplog) -> None:
    monkeypatch.setattr(connection_reset_filter.sys, "platform", "win32")
    forwarded: list[dict] = []
    loop.set_exception_handler(lambda _loop, ctx: forwarded.append(ctx))
    connection_reset_filter.install(loop)

    benign = _context(loop, _CALL_CONNECTION_LOST, ConnectionResetError(10054, "reset"))
    real = _context(loop, _other_callback, ConnectionResetError(10054, "reset"))
    with caplog.at_level(logging.DEBUG, logger=connection_reset_filter.__name__):
        loop.call_exception_handler(benign)
        loop.call_exception_handler(real)

    assert forwarded == [real]
    # Quieted, not erased: the dropped event is still on the DEBUG log.
    assert any("reset the connection" in r.getMessage() for r in caplog.records)


def test_installed_handler_falls_back_to_default(loop, monkeypatch) -> None:
    monkeypatch.setattr(connection_reset_filter.sys, "platform", "win32")
    seen: list[dict] = []
    monkeypatch.setattr(loop, "default_exception_handler", seen.append)
    connection_reset_filter.install(loop)

    real = _context(loop, _other_callback, RuntimeError("boom"))
    loop.call_exception_handler(real)
    assert seen == [real]


def test_install_is_a_noop_off_windows(loop, monkeypatch) -> None:
    monkeypatch.setattr(connection_reset_filter.sys, "platform", "linux")
    connection_reset_filter.install(loop)
    assert loop.get_exception_handler() is None


def test_missing_stdlib_callback_switches_the_filter_off(loop, monkeypatch) -> None:
    # A future Python renaming the private callback must not match everything
    # (None is None) nor break startup: the filter just turns itself off.
    monkeypatch.setattr(connection_reset_filter.sys, "platform", "win32")
    monkeypatch.setattr(connection_reset_filter, "_CALL_CONNECTION_LOST", None)
    ctx = {"message": "x", "exception": ConnectionResetError(), "handle": object()}
    assert not connection_reset_filter.is_benign_connection_reset(ctx)
    connection_reset_filter.install(loop)
    assert loop.get_exception_handler() is None


def test_uninstall_restores_the_previous_handler(loop, monkeypatch) -> None:
    monkeypatch.setattr(connection_reset_filter.sys, "platform", "win32")

    def previous(_loop, _ctx):
        pass

    loop.set_exception_handler(previous)
    uninstall = connection_reset_filter.install(loop)
    assert loop.get_exception_handler() is not previous
    uninstall()
    assert loop.get_exception_handler() is previous


def test_app_lifespan_installs_and_removes_the_filter(monkeypatch) -> None:
    from app import main

    monkeypatch.setattr(connection_reset_filter.sys, "platform", "win32")
    monkeypatch.setattr(main, "migrate_assistant_tags_once", lambda: None)
    monkeypatch.setattr(main.node_index_gate, "flush", lambda: None)

    async def run() -> None:
        loop = asyncio.get_running_loop()
        benign = _context(loop, _CALL_CONNECTION_LOST, ConnectionResetError(10054, "reset"))
        reached: list[dict] = []
        loop.set_exception_handler(lambda _loop, ctx: reached.append(ctx))
        async with main.lifespan(main.app):
            loop.call_exception_handler(benign)
            assert reached == []
        loop.call_exception_handler(benign)
        assert reached == [benign]

    asyncio.run(run())
