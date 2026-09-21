"""Download-and-apply half of the in-app updater (ADR-0072 S6, #2083).

`updates.py` only *notifies*. This downloads the release asset for the running
channel and hands off to the platform installer so the app is replaced and
relaunched — "download + swap-on-restart".

Two apply paths so far, one per install form:
- **Windows** (#2083): download `setup.exe`, run it silently; the Inno stable
  AppId upgrades in place and a `[Run]` entry relaunches it.
- **Linux AppImage** (#2089): download the new `.AppImage`, then a detached
  helper waits for this process to exit, replaces the running file (path from
  `$APPIMAGE`) and relaunches — an AppImage can't swap itself while mounted.

macOS (#2090) and the Linux headless tarball (that's `update-server.sh`) are not
here; they report ``unsupported`` and the UI keeps the release-page link.

Flow: `start_apply()` kicks off a background worker (download -> verify ->
apply) and returns immediately; the UI polls `current_status()`. The apply step
hands off detached and asks the server to stop gracefully
(`runtime_control.request_shutdown`) so this process exits and its files can be
replaced, then the app relaunches. There is deliberately no silent/background
auto-update — a human clicks "install", and only the official release asset for
the pinned repo is ever fetched, over HTTPS.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading

import httpx

from app.models import UpdateApplyStatus, UpdateChannel
from app.services import runtime_control
from app.services.machine_settings import config_dir
from app.services.updates import GITHUB_REPO

logger = logging.getLogger("app.update_apply")

# The in-place-upgradable desktop assets, one per supported platform. Both are
# x64 only — the arm64 desktop ships as a portable zip (no in-app apply) and the
# headless tarball updates via update-server.sh.
_WINDOWS_SETUP_ASSET = "local-writing-app-windows-x64-setup.exe"
_LINUX_APPIMAGE_ASSET = "local-writing-app-linux-x64.AppImage"
_DOWNLOAD_TIMEOUT_SECONDS = 300.0
_HEADERS = {"User-Agent": "local-writing-app-updater"}

# Detached POSIX helper: wait for the running app (pid $1) to exit, move the new
# AppImage ($2) over the current one ($3), make it executable, and relaunch. An
# AppImage is a mounted read-only image, so it can only be replaced from outside
# the running process — hence a helper that outlives it. The final `exec` is
# unconditional: if the swap fails (e.g. a non-writable dir) the old AppImage is
# untouched, so we still relaunch it rather than leave the user with no app.
_APPIMAGE_SWAP = (
    'pid="$1"; new="$2"; target="$3"; '
    'while kill -0 "$pid" 2>/dev/null; do sleep 0.5; done; '
    'mv -f "$new" "$target" && chmod +x "$target"; '
    'exec "$target"'
)


def apply_supported() -> bool:
    """Whether this build/platform can install an update in-app.

    A source run has nothing to replace. Frozen Windows always can; frozen Linux
    only when running *as an AppImage* (`$APPIMAGE` set) — the portable zip and
    the headless tarball (update-server.sh) have no in-app path. macOS is #2090."""
    if not getattr(sys, "frozen", False):
        return False
    if sys.platform == "win32":
        return True
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("APPIMAGE"))
    return False


class _State:
    """The single in-flight apply's progress, guarded by a lock (one apply at a
    time — the UI only offers the button when idle/finished)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = UpdateApplyStatus(state="idle")

    def get(self) -> UpdateApplyStatus:
        with self._lock:
            return self._status.model_copy()

    def set(self, **fields: object) -> None:
        with self._lock:
            self._status = self._status.model_copy(update=fields)

    def begin(self) -> bool:
        """Atomically start a fresh apply if none is running; False if one is.

        Check-and-set under one lock so two concurrent POSTs can't both spawn a
        worker (single-flight, independent of the UI disabling the button)."""
        with self._lock:
            if self._status.state in ("downloading", "verifying", "applying"):
                return False
            self._status = UpdateApplyStatus(state="downloading", progress=0.0)
            return True


_state = _State()


def current_status() -> UpdateApplyStatus:
    return _state.get()


def _platform_asset() -> str:
    """The release asset to download for this platform's in-app apply."""
    if sys.platform == "win32":
        return _WINDOWS_SETUP_ASSET
    return _LINUX_APPIMAGE_ASSET


