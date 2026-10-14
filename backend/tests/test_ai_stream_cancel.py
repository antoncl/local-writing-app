"""`stream_ndjson_until_disconnect` — the disconnect-aware async body wrapper
that drives a sync ndjson generator and closes it on EVERY exit (#1570)."""

from __future__ import annotations

import asyncio
import contextlib
import unittest

from app.routers.ai import stream_ndjson_until_disconnect


class _FakeRequest:
    """A `starlette.requests.Request` stand-in: `is_disconnected()` returns
    False for the first `disconnect_after` polls, then True."""

    def __init__(self, disconnect_after: int | None) -> None:
        self._disconnect_after = disconnect_after
        self.polls = 0

    async def is_disconnected(self) -> bool:
        self.polls += 1
        if self._disconnect_after is None:
            return False
        return self.polls > self._disconnect_after


def _fake_sync_lines(lines: list[str], closed: list[bool]):
    """A sync generator that yields `lines` and records `.close()` (via the
    GeneratorExit that fires its `finally`) into `closed`."""
    try:
        yield from lines
    finally:
        closed.append(True)


async def _drain(gen) -> list[str]:
    return [line async for line in gen]


class StreamNdjsonUntilDisconnectTests(unittest.TestCase):
    def test_stops_and_closes_the_generator_on_disconnect(self):
        closed: list[bool] = []
        lines = _fake_sync_lines(["a\n", "b\n", "c\n", "d\n"], closed)
        request = _FakeRequest(disconnect_after=2)

        out = asyncio.run(
            _drain(stream_ndjson_until_disconnect(lines, request))
        )

        self.assertEqual(out, ["a\n", "b\n"])
        self.assertEqual(closed, [True])

    def test_happy_path_streams_all_lines_then_closes(self):
        closed: list[bool] = []
        lines = _fake_sync_lines(["a\n", "b\n", "c\n"], closed)
        request = _FakeRequest(disconnect_after=None)

        out = asyncio.run(
            _drain(stream_ndjson_until_disconnect(lines, request))
        )

        self.assertEqual(out, ["a\n", "b\n", "c\n"])
        self.assertEqual(closed, [True])


class ClosingStreamingResponseTests(unittest.TestCase):
    """#2482: on a client disconnect Starlette stops pulling from the body iterator
    but never closes it, so the provider teardown in its `finally` waited for
    garbage collection while Ollama kept generating. The response must close the
    iterator before it returns."""

    def _run(self, send_fails_after: int | None) -> tuple[list[str], list[bool]]:
        from app.routers.ai import ClosingStreamingResponse

        closed: list[bool] = []
        sent: list[str] = []

        async def body():
            try:
                for chunk in ["a\n", "b\n", "c\n", "d\n"]:
                    yield chunk
            finally:
                closed.append(True)

        async def receive():
            await asyncio.sleep(3600)  # no disconnect message: the send is what fails
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                if send_fails_after is not None and len(sent) >= send_fails_after:
                    raise OSError("client went away")
                sent.append(message["body"].decode())

        async def go():
            response = ClosingStreamingResponse(body(), media_type="application/x-ndjson")
            scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}}
            # Starlette wraps the failed send (ClientDisconnect, or an exception group).
            with contextlib.suppress(Exception):
                await response(scope, receive, send)
            # Checked BEFORE the event loop can garbage-collect the generator.
            return list(closed)

        closed_at_return = asyncio.run(go())
        return sent, closed_at_return

    def test_a_failed_send_closes_the_body_iterator_immediately(self):
        sent, closed = self._run(send_fails_after=1)
        self.assertEqual(sent, ["a\n"])
        self.assertEqual(closed, [True])

    def test_a_normal_end_still_streams_everything(self):
        sent, closed = self._run(send_fails_after=None)
        self.assertEqual(sent, ["a\n", "b\n", "c\n", "d\n"])
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
