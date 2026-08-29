"""`stream_ndjson_until_disconnect` — the disconnect-aware async body wrapper
that drives a sync ndjson generator and closes it on EVERY exit (#1570)."""

from __future__ import annotations

import asyncio
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


if __name__ == "__main__":
    unittest.main()
