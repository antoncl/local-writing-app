"""The product entrypoint: resolve the bind address, then serve API + bundle.

`python -m app`, the `local-writing-app` console script, and (ADR-0072 slice S3)
the frozen binary all funnel through `main()`. Development keeps running
`uvicorn app.main:app --reload` directly — this path is for running the product,
not hot-reload dev.

Bind precedence (ADR-0072 §3): CLI flag -> env (LWA_HOST/LWA_PORT) -> machine
settings -> loopback default. Binding a non-loopback host is an explicit opt-in
and logs a no-authentication warning at startup (the "say so at the point of
choice" obligation for the CLI/env path).

On a loopback desktop launch it also opens the default browser at the app's URL
(#1365), so the installed product answers "where is the app?" without the
optional pywebview shell (ADR-0072 §7/S8). Skipped for a non-loopback (LAN/Pi)
bind, for `--no-browser`/`LWA_NO_BROWSER`, and for `--self-check` — a headless
server must never try to pop a browser.
"""

from __future__ import annotations

import argparse
import ipaddress
import logging
import os
import threading

import uvicorn

from app.main import app
from app.services.machine_settings import bind_address

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

logger = logging.getLogger("app.server")


def _env_port() -> int | None:
    raw = os.environ.get("LWA_PORT")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _is_loopback(host: str) -> bool:
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A hostname we can't parse (not a bare IP) — treat as non-loopback so
        # the warning errs toward being shown, never silently suppressed.
        return False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-writing-app")
    parser.add_argument("--host", default=None, help="Bind host (overrides env/settings).")
    parser.add_argument("--port", type=int, default=None, help="Bind port (overrides env/settings).")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Open a throwaway project in-process to verify the runtime, then exit (0 ok, 1 failed).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open a browser window on startup (for a server/headless run).",
    )
    return parser


def resolve_bind(args: argparse.Namespace) -> tuple[str, int]:
    settings_host, settings_port = bind_address()
    host = args.host or os.environ.get("LWA_HOST") or settings_host or DEFAULT_HOST
    port = args.port or _env_port() or settings_port or DEFAULT_PORT
    return host, port


def _env_flag(name: str) -> bool:
    """A truthy env flag: set and not one of the obvious 'off' spellings."""
    raw = os.environ.get(name)
    return raw is not None and raw.strip().lower() not in ("", "0", "false", "no", "off")


def _should_open_browser(args: argparse.Namespace, host: str) -> bool:
    """Whether to pop the browser on this launch (#1365).

    Only for a loopback desktop run: a non-loopback bind is the LAN/Pi server,
    which is headless and must never open a browser — the same boundary the
    no-auth warning uses. `--no-browser` / `LWA_NO_BROWSER` force it off (the
    systemd server unit passes the flag; a desktop user never has to).
    """
    if args.no_browser or _env_flag("LWA_NO_BROWSER"):
        return False
    return _is_loopback(host)


def _open_browser_when_ready(host: str, port: int, *, timeout: float = 30.0) -> None:
    """Wait for the server to accept connections, then open the default browser.

    Runs in a daemon thread (so it neither blocks the server nor outlives it) and
    polls a TCP connect rather than sleeping a fixed delay — a frozen cold start
    can take a few seconds, and opening the URL before the socket is bound would
    load an error page. Best-effort throughout: no display, no browser, or a
    server that never comes up all end quietly. The server is the product and
    comes up regardless (ADR-0072 §7).
    """
    import contextlib
    import socket
    import time
    import webbrowser

    # A 0.0.0.0 bind never reaches this (non-loopback), but normalise defensively:
    # you connect to a concrete address, not the wildcard.
    connect_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((connect_host, port), timeout=1.0):
                break
        except OSError:
            time.sleep(0.2)
    else:
        return  # never came up within the budget — don't open a dead URL
    # Opening a browser is a convenience, never fatal: no display, no registered
    # browser, or a launcher that errors must not take the server down with it.
    with contextlib.suppress(Exception):
        webbrowser.open(f"http://{connect_host}:{port}")


def self_check() -> int:
    """Exercise the assembled runtime end-to-end, in-process; return 0 ok / 1 failed.

    Create a throwaway project and read it back through the service layer — the
    real node-index, schema, and built-in Library paths. These break in a frozen
    build in ways `--help` or a health ping never touch (a data file left
    unbundled, the node-index identity computed from source that isn't on disk),
    so this is what a per-platform CI smoke — and a user's "is my install
    healthy?" check — runs (#1350).
    """
    import tempfile
    import traceback
    from pathlib import Path

    from app.services.project_service import ProjectService

    print("self-check: opening a throwaway project through the real runtime...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            service = ProjectService.created_at(Path(tmp) / "self-check-project", "self-check")
            service.read_structure()       # node-index build identity + schema resolution
            service.list_lore_entries()     # node-index load
            service.list_prompt_entries()   # built-in Library resolution
    except Exception as exc:
        print(f"self-check: FAILED - {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1
    print("self-check: OK")
    return 0


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    if args.self_check:
        raise SystemExit(self_check())
    host, port = resolve_bind(args)
    if not _is_loopback(host):
        logger.warning(
            "Binding %s:%s — reachable on your network. This app has NO "
            "authentication; only expose it to a single trusted user on a "
            "trusted private network.",
            host,
            port,
        )
    if _should_open_browser(args, host):
        # Daemon thread: opens the browser once the socket is live, then dies with
        # the process. Started before the blocking uvicorn.run below.
        threading.Thread(
            target=_open_browser_when_ready, args=(host, port), daemon=True
        ).start()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
