"""Provider API keys in the OS secret store (#2287).

Keys used to sit in plaintext in `config.yaml`, where anything that reads or
copies the file gets them — a backup, a synced folder, a config attached to a
bug report, a tool that prints it. They now live in the OS store instead:
Windows Credential Manager, macOS Keychain, Linux Secret Service, via
`keyring`. `machine_settings` is the only caller: it fills the key fields from
here on load and writes them here (blanking the file) on save.

Two properties keep this safe beside the rest of the app:

- **Namespaced per config dir.** The entries live under `local-writing-app`
  for the real machine config, and under a suffixed name when
  `LWA_CONFIG_DIR` points elsewhere — a worktree dev backend, an E2E run — so an
  isolated config can never read, or overwrite, the author's real keys.
- **Never the real keyring from a test process.** A test run installs an
  in-memory backend (conftest); reaching a real OS backend from a process with
  a test runner loaded fails loud, the same stance as the config-dir guard
  (#1862, #2279).

Where no OS store exists (a headless Linux box with no Secret Service) the
keyring backend reports itself unusable; `available()` is then False and the
keys stay in `config.yaml`, which the Settings dialog says plainly.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import sys

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError, PasswordDeleteError

KEY_FIELDS = ("anthropic_api_key", "openai_api_key", "openrouter_api_key")
_SERVICE = "local-writing-app"
# Duplicated from machine_settings.CONFIG_DIR_ENV (which imports this module).
_CONFIG_DIR_ENV = "LWA_CONFIG_DIR"
# Backends that store nothing — the ones a test process may use besides its own
# in-memory one. Anything else under `keyring.backends.` is a real OS store.
_INERT_BACKEND_MODULES = ("keyring.backends.null", "keyring.backends.fail")

logger = logging.getLogger(__name__)


def service_name() -> str:
    """The keyring service the keys live under: the plain app name for the real
    machine config, a per-directory name for an isolated one."""
    override = os.environ.get(_CONFIG_DIR_ENV)
    if not override:
        return _SERVICE
    digest = hashlib.sha256(os.path.normcase(os.path.abspath(override)).encode("utf-8")).hexdigest()[:12]
    return f"{_SERVICE}-{digest}"


def _backend() -> KeyringBackend:
    backend = keyring.get_keyring()
    module = type(backend).__module__
    in_test_process = "pytest" in sys.modules or "unittest" in sys.modules
    if (
        in_test_process
        and not getattr(sys, "frozen", False)
        and module.startswith("keyring.backends.")
        and module not in _INERT_BACKEND_MODULES
    ):
        raise RuntimeError(
            f"Refusing to use the real OS keyring ({module}) from a test process. "
            "Install a test backend with keyring.set_keyring() first — "
            "backend/tests/conftest.py does this for pytest. See #2287."
        )
    return backend


def available() -> bool:
    """Whether a usable secret store backs this process. The `fail` backend
    (no store found) reports priority 0 and `null` reports -1."""
    return getattr(_backend(), "priority", 0) > 0


def get(field: str) -> str:
    """The stored key for `field`, or "" when there is none or the store errs."""
    try:
        return _backend().get_password(service_name(), field) or ""
    except KeyringError:
        logger.warning("Could not read %s from the OS secret store.", field, exc_info=True)
        return ""


def put(field: str, value: str) -> bool:
    """Store `value` for `field` — an empty value deletes the entry. Returns
    whether the store now holds exactly `value`; on False the caller keeps the
    key where it was rather than lose it."""
    backend = _backend()
    service = service_name()
    try:
        if value:
            if backend.get_password(service, field) != value:
                backend.set_password(service, field, value)
        else:
            # Nothing stored is already the state we want.
            with contextlib.suppress(PasswordDeleteError):
                backend.delete_password(service, field)
    except KeyringError:
        logger.warning("Could not write %s to the OS secret store.", field, exc_info=True)
        return False
    return True
