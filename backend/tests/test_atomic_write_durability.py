"""Durable atomic writes (#480).

The temp-then-rename primitive never lets a reader see a torn file, but until
#480 it fsynced neither the contents before the rename nor the directory after
it — so an acknowledged save could still be lost inside the OS write-back window
on a power cut. These pin two things a mutation can't sneak past: the bytes land
correctly (real fsync, no mock), and fsync is actually *called* on a durable
write and *skipped* on the one rebuildable-cache opt-out (#476). Removing either
fsync fails the call-count assertions; making the cache write durable fails the
opt-out one.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services.atomic_io import atomic_write_bytes, atomic_write_text


class AtomicWriteDurabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ----- content correctness (real fsync, no mock) -----------------------

    def test_text_write_lands_and_leaves_no_temp(self) -> None:
        target = self.dir / "sub" / "scene.md"  # parent created on demand
        atomic_write_text(target, "hello — prose")

        self.assertEqual(target.read_text(encoding="utf-8"), "hello — prose")
        # The temp file is renamed onto the target, so nothing else is left behind.
        self.assertEqual([p.name for p in target.parent.iterdir()], ["scene.md"])

    def test_text_write_overwrites_existing(self) -> None:
        target = self.dir / "note.md"
        atomic_write_text(target, "first")
        atomic_write_text(target, "second")

        self.assertEqual(target.read_text(encoding="utf-8"), "second")
        self.assertEqual([p.name for p in target.parent.iterdir()], ["note.md"])

    def test_bytes_write_lands_verbatim(self) -> None:
        target = self.dir / "restore.md"
        payload = b"\xef\xbb\xbf---\nid: x\n---\r\nbody\x00"  # BOM + CRLF + NUL
        atomic_write_bytes(target, payload)

        self.assertEqual(target.read_bytes(), payload)

    # ----- fsync is actually invoked (the regression guard) ----------------

    def _expected_fsync_calls(self) -> int:
        # One for the file contents, plus one for the parent directory on POSIX
        # (Windows has no directory fd — `_fsync_dir` is a no-op there).
        return 2 if os.name == "posix" else 1

    def test_durable_text_fsyncs_contents_and_dir(self) -> None:
        target = self.dir / "scene.md"
        with patch("app.services.atomic_io.os.fsync") as fsync:
            atomic_write_text(target, "durable")
        self.assertEqual(fsync.call_count, self._expected_fsync_calls())

    def test_durable_bytes_fsyncs_contents_and_dir(self) -> None:
        target = self.dir / "restore.md"
        with patch("app.services.atomic_io.os.fsync") as fsync:
            atomic_write_bytes(target, b"durable")
        self.assertEqual(fsync.call_count, self._expected_fsync_calls())

    def test_non_durable_text_skips_fsync(self) -> None:
        # The node-index snapshot opt-out (#476): rebuildable cache must not pay
        # the fsync every user file does.
        target = self.dir / "index.snapshot.json"
        with patch("app.services.atomic_io.os.fsync") as fsync:
            atomic_write_text(target, "cache", durable=False)
        fsync.assert_not_called()
        # …and still writes correctly.
        self.assertEqual(target.read_text(encoding="utf-8"), "cache")


if __name__ == "__main__":
    unittest.main()
