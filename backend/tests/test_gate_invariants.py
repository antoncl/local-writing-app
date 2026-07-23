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
import os
import socket
import subprocess
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


def test_default_port_varies_with_the_checkout(monkeypatch):
    """Different checkouts must get different ports — the actual #364 property.

    Stated as "the port is a function of REPO that separates siblings", because
    the obvious version of this test cannot fail: assert determinism, a range,
    and "not 8787", and `return 8888` — a constant in a tracked file, which *is*
    the #364 root cause — passes all three. Vary REPO instead.
    """
    ports = {}
    for path in (
        r"D:\Users\anton\Documents\Projects\local-writing-app",
        r"D:\Users\anton\Documents\Projects\local-writing-app\.claude\worktrees\a",
        r"D:\Users\anton\Documents\Projects\local-writing-app\.claude\worktrees\b",
        "/home/runner/work/local-writing-app/local-writing-app",
    ):
        monkeypatch.setattr(dev_backend, "REPO", Path(path))
        ports[path] = dev_backend.default_port()

    assert len(set(ports.values())) == len(ports), (
        f"checkouts share a default port: {ports}. Sibling worktrees would "
        "collide, which is #364."
    )
    for path, port in ports.items():
        assert dev_backend.PORT_BASE <= port < dev_backend.PORT_BASE + dev_backend.PORT_SPAN, (
            f"{path} -> {port} is outside the reserved range"
        )


def test_default_port_is_stable_for_one_checkout(monkeypatch):
    """Restarting the same tree must reuse its port, or the port file churns."""
    monkeypatch.setattr(dev_backend, "REPO", Path(r"D:\some\checkout"))
    assert dev_backend.default_port() == dev_backend.default_port()


def test_default_port_range_avoids_the_pinned_stack():
    """Anton's :8787 and :5173 must be unreachable, not merely unlikely."""
    reserved = range(dev_backend.PORT_BASE, dev_backend.PORT_BASE + dev_backend.PORT_SPAN)
    assert 8787 not in reserved
    assert 5173 not in reserved
    assert 8788 not in reserved, "the historical shared port that caused #364"


def test_probe_path_cannot_drift():
    """The wrapper's fallback must equal the path the launcher probes.

    They are separate modules, and if the constants differ our own healthy
    server 404s the probe — which `verify_server` reports as "SERVED BY A
    DIFFERENT SERVER", sending the reader after a hijack that never happened.
    The launcher passes the real value through `DEV_BACKEND_PROBE_PATH`; this
    pins the fallback the two literals share.
    """
    source = (REPO / "scripts" / "dev_backend_app.py").read_text(encoding="utf-8")
    assert f'"{dev_backend.PROBE_PATH}"' in source, (
        f"scripts/dev_backend_app.py no longer mentions {dev_backend.PROBE_PATH!r}"
    )


