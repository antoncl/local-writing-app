"""Durable file log for the general server stream (#1745).

The catch-all the console used to be. Distinct from ``errors.log``
(``error_log.py``, #386/#741), which is the *curated* error record — caught
backend 500s and browser failures POSTed to ``/api/log``, one line each. This is
the *general* stream instead: uvicorn's startup/access lines, the no-auth binding
warning, ``logger.info``/``debug`` across the app, and any stray
``print``/``traceback``.

Today that stream's only sink is the console window. Once the frozen build goes
windowed (#1746, ``console=False``) there is no console, and on Windows a windowed
PyInstaller build writing to the then-``None`` ``stdout``/``stderr`` can crash. So
the product entrypoint (``app/server.main``) routes the general stream to a
rotating file under the app-data dir — the same ``config_dir()`` home
``errors.log``'s machine scope already uses — and, when the std streams are dead,
swaps in a writer that forwards to that log so nothing can crash on a ``None``
stream. The ``--reload`` dev path never calls this; its console stays as-is.

The one invariant mirrors ``errors.log``: **configuring the log must never take
down the server it was only meant to record.** A dir we cannot create or a file
we cannot open degrades to no file log, never to a failed launch.
"""

from __future__ import annotations

import atexit
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from app.services.machine_settings import config_dir

LOG_FILENAME = "app.log"

# ~2 MB per file, three rolled backups — enough to hold a bug report's worth of
# context without letting the log grow without bound on a long-lived desktop run.
_MAX_BYTES = 2_000_000
_BACKUP_COUNT = 3

_FORMATTER = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")

# Tags our own handlers so configure is idempotent by *presence* rather than a
# module-global flag — a second call (or a test) finds them and no-ops instead of
# stacking duplicate handlers on the root logger.
_MARK = "_lwa_product_log"


class _LoggerWriter:
    """A minimal text stream that forwards writes to a logger.

    Stands in for ``sys.stdout``/``sys.stderr`` when the windowed build has none,
    so a stray ``print()`` or ``traceback.print_exc()`` can never crash on a
    ``None`` stream — the write lands in the same file log instead. Line-buffered
    so one ``print`` is one record and a multi-line traceback isn't split at
    arbitrary write boundaries.
    """

    def __init__(self, log: logging.Logger, level: int) -> None:
        self._log = log
        self._level = level
        self._buffer = ""
        # Re-entrancy guard: if a handler downstream of self._log.log() fails,
        # logging.handleError writes the traceback back to sys.stderr — us — and
        # a naive re-log would drive the same failing handler again, unbounded.
        # While emitting we swallow further writes instead of recursing.
        self._emitting = False

    def _emit(self, line: str) -> None:
        if self._emitting:
            return
        self._emitting = True
        try:
            self._log.log(self._level, line)
        finally:
            self._emitting = False

    def write(self, message: str) -> int:
        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                self._emit(line)
        return len(message)

    def flush(self) -> None:
        # Emit any trailing newline-less fragment — a crash message written as
        # `sys.stderr.write("fatal: ")` right before exit would otherwise sit in
        # the buffer forever. Registered with atexit on the swap so a normal
        # (exception-driven) shutdown still drains it.
        if self._buffer:
            line, self._buffer = self._buffer, ""
            self._emit(line)

    def isatty(self) -> bool:
        return False


def _live_stream(stream: TextIO | None) -> TextIO | None:
    """The stream if it can actually be written to, else ``None``.

    A windowed PyInstaller build has ``None`` std streams; a closed stream is
    just as dead. Either way there is no real console to echo to.
    """
    if stream is None:
        return None
    if getattr(stream, "closed", False):
        return None
    return stream


def configure_product_logging() -> Path | None:
    """Attach a rotating file handler for the general stream; return the log path.

    Called from the product entrypoint (``app/server.main``), never the
    ``--reload`` dev path. Idempotent. ``errors.log`` is untouched. Returns the
    log path, or ``None`` if the file log could not be set up (the crash-safety
    stream swap is still applied first, so a windowed build stays safe even then).
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, _MARK, False):
            return config_dir() / LOG_FILENAME

    # Decide console echo from the *original* stdout, before any swap, so we
    # never point a StreamHandler at the _LoggerWriter below (that would loop:
    # write -> log -> handler -> write -> ...).
    console = _live_stream(sys.stdout)

    # Windowed-build safety: forward stray writes to a logger so print()/traceback
    # can't raise on a None/closed stream. Done first and unconditionally of the
    # file-handler setup, so crash-safety never depends on a writable app-data dir.
    # atexit drains any trailing newline-less fragment (a crash message) on a
    # normal/exception-driven shutdown.
    if console is None:
        writer = _LoggerWriter(logging.getLogger("stdout"), logging.INFO)
        sys.stdout = writer  # type: ignore[assignment]
        atexit.register(writer.flush)
    if _live_stream(sys.stderr) is None:
        writer = _LoggerWriter(logging.getLogger("stderr"), logging.ERROR)
        sys.stderr = writer  # type: ignore[assignment]
        atexit.register(writer.flush)

    try:
        directory = config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / LOG_FILENAME
        file_handler = RotatingFileHandler(
            path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(_FORMATTER)
        setattr(file_handler, _MARK, True)
        root.setLevel(logging.INFO)
        root.addHandler(file_handler)

        # Keep console output when a real console exists (a console build, or
        # `python -m app` in a terminal). The windowed build has no console and
        # gets no stream handler — nothing to crash on.
        if console is not None:
            echo = logging.StreamHandler(console)
            echo.setFormatter(_FORMATTER)
            setattr(echo, _MARK, True)
            root.addHandler(echo)
        return path
    except Exception:
        # Same invariant as errors.log: setting up the log must never take down
        # the server it was only meant to record.
        return None
