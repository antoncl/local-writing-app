"""A thin HTTP client for the prose harness (#2613, measuring-prose-quality.md §7).

Why it exists: the harness drives a worktree dev backend over HTTP, in the same
call sequence the frontend uses, so every call runs the real backend code. This
is the one place the harness touches the network, mirroring `lib/api/core.ts`
(`request`, `streamNdjson`, `scopeHeaders`): the `X-Project-Root` header carries
the request's scope (`backend/app/runtime.py::root_from_header`), URL-encoded
like the frontend's `encodeURIComponent`.

`discover_backend()` reads the port `scripts/dev_backend.py` publishes to
`tmp/dev-backend-port` for *this checkout*. It refuses a missing file and refuses
:8787 outright, so the harness can never drive the writer's own server.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

REPO = Path(__file__).resolve().parents[3]
PORT_FILE = REPO / "tmp" / "dev-backend-port"
USER_PORT = 8787

# Routes the frontend calls before any project is open (or that are machine-wide),
# so they run unscoped: the create/open handlers take no `CurrentProject`, and
# machine settings are not project state.
UNSCOPED_PATHS = ("/api/project/open", "/api/project/create", "/api/settings/machine")

# A local 9B model writing a full scene plus its commit can take many minutes.
DEFAULT_TIMEOUT_S = 1800.0


class ApiError(RuntimeError):
    """A non-2xx response, or an `error` line on a stream."""


def discover_backend() -> str:
    """Base URL of this checkout's dev backend, or exit with a message.

    Format (scripts/dev_backend.py, `PORT_FILE.write_text(str(port))`): the bare
    port number. A missing file means no dev backend is up for this tree; port
    8787 is the writer's own server and is never ours to drive.
    """
    if not PORT_FILE.is_file():
        sys.exit(
            f"No dev backend published at {PORT_FILE}. Start one first: "
            "python scripts/dev_backend.py (backgrounded)."
        )
    raw = PORT_FILE.read_text(encoding="utf-8").strip()
    try:
        port = int(raw)
    except ValueError:
        sys.exit(f"{PORT_FILE} does not hold a port number: {raw!r}")
    if port == USER_PORT:
        sys.exit(f"Refusing to drive port {USER_PORT}: that is the user's own server, not a dev backend.")
    return f"http://127.0.0.1:{port}"


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
    return detail[:500] if isinstance(detail, str) else json.dumps(detail)[:500]


class Client:
    """Scoped JSON client. `project_root` becomes the `X-Project-Root` header."""

    def __init__(
        self, base_url: str, project_root: Path | str | None = None, timeout: float = DEFAULT_TIMEOUT_S
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.project_root = str(Path(project_root).resolve()) if project_root is not None else None
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, trust_env=False)

    def _headers(self, path: str) -> dict[str, str]:
        if self.project_root is None or path in UNSCOPED_PATHS:
            return {}
        return {"X-Project-Root": quote(self.project_root, safe="")}

    def request(self, method: str, path: str, body: Any = None) -> Any:
        response = self._http.request(method, path, json=body, headers=self._headers(path))
        if not response.is_success:
            raise ApiError(f"{method} {path} -> {response.status_code}: {_detail(response)}")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, body if body is not None else {})

    def put(self, path: str, body: Any) -> Any:
        return self.request("PUT", path, body)

    def patch(self, path: str, body: Any) -> Any:
        return self.request("PATCH", path, body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    def stream_ndjson(self, path: str, body: Any) -> tuple[str, dict[str, Any]]:
        """POST to a streaming route. Returns `(text, done_line)`.

        `text` joins every `delta`. The `done` dict also carries `_thinking`, the
        joined `thinking` text (the chat record stores it per message). A
        `{"type":"error"}` line, a non-2xx status, or a stream that ends without
        `done` raises `ApiError`.
        """
        text: list[str] = []
        thinking: list[str] = []
        done: dict[str, Any] | None = None
        with self._http.stream("POST", path, json=body, headers=self._headers(path)) as response:
            if not response.is_success:
                response.read()
                raise ApiError(f"POST {path} -> {response.status_code}: {_detail(response)}")
            for line in response.iter_lines():
                if not line.strip():
                    continue
                event = json.loads(line)
                kind = event.get("type")
                if kind == "delta":
                    text.append(event.get("text", ""))
                elif kind == "thinking":
                    thinking.append(event.get("text", ""))
                elif kind == "done":
                    done = event
                elif kind == "error":
                    raise ApiError(f"POST {path} stream error: {event.get('error') or event}")
        if done is None:
            raise ApiError(f"POST {path}: the stream ended before its done line")
        return "".join(text), {**done, "_thinking": "".join(thinking)}

    def close(self) -> None:
        self._http.close()
