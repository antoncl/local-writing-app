"""The writer's reading page for the judge's calibration (#2615).

  calibration_serve.py DIR [--port 0]

Serves DIR/answers.yaml (from `calibration.py sheet`) as a local page on 127.0.0.1: one passage at a
time, each rule's question answered Yes / No / Not sure, an optional note. Every change is written
to answers.yaml at once, so work stops and resumes anywhere. The API serves only what the sheet
shows the writer: never the judge's verdicts, whether a passage is seeded, or its model or case.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
import threading
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_gen import load_book  # noqa: E402
from judge import RULES, passage_context, question_sha  # noqa: E402

PAGE = Path(__file__).resolve().parent / "calibration_page.html"
ANSWERS = ("yes", "no", "unsure")
MAX_BODY = 1 << 20
ITEM_PATH = re.compile(r"^/api/items/([\w-]+)$")
SERVING = ".serving"  # in DIR while the page runs: holds its pid and port, so `extend` leaves answers.yaml alone


def item_status(item: dict[str, Any]) -> str:
    """`untouched`, `partial` or `done` (every rule answered; "unsure" counts as answered)."""
    given = sum(1 for rule in RULES if (item.get("answers") or {}).get(rule) in ANSWERS)
    return "untouched" if given == 0 else "done" if given == len(RULES) else "partial"


def item_payload(item: dict[str, Any], book: dict[str, Any], text: str) -> dict[str, Any]:
    """What the page may know about one item: its passage, context, questions and the writer's own
    answers. Nothing that tells a seeded passage from a natural one, nor any judge file."""
    context = passage_context(book, item)
    return {
        "id": item["id"],
        "kind": "continuation" if item["prompt"] == "continue" else "scene",
        "pov": context["pov"],
        "context": context.get("lead_in") or context["summary"],
        "text": text.strip(),
        "questions": [{"rule": rule, "question": question} for rule, question in RULES.items()],
        "answers": {rule: (item.get("answers") or {}).get(rule) for rule in RULES},
        "note": item.get("note") or "",
    }


def apply_answer(doc: dict[str, Any], item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """A copy of `doc` with the payload's answers and note applied to item `item_id`.
    Raises ValueError for an unknown id or rule, a value other than yes/no/unsure/null, or a non-string note."""
    out = copy.deepcopy(doc)
    item = next((i for i in out["items"] if i["id"] == item_id), None)
    if item is None:
        raise ValueError(f"unknown item {item_id!r}")
    answers = payload.get("answers", {})
    if not isinstance(answers, dict):
        raise ValueError("answers must be an object")
    for rule, value in answers.items():
        if rule not in RULES:
            raise ValueError(f"unknown rule {rule!r}")
        if value is not None and value not in ANSWERS:
            raise ValueError(f"bad answer {value!r} for {rule}")
    note = payload.get("note", item.get("note") or "")
    if not isinstance(note, str):
        raise ValueError("note must be a string")
    item["answers"] = {**dict.fromkeys(RULES), **(item.get("answers") or {}), **answers}
    # Each answer records the wording it answered, so a reworded question never counts it in the tally.
    item["question_sha"] = {k: v for k, v in (item.get("question_sha") or {}).items() if k not in answers}
    item["question_sha"].update({rule: question_sha(RULES[rule]) for rule, value in answers.items() if value is not None})
    item["note"] = note
    return out


def write_atomic(path: Path, doc: dict[str, Any]) -> None:
    """Write the YAML to a temp file beside `path`, then replace it, so a crash never leaves half a file."""
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(doc, handle, sort_keys=False)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def draft_text(doc: dict[str, Any], item: dict[str, Any]) -> str:
    run = Path(item.get("run") or doc["run"])
    path = run / item["case"] / item["model"] / item["prompt"] / item["brief"] / f"draft_{item['n']}.md"
    return path.read_text(encoding="utf-8")


class Store:
    """answers.yaml on disk, read fresh per request and written under one lock."""

    def __init__(self, directory: Path) -> None:
        self.path = directory / "answers.yaml"
        self.book = load_book()
        self.lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        return yaml.safe_load(self.path.read_text(encoding="utf-8"))

    def listing(self) -> dict[str, Any]:
        with self.lock:
            items = [{"id": i["id"], "status": item_status(i)} for i in self.load()["items"]]
        return {"items": items, "done": sum(i["status"] == "done" for i in items), "total": len(items)}

    def payload(self, item_id: str) -> dict[str, Any] | None:
        with self.lock:
            doc = self.load()
            item = next((i for i in doc["items"] if i["id"] == item_id), None)
            return None if item is None else item_payload(item, self.book, draft_text(doc, item))

    def answer(self, item_id: str, payload: dict[str, Any]) -> dict[str, str]:
        with self.lock:
            doc = apply_answer(self.load(), item_id, payload)
            write_atomic(self.path, doc)
            return {"status": item_status(next(i for i in doc["items"] if i["id"] == item_id))}


def request_allowed(method: str, headers: Mapping[str, str], port: int) -> bool:
    """Whether a request may be served: its Host is this server's own (a foreign one is DNS rebinding) and,
    for a POST, its Origin (if sent) is this server's page and its body is JSON (so no cross-site form)."""
    own = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if headers.get("Host") not in own:
        return False
    if method != "POST":
        return True
    origin = headers.get("Origin")
    if origin is not None and origin not in {f"http://{host}" for host in own}:
        return False
    return (headers.get("Content-Type") or "").split(";")[0].strip().lower() == "application/json"


