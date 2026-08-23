"""The product entrypoint: resolve the bind address, then serve API + bundle.

`python -m app`, the `local-writing-app` console script, and (ADR-0072 slice S3)
the frozen binary all funnel through `main()`. Development keeps running
`uvicorn app.main:app --reload` directly — this path is for running the product,
not hot-reload dev.

Bind precedence (ADR-0072 §3): CLI flag -> env (LWA_HOST/LWA_PORT) -> machine
settings -> loopback default. Binding a non-loopback host is an explicit opt-in
and logs a no-authentication warning at startup (the "say so at the point of
choice" obligation for the CLI/env path).
"""

from __future__ import annotations

import argparse
import ipaddress
import logging
import os

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
    return parser


def resolve_bind(args: argparse.Namespace) -> tuple[str, int]:
    settings_host, settings_port = bind_address()
    host = args.host or os.environ.get("LWA_HOST") or settings_host or DEFAULT_HOST
    port = args.port or _env_port() or settings_port or DEFAULT_PORT
    return host, port


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
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
