"""The quality gates' own invariants (#352, #364).

These assert properties of the *test run itself* and of the dev-server launcher,
not of the app. They exist because a gate that validates the wrong code fails in
the two worst ways: red when nothing is broken, and green when something is. A
browser preview that serves the wrong tree is the same failure with no red at
all, which is why `scripts/dev_backend.py` is pinned here too.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import app

REPO = Path(__file__).resolve().parents[2]


def _load_script(name: str):
    """Import a module from `scripts/`, which is not a package."""
    path = REPO / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_gate_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dev_backend = _load_script("dev_backend")


class _StubProc:
    """A process that is still running, as far as `verify_server` can tell."""

    returncode = None

    def poll(self):
        return None


class _FakeServer:
    """A server on a real port, answering the provenance probe however we say."""

    def __init__(self, payload: dict | None):
        self.payload = payload
        handler = self._handler()
        self.httpd = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def _handler(self):
        payload = self.payload

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's spelling
                if payload is None:
                    self.send_error(404)
                    return
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        return Handler

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def fake_server():
    servers = []

    def make(payload):
        server = _FakeServer(payload)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.close()


# --------------------------------------------------------------------------
# #352 — the test run imports the checkout it was collected from
# --------------------------------------------------------------------------


def test_app_under_test_belongs_to_this_checkout():
    """`import app` must resolve inside the tree these tests were collected from.

    The shared venv installs the backend editable against the *primary* git
    worktree, so from a linked worktree `app` resolves there unless something
    puts this checkout's `backend/` first (scripts/venv_run.py does). Without
    that, pytest runs one tree's tests against another tree's code — and the
    primary tree normally carries uncommitted WIP.
    """
    app_dir = Path(app.__file__).resolve().parent
    expected = (REPO / "backend" / "app").resolve()
    assert app_dir == expected, (
        f"tests collected from {REPO} but `app` imported from {app_dir}.\n"
        "Run the suite via `python scripts/venv_run.py -m pytest backend/tests`, "
        "which puts this checkout's backend/ on PYTHONPATH."
    )


def test_no_meta_path_finder_outranks_pythonpath_for_app():
    """`venv_run.py`'s PYTHONPATH fix must win *by construction*, not by luck.

    #364 asked whether #352's guarantee was real. It is, but only because of an
    ordering nothing enforced: a PEP 660 editable install ships a
    `__editable___*_finder.py` **meta path finder**, and `sys.meta_path` is
    consulted before `sys.path`. setuptools currently *appends* it, leaving it
    behind `PathFinder`, so PYTHONPATH decides. Were it ever inserted ahead of
    `PathFinder` — a different packaging backend, a future setuptools — the
    editable install's hardcoded path to the primary worktree would silently
    outrank PYTHONPATH and #352 would regress with no other symptom.

    So pin the property #352 actually depends on: nothing ahead of `PathFinder`
    claims `app`.
    """
    from importlib.machinery import PathFinder

    ahead = []
    for finder in sys.meta_path:
        if finder is PathFinder:
            break
        ahead.append(finder)

    claimants = []
    for finder in ahead:
        find_spec = getattr(finder, "find_spec", None)
        if find_spec is None:
            continue
        try:
            if find_spec("app", None) is not None:
                claimants.append(finder)
        except (ImportError, AttributeError, TypeError):
            continue

    assert not claimants, (
        f"{claimants} answer `import app` before PathFinder, so sys.path order "
        "(and therefore PYTHONPATH, and therefore scripts/venv_run.py) no longer "
        "decides which checkout is imported. See #352 and #364."
    )


# --------------------------------------------------------------------------
# #364 — the dev server that answers the port is the one we started
# --------------------------------------------------------------------------


def test_default_port_is_per_checkout():
    """Two checkouts must not aim at the same port by default.

    The old launcher fell back to a constant 8788 held in a *tracked* file, so
    every worktree targeted the same port — the collision `dev_backend.py`'s own
    docstring says it exists to prevent.
    """
    assert dev_backend.default_port() == dev_backend.default_port()
    assert (
        dev_backend.PORT_BASE
        <= dev_backend.default_port()
        < dev_backend.PORT_BASE + dev_backend.PORT_SPAN
    )
    assert dev_backend.default_port() not in (8787, 5173), (
        "must not collide with Anton's pinned stack"
    )


def test_claim_port_refuses_an_occupied_port():
    """The check uvicorn --reload does not do for us on Windows.

    `uvicorn/config.py::bind_socket` sets SO_REUSEADDR on the reload path, and
    Windows reads that as "share this address": the second server starts
    cleanly, owns nothing, and the first keeps answering. #364.
    """
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:
        holder.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        assert dev_backend.claim_port(port) is False
    finally:
        holder.close()


def test_claim_port_accepts_a_free_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    assert dev_backend.claim_port(port) is True


def test_verify_server_rejects_another_checkouts_server(fake_server):
    """The #364 reproduction, as a check: our launch, someone else's server.

    Before the fix this was the whole bug — our uvicorn logged "Application
    startup complete" while a server from another tree answered every request.
    Nothing in our own process could notice, so the proof has to be a round trip
    carrying a secret only this launch knows.
    """
    server = fake_server(
        {
            "checkout": r"D:\Users\anton\Documents\Projects\local-writing-app",
            "app_file": r"D:\...\local-writing-app\backend\app\__init__.py",
            "nonce": "a-different-launch",
            "pid": 4242,
        }
    )
    assert verify(server.port, "our-nonce") is False


def test_verify_server_rejects_a_server_without_the_probe(fake_server):
    """A plain uvicorn (Anton's :8787 stack) 404s the probe — also not ours."""
    server = fake_server(None)
    assert verify(server.port, "our-nonce") is False


def test_verify_server_accepts_our_own_server(fake_server):
    server = fake_server(
        {
            "checkout": str(REPO),
            "app_file": str(REPO / "backend" / "app" / "__init__.py"),
            "nonce": "our-nonce",
            "pid": 1,
        }
    )
    assert verify(server.port, "our-nonce") is True


def verify(port: int, nonce: str) -> bool:
    return dev_backend.verify_server(port, nonce, _StubProc())