def route_get(store: Store, path: str) -> tuple[int, Any]:
    """`(status, body)` for a GET; the page is bytes, everything else JSON-able."""
    if path in ("/", "/index.html"):
        return HTTPStatus.OK, PAGE.read_bytes()
    if path == "/api/items":
        return HTTPStatus.OK, store.listing()
    match = ITEM_PATH.match(path)
    try:
        payload = store.payload(match.group(1)) if match else None
    except OSError as exc:
        return HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"draft file missing: {exc.filename or exc}"}
    return (HTTPStatus.OK, payload) if payload else (HTTPStatus.NOT_FOUND, {"error": "not found"})


def route_post(store: Store, path: str, raw: bytes) -> tuple[int, Any]:
    """`(status, body)` for a POST to /api/items/<id>; a bad body or answer is a 400."""
    match = ITEM_PATH.match(path)
    if not match:
        return HTTPStatus.NOT_FOUND, {"error": "not found"}
    try:
        payload = json.loads(raw or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("body must be an object")
        return HTTPStatus.OK, store.answer(match.group(1), payload)
    except ValueError as exc:  # includes bad JSON
        return HTTPStatus.BAD_REQUEST, {"error": str(exc)}


def make_handler(store: Store) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base signature
            pass

        def _reply(self, status: int, body: Any) -> None:
            is_page = isinstance(body, bytes)
            data = body if is_page else json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if is_page else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self, method: str) -> bool:
            if request_allowed(method, self.headers, self.server.server_address[1]):
                return True
            self._reply(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            return False

        def do_GET(self) -> None:
            if not self._allowed("GET"):
                return
            self._reply(*route_get(store, self.path))

        def do_POST(self) -> None:
            if not self._allowed("POST"):
                return
            size = int(self.headers.get("Content-Length") or 0)
            if size > MAX_BODY:
                self._reply(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
                return
            self._reply(*route_post(store, self.path, self.rfile.read(size)))

    return Handler


def make_server(directory: Path, port: int = 0) -> ThreadingHTTPServer:
    """A server for DIR/answers.yaml, bound to 127.0.0.1 only (port 0 lets the OS pick)."""
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(Store(directory)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("directory", type=Path, help="the folder `calibration.py sheet` wrote")
    parser.add_argument("--port", type=int, default=0, help="default: any free port")
    args = parser.parse_args()
    if not (args.directory / "answers.yaml").is_file():
        raise SystemExit(f"No answers.yaml in {args.directory}: run `calibration.py sheet` first.")
    server = make_server(args.directory, args.port)
    marker = args.directory / SERVING
    marker.write_text(json.dumps({"pid": os.getpid(), "port": server.server_address[1]}), encoding="utf-8")
    print(f"Calibration page: http://127.0.0.1:{server.server_address[1]}/  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        marker.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
