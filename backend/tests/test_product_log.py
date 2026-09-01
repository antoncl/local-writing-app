"""The general-stream file log (#1745): rotating handler, console echo, windowed safety.

`product_log.configure_product_logging` is the catch-all the console used to be —
uvicorn/warnings/tracebacks routed to `<config_dir>/app.log`, distinct from the
curated `errors.log`. The seams under test: the file is created and captures a
logged line; the call is idempotent; a real console still gets an echo while a
windowed build (dead std streams) gets none but a crash-safe writer swap instead;
and a setup failure degrades to `None` rather than taking the launch down.

Both the root logger and `sys.stdout`/`sys.stderr` are process-global, so
`_restore_logging` snapshots and restores them per test — a leaked handler or a
swapped stream would corrupt every later test in the same worker. `config_dir` is
patched per test (the autouse conftest isolates `config_path`, not `config_dir`),
so nothing here touches the developer's real app-data dir.
"""

from __future__ import annotations

import io
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from app.services import product_log
from app.services.product_log import (
    _MARK,
    LOG_FILENAME,
    _LoggerWriter,
    configure_product_logging,
)


@pytest.fixture(autouse=True)
def _restore_logging():
    """Snapshot/restore the global logging + stream state around each test."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_stdout, saved_stderr = sys.stdout, sys.stderr
    try:
        yield
    finally:
        for handler in root.handlers[:]:
            if handler not in saved_handlers:
                handler.close()
                root.removeHandler(handler)
        root.setLevel(saved_level)
        sys.stdout, sys.stderr = saved_stdout, saved_stderr


def _use_temp_config_dir(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    monkeypatch.setattr(product_log, "config_dir", lambda: directory)


def _log_text(directory: Path) -> str:
    return (directory / LOG_FILENAME).read_text(encoding="utf-8")


def _marked_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if getattr(h, _MARK, False)]


def test_creates_log_file_and_captures_a_logged_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_temp_config_dir(monkeypatch, tmp_path)
    path = configure_product_logging()
    assert path == tmp_path / LOG_FILENAME
    assert path.exists()  # RotatingFileHandler opens eagerly

    logging.getLogger("app.somewhere").warning("hello from the server")
    assert "hello from the server" in _log_text(tmp_path)


def test_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_temp_config_dir(monkeypatch, tmp_path)
    first = configure_product_logging()
    count_after_first = len(_marked_handlers())
    second = configure_product_logging()

    assert second == first
    # A second call must not stack another set of handlers on the root logger.
    assert len(_marked_handlers()) == count_after_first


def test_real_console_gets_an_echo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_temp_config_dir(monkeypatch, tmp_path)
    console = io.StringIO()
    monkeypatch.setattr(sys, "stdout", console)
    configure_product_logging()

    logging.getLogger("app.somewhere").warning("echoed line")
    assert "echoed line" in console.getvalue()      # console echo
    assert "echoed line" in _log_text(tmp_path)      # and the file
    echo_handlers = [h for h in _marked_handlers() if not isinstance(h, RotatingFileHandler)]
    assert len(echo_handlers) == 1
    assert isinstance(echo_handlers[0], logging.StreamHandler)


def test_windowed_dead_streams_are_swapped_and_capture_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A windowed PyInstaller build has None std streams; writing to them would
    # crash. configure() must swap in a writer that lands in the log instead.
    _use_temp_config_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    configure_product_logging()  # must not raise

    assert isinstance(sys.stdout, _LoggerWriter)
    assert isinstance(sys.stderr, _LoggerWriter)
    print("stray print in a windowed build")  # would crash on a None stdout
    assert "stray print in a windowed build" in _log_text(tmp_path)


def test_windowed_build_adds_no_console_echo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With no real console, only the file handler is added — a StreamHandler
    # aimed at the LoggerWriter would recurse (write -> log -> handler -> write).
    _use_temp_config_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    configure_product_logging()

    marked = _marked_handlers()
    assert len(marked) == 1
    assert isinstance(marked[0], RotatingFileHandler)


def test_uvicorn_logs_reach_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The PR's core integration claim: passing log_config=None to uvicorn leaves
    # its error/access loggers unconfigured, so they propagate to the root file
    # handler instead of uvicorn's default console-only handlers. Proven against a
    # real short-lived server (an in-process emit couldn't tell log_config=None
    # from uvicorn's default), bound to an ephemeral port so parallel runs don't
    # collide. Guards against a future log_config re-add or a uvicorn default change.
    import threading
    import time
    import urllib.request

    import uvicorn

    from app.main import app

    _use_temp_config_dir(monkeypatch, tmp_path)
    configure_product_logging()

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started and server.servers:
                break
            time.sleep(0.05)
        assert server.started, "uvicorn did not start within the budget"
        port = server.servers[0].sockets[0].getsockname()[1]
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2).read()
        time.sleep(0.2)  # let the access log line flush
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    text = _log_text(tmp_path)
    assert "Application startup complete" in text  # uvicorn.error propagated to root
    assert "/api/health" in text                   # uvicorn.access propagated to root


def test_logger_writer_survives_a_failing_downstream_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The windowed disk-full / rollover-lock path: sys.stderr is the _LoggerWriter
    # and the downstream handler keeps raising. logging.handleError writes the
    # traceback back to sys.stderr (us); without the re-entrancy guard that would
    # re-drive the same failing handler until RecursionError takes the server down.
    class _Exploding(logging.Handler):
        # Mirrors StreamHandler/RotatingFileHandler: a failing emit calls
        # handleError, which (with logging.raiseExceptions) writes the traceback
        # to sys.stderr — the path that closes the recursion loop.
        def emit(self, record: logging.LogRecord) -> None:
            try:
                raise OSError("disk full during rollover")
            except OSError:
                self.handleError(record)

    root = logging.getLogger()
    root.addHandler(_Exploding())  # removed by _restore_logging
    root.setLevel(logging.ERROR)
    writer = _LoggerWriter(logging.getLogger("stderr"), logging.ERROR)
    monkeypatch.setattr(sys, "stderr", writer)

    # Must complete without RecursionError.
    writer.write("a stray stderr line\n")


def test_setup_failure_is_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An unwritable app-data dir must degrade to no file log, never a failed
    # launch — and the crash-safety stream swap still applies first.
    def _boom() -> Path:
        raise OSError("app-data dir unavailable")

    monkeypatch.setattr(product_log, "config_dir", _boom)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    assert configure_product_logging() is None  # swallowed, no raise
    assert isinstance(sys.stdout, _LoggerWriter)  # still made crash-safe