def test_port_file_is_left_alone_when_a_start_fails(tmp_path, monkeypatch):
    """A failed launch must not delete the port file a working one published.

    Both launchers in a worktree share `tmp/dev-backend-port`, so an
    unconditional cleanup on the failure path strands the running server: the
    frontend hard-fails on the missing file and `claim_port` refuses to start a
    replacement on the port still held.
    """
    port_file = tmp_path / "dev-backend-port"
    port_file.write_text("8801", encoding="utf-8")
    monkeypatch.setattr(dev_backend, "PORT_FILE", port_file)
    monkeypatch.setattr(dev_backend, "resolve_port", lambda: 8802)
    monkeypatch.setattr(dev_backend, "claim_port", lambda _port: True)
    monkeypatch.setattr(dev_backend, "find_venv_python", lambda _root: Path(sys.executable))
    monkeypatch.setattr(dev_backend, "verify_server", lambda *_a: False)

    killed = []
    monkeypatch.setattr(dev_backend, "kill_tree", killed.append)
    monkeypatch.setattr(
        dev_backend.subprocess, "Popen", lambda *_a, **_k: _StubProc()
    )

    assert dev_backend.main() == 1
    assert killed, "a failed start must take its server down"
    assert port_file.read_text(encoding="utf-8") == "8801", (
        "the other launcher's published port was deleted"
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


# --------------------------------------------------------------------------
# #435 — the generated diff fixtures still describe the code that generates them
# --------------------------------------------------------------------------


def _gen_fixtures(*args: str) -> subprocess.CompletedProcess[str]:
    """Run `scripts/gen_diff_fixtures.py` as CI runs it.

    A subprocess rather than an import, for two reasons. The script inserts this
    checkout's `backend/` and `backend/tests` at the front of `sys.path` when it
    loads; importing it here would leave that mutation behind for every later
    test in the session, and the two tests above exist precisely because which
    tree `app` resolves from is load-bearing. And running the real command line
    is the point — the gate CI depends on is the *CLI contract*, not the
    internals, so this pins what CI actually invokes.
    """
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_diff_fixtures.py"), *args],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def test_diff_fixtures_are_current():
    """`diffRuns.fixtures.json` must still be what `diff_runs` produces.

    The file is generated from the backend and consumed by the frontend suite,
    which renders it through the real `sceneMarkdownToHtml`. Nothing regenerated
    it, so it was a frozen output of the code it grades: under a mutation to the
    diff the committed JSON stayed stale and the frontend stayed green (#435).

    A test rather than a step in `gates.yml`, which is where it started, for two
    reasons. It runs on **Windows**: the generator's one platform-sensitive line
    is its `newline=""` write, and the hazard it guards — the default
    translation emitting CRLF — happens only on Windows, so as a step in the
    Linux `backend` job the gate never visited the case it exists for. And a
    workflow step can be deleted without anything noticing, while
    `check_exemptions.py` ratchets a test that turns up newly skipped.
    """
    result = _gen_fixtures("--check")
    assert result.returncode == 0, (
        "the committed diff fixtures no longer match what diff_runs produces.\n"
        "Run `python scripts/gen_diff_fixtures.py` and commit the result; if the "
        "change is deliberate, the diff is the thing to review.\n"
        f"{result.stdout}{result.stderr}"
    )


def test_the_fixture_gate_refuses_an_argument_it_does_not_understand():
    """An unrecognised flag must fail, not silently fall through to writing.

    This is the guard on the guard. The first form tested `"--check" in argv`,
    so a misspelled or renamed flag in `gates.yml` regenerated the fixtures
    inside the runner's own checkout and exited 0 — the gate reporting green
    while doing nothing, which is the failure this whole file is about.
    """
    result = _gen_fixtures("--chek")
    assert result.returncode != 0, (
        "an unrecognised argument was accepted, so a typo in the workflow would "
        "silently turn the fixture gate into a no-op that reports success."
    )


# --- the memory-index ratchet -------------------------------------------------
#
# `MEMORY.md` is loaded into every request of every session, so its size is paid
# on every model step. It has no natural shrinking force — sessions add memories
# and never remove them — so `scripts/check_memory_index.py` ratchets it. These
# tests pin the two properties that make a ratchet useful: it must be silent
# while nothing regresses, and it must not be silenceable by accident.

check_memory_index = _load_script("check_memory_index")


def _index(tmp_path: Path, body: str) -> Path:
    (tmp_path / "real.md").write_text("a memo", encoding="utf-8")
    index = tmp_path / "MEMORY.md"
    index.write_text(body, encoding="utf-8")
    return index


def test_a_healthy_index_is_silent(tmp_path):
    """No finding for a well-formed index — a guard that always fires is noise."""
    index = _index(tmp_path, "# Memory Index\n\n- [Real](real.md) - a short hook\n")
    assert check_memory_index.check(index) == []


def test_a_pointer_to_a_missing_memo_is_always_reported(tmp_path):
    """Dangling pointers are a correctness bug, so they carry no ratchet."""
    index = _index(tmp_path, "# Memory Index\n\n- [Gone](vanished.md) - hook\n")
    problems = check_memory_index.check(index)
    assert any("missing memo" in p for p in problems)


def test_growth_past_the_ratchet_is_reported(tmp_path):
    """The whole point: the file may shrink, never grow."""
    index = _index(tmp_path, "# Memory Index\n\n- [Real](real.md) - hook\n")
    assert check_memory_index.check(index) == []
    index.write_text("x" * (check_memory_index.MAX_BYTES + 1), encoding="utf-8")
    assert any("over the" in p for p in check_memory_index.check(index))


def test_the_content_budget_only_ever_ratchets_down(tmp_path):
    """Below the budget it stays quiet; one line over it, the guard speaks.

    This test used to assert the opposite — that the budget must be > 0 —
    because when the guard landed the index carried 8 blocks of inline prose,
    and an absolute rule would have fired on every memory write until that was
    consolidated. The 2026-07-23 pass removed all 8, so the budget ratcheted to
    0 and the rule the index always claimed to follow (pointers only, content
    in the memo) is finally absolute.

    The property being pinned is therefore the *direction*: the budget may fall
    and must never rise. A future session that hits the rule and "fixes" it by
    raising the constant has reintroduced exactly what this guard exists to
    stop, and this assertion is what catches that.
    """
    budget = check_memory_index.MAX_CONTENT_LINES
    assert budget == 0, (
        "MAX_CONTENT_LINES ratchets down only. It reached 0 on 2026-07-23; "
        "raising it means inline prose is back in the index, which is paid on "
        "every model step. Move the content into a memo instead."
    )

    at_budget = "# Memory Index\n\n" + "".join(f"**Inline {i}:** prose\n" for i in range(budget))
    assert not any("non-pointer" in p for p in check_memory_index.check(_index(tmp_path, at_budget)))

    over = at_budget + "**One more:** prose\n"
    assert any("non-pointer" in p for p in check_memory_index.check(_index(tmp_path, over)))


def test_a_missing_memory_dir_does_not_fail_the_gate(tmp_path):
    """Clones without a memory directory must not go red; the guard falls open."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_memory_index.py"),
         "--memory-dir", str(tmp_path / "absent")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_findings_survive_a_cp1252_console(tmp_path):
    """Memory files carry emoji; the guard must not die encoding one back.

    This is a Windows-first repo and the guard runs on a console that defaults
    to cp1252. An earlier version raised UnicodeEncodeError while *reporting* a
    finding, which turns a useful gate into a crash at exactly the moment it
    has something to say.
    """
    _index(tmp_path, "# Memory Index\n\n" + "\U0001f333 inline content with an emoji\n" * 40)
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_memory_index.py"),
         "--memory-dir", str(tmp_path)],
        capture_output=True, text=True, env=env,
        # Decode with the encoding we just forced on the child. `text=True`
        # alone decodes with the *parent's* default, which is cp1252 on Windows
        # and UTF-8 on Linux — so the child's cp1252 em-dash (0x97) read back
        # fine locally and raised UnicodeDecodeError in CI.
        encoding="cp1252",
    )
    # `returncode == 1` alone proves nothing: a UnicodeEncodeError also exits 1,
    # and it happens *after* the "memory index:" header has been flushed, so
    # both of those pass while the guard is in fact crashing. The traceback on
    # stderr is the only thing that distinguishes reporting from dying.
    assert "Traceback" not in result.stderr, f"the guard crashed while reporting:\n{result.stderr}"
    assert result.stderr.strip() == "", result.stderr
    assert result.returncode == 1, "the oversized index should have been reported"
    assert "memory index:" in result.stdout
    assert "non-pointer" in result.stdout, "the finding itself never made it out"
