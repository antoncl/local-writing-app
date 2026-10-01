"""Pytest-wide fixtures.

`_isolate_machine_settings` redirects `machine_settings.config_path()` to a
per-test tempdir so tests can't accidentally read or write the developer's
real ~/AppData (or ~/.config) machine settings. Tests that need stricter
control (e.g. test_assistants) still patch config_path themselves; their
patch takes precedence over this safety net.

`_inject_wire_scope` plays the browser (#413): since the resolution scope now
rides the wire (`X-Project-Root`), it injects the current test's scope header on
every `TestClient` request, so routes resolve their project from the request
exactly as in production. It also resets the scope per-test so one test's open
project never leaks into the next.

`_neutralize_price_oracle` stops the ADR-0083 price oracle from reaching the
network: it warms inside every native profile's `list_models`, so without this
the suite would fetch OpenRouter's live feed and overlay real (drifting) prices
onto baked descriptors, making native cost assertions non-deterministic. Stubbed
to an empty feed by default; oracle tests re-stub `_fetch_rows` themselves.

No test touches the network. `_offline_http` refuses every real httpx transport,
so a provider profile's live model listing takes its offline bake-in path; the
socket guard installed in `pytest_configure` (with `_forbid_network`) fails any
test that still reaches a non-loopback host by any other client.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import tempfile

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError


def pytest_configure(config: pytest.Config) -> None:
    """Floor isolation for `machine_settings.config_dir()` (#1862).

    Point the `LWA_CONFIG_DIR` seam at a throwaway dir before collection, so:
    (a) any import-time or fixture-ordering resolution of the config dir lands in
    tmp, never the developer's real `%APPDATA%`; (b) the `config_dir()` guard
    never trips under pytest; and (c) subprocesses a test spawns inherit an
    isolated config dir. Set unconditionally (not `setdefault`) so a stray real
    value already in the environment can't defeat the floor. The per-test
    `_isolate_machine_settings` fixture narrows it to a fresh dir per test.

    Keyring floor (#2287): a subprocess a test spawns resolves keyring's inert
    `null` backend, never the developer's OS store; in-process tests get a fresh
    in-memory store per test (`_isolate_keyring`)."""
    os.environ["LWA_CONFIG_DIR"] = tempfile.mkdtemp(prefix="lwa-test-cfg-")
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    _install_network_guard()


class NetworkAccessBlocked(OSError):
    """A test tried to reach a non-loopback host."""


# Every refused attempt, recorded as well as raised: provider code catches
# transport errors and falls back to bake-in, so a raise alone would vanish.
# `_forbid_network` turns a non-empty record into a test failure.
_network_attempts: list[str] = []


def _is_loopback(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode()
    if host is None or host in ("", "localhost", "0.0.0.0", "::"):
        return True
    host = str(host)
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return host.endswith(".localhost")


def _install_network_guard() -> None:
    """No backend test touches the network: refuse every name lookup and connect
    to a non-loopback host, process-wide (in-process servers, asyncio's
    self-pipe and AF_UNIX stay allowed). Installed in `pytest_configure` so
    import-time and session-scoped code is covered too, and in each xdist
    worker, which runs this hook itself.

    Names are refused at `getaddrinfo` because Windows' proactor loop connects
    through `ConnectEx`, never `socket.connect` — the lookup is the one step
    every async and sync client shares."""
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def refuse(what: str, target: object) -> NetworkAccessBlocked:
        _network_attempts.append(f"{what} {target!r}")
        return NetworkAccessBlocked(f"network access blocked in tests: {what} {target!r}")

    def getaddrinfo(host, *args, **kwargs):
        if not _is_loopback(host):
            raise refuse("getaddrinfo", host)
        return real_getaddrinfo(host, *args, **kwargs)

    def connect(self, address):
        if isinstance(address, tuple) and not _is_loopback(address[0]):
            raise refuse("connect", address)
        return real_connect(self, address)

    def connect_ex(self, address):
        if isinstance(address, tuple) and not _is_loopback(address[0]):
            raise refuse("connect_ex", address)
        return real_connect_ex(self, address)

    socket.getaddrinfo = getaddrinfo
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex


@pytest.fixture(autouse=True)
def _forbid_network():
    _network_attempts.clear()
    yield
    if _network_attempts:
        attempts = ", ".join(_network_attempts)
        _network_attempts.clear()
        pytest.fail(f"test reached for the network: {attempts}", pytrace=False)


class MemoryKeyring(KeyringBackend):
    """A usable (priority > 0) secret store that lives only in this process."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.entries.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


@pytest.fixture(autouse=True)
def _isolate_keyring():
    """A fresh in-memory keyring per test (#2287): provider keys never reach the
    developer's real OS secret store, and never leak between tests."""
    previous = keyring.get_keyring()
    store = MemoryKeyring()
    keyring.set_keyring(store)
    yield store
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def _isolate_machine_settings(tmp_path, monkeypatch, _isolate_keyring):
    from app.services import machine_settings as ms

    fake = tmp_path / "machine" / "config.yaml"
    # Redirect BOTH seams to the same per-test dir so config_path() and
    # config_dir() never diverge: config_path()==config_dir()/config.yaml, the
    # real relationship. config_path is patched (tests assert on it directly);
    # config_dir() reads the env override.
    monkeypatch.setenv("LWA_CONFIG_DIR", str(fake.parent))
    monkeypatch.setattr(ms, "config_path", lambda: fake)
    yield


@pytest.fixture(autouse=True)
def _neutralize_price_oracle(_isolate_machine_settings, monkeypatch):
    # Depends on _isolate_machine_settings so config_path is ALREADY redirected to
    # tmp before reset_cache() runs — reset_cache now deletes the cache file, and
    # that file's path derives from config_path. Without this ordering a setup-time
    # reset could unlink the developer's real price_oracle_cache.json.
    from app.services.ai.profiles import price_oracle

    price_oracle.reset_cache()

    async def _empty_feed() -> list[dict]:
        return []

    monkeypatch.setattr(price_oracle, "_fetch_rows", _empty_feed)
    yield
    price_oracle.reset_cache()


@pytest.fixture(autouse=True)
def _offline_http(monkeypatch):
    """Every real httpx transport is offline in tests.

    A generate/chat cost lookup resolves `priced_descriptor_for` → `descriptor_for`
    → the provider profile's `list_models`, which fetches the live catalogue
    (`/v1/models`, OpenRouter's public `/api/v1/models`, Ollama's `/api/tags`)
    BEFORE the oracle overlay `_neutralize_price_oracle` stubs. Every profile opens
    a plain `httpx.AsyncClient` for it, so the shared seam is httpx's real
    transport: refusing it sends each profile down its own offline path (bake-in,
    or no local models) — deterministic, and never a live, drifting catalogue.

    Tests that mean to answer HTTP pass `transport=httpx.MockTransport(...)` or
    replace `httpx.AsyncClient`/`Client`; neither reaches these methods."""
    import httpx

    def refuse(request: httpx.Request) -> httpx.ConnectError:
        return httpx.ConnectError(f"offline in tests: {request.url}", request=request)

    def handle_request(self, request):
        raise refuse(request)

    async def handle_async_request(self, request):
        raise refuse(request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle_request)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle_async_request)


@pytest.fixture(autouse=True)
def _inject_wire_scope(monkeypatch):
    import project_fixtures
    from starlette.testclient import TestClient

    project_fixtures.clear_test_scope()
    original_request = TestClient.request

    def request_with_scope(self, method, url, *args, headers=None, **kwargs):
        merged = dict(headers) if headers else {}
        for key, value in project_fixtures.test_scope_header().items():
            merged.setdefault(key, value)  # an explicit header still wins
        return original_request(self, method, url, *args, headers=merged, **kwargs)

    monkeypatch.setattr(TestClient, "request", request_with_scope)
    yield
    project_fixtures.clear_test_scope()