def _asset_url(channel: UpdateChannel) -> str:
    # stable = the latest non-prerelease; nightly = the rolling `nightly` tag.
    if channel == "nightly":
        base = f"https://github.com/{GITHUB_REPO}/releases/download/nightly"
    else:
        base = f"https://github.com/{GITHUB_REPO}/releases/latest/download"
    return f"{base}/{_platform_asset()}"


def _download(url: str, dest, on_progress) -> int:
    """Stream `url` to `dest`, reporting 0..1 progress; return bytes written.

    `follow_redirects` is required — the `/releases/latest/download/` path is a
    302 to the asset host."""
    written = 0
    with httpx.stream(
        "GET",
        url,
        follow_redirects=True,
        timeout=_DOWNLOAD_TIMEOUT_SECONDS,
        headers=_HEADERS,
    ) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length", 0) or 0)
        with open(dest, "wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
                written += len(chunk)
                if total:
                    on_progress(min(1.0, written / total))
    # Catch a stream that ended short of its declared length without erroring —
    # a real completeness check (vs. the tautology of size-vs-own-byte-count).
    if total and written != total:
        raise RuntimeError(f"incomplete download ({written} of {total} bytes)")
    return written


def _spawn_installer(installer_path) -> None:
    """Launch the Inno installer silently, detached so it outlives this process.

    `/CLOSEAPPLICATIONS` lets it close us if we're still holding files;
    `[Run]` in the installer relaunches the app afterwards (no
    `/RESTARTAPPLICATIONS`, to avoid a double launch)."""
    subprocess.Popen(  # noqa: S603 - our own signed-by-us-later installer, fixed args
        [
            str(installer_path),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/CLOSEAPPLICATIONS",
            "/NORESTART",
        ],
        creationflags=(
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        ),
        close_fds=True,
    )


def _spawn_appimage_swap(new_path) -> None:
    """Hand the new AppImage to a detached helper that swaps it in after we exit.

    `start_new_session` detaches the helper from our process group so it survives
    our shutdown; it inherits the environment (DISPLAY etc.) so the relaunched
    app can open the browser."""
    target = os.environ.get("APPIMAGE")
    if not target:
        raise RuntimeError("not running as an AppImage ($APPIMAGE unset)")
    subprocess.Popen(  # noqa: S603 - fixed argv, our own inlined helper script
        ["/bin/sh", "-c", _APPIMAGE_SWAP, "lwa-update", str(os.getpid()), str(new_path), target],
        start_new_session=True,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _apply(dest) -> None:
    """Hand the downloaded asset to the platform's swap-and-relaunch mechanism."""
    if sys.platform == "win32":
        _spawn_installer(dest)
    else:
        _spawn_appimage_swap(dest)


def _run(channel: UpdateChannel) -> None:
    """Background worker: download -> verify -> apply. Never raises to the caller
    — failures land in the status as ``error`` with a short detail."""
    try:
        _state.set(state="downloading", progress=0.0, detail=None)
        target_dir = config_dir() / "updates"
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / _platform_asset()
        url = _asset_url(channel)
        logger.info("Update: downloading %s", url)
        written = _download(url, dest, lambda frac: _state.set(progress=frac))

        _state.set(state="verifying", progress=1.0)
        # Unsigned builds (ADR-0072 §10): we can't verify a signature. `_download`
        # already fails a short read against Content-Length; here we just refuse
        # an empty/missing file before handing it on.
        if written <= 0 or not dest.exists():
            raise RuntimeError("the downloaded update is empty")

        _state.set(state="applying")
        logger.info("Update: handing off to the installer and stopping for replacement")
        _apply(dest)
        # Exit gracefully so our files unlock; the installer/helper replaces them
        # and relaunches. On Windows the installer's /CLOSEAPPLICATIONS is a
        # backstop; on Linux the helper waits for this pid to exit first.
        runtime_control.request_shutdown()
    except Exception as exc:  # noqa: BLE001 - any failure becomes a status, not a crash
        logger.warning("Update apply failed: %s", exc)
        _state.set(state="error", detail=str(exc) or exc.__class__.__name__)


def start_apply(channel: UpdateChannel) -> UpdateApplyStatus:
    """Begin an install in the background (idempotent while one is running).

    Returns the status to report to the caller: ``unsupported`` off Windows, the
    in-flight status if one is already running, else a fresh ``downloading``."""
    if not apply_supported():
        _state.set(
            state="unsupported",
            detail="In-app install isn't available on this platform yet.",
        )
        return _state.get()
    if not _state.begin():
        return _state.get()  # one already running
    threading.Thread(target=_run, args=(channel,), daemon=True).start()
    return _state.get()
