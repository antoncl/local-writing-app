"""Parity check: the harness's chat against the same brief run by hand in the app (#2613).

The harness mirrors the frontend's call sequence rather than calling it, so the
mirror needs a guard (measuring-prose-quality.md §7, "The guard on the mirror").
This compares the fields the harness mirrors from the frontend's lock record
(lib/chat/chatSessionRecord.svelte.ts::toPayload, components/editor/body/chat/
promptTemplateLock.ts):

  system_prompt (exact), messages up to and including the first user turn,
  used_node_ids (as sets), used_node_hints, used_snapshots, field_contract_stored,
  inputs (after json-decoding the context_pick strings), lore_enabled, lore_free.

The harness side is a `meta_<n>.json` (its `chat_record`). The hand run's side is
its chat id, read through the backend with `--case <case>`, so both records come
through the same route. Run the hand run in the SAME fixture project so node ids
line up. Prints every difference; exits 1 on any.

    parity.py RUN/frank/<model>/draft_scene/short_column/meta_1.json chat_<id> --case frank
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_chat(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("chat_record", data)


def head_messages(messages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """role/content up to and including the first user turn."""
    head: list[tuple[str, str]] = []
    for m in messages:
        head.append((m["role"], m["content"]))
        if m["role"] == "user":
            break
    return head


def decode_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """json-decode a list/object-shaped string (a context_pick's wire string)."""
    out: dict[str, Any] = {}
    for name, value in inputs.items():
        if isinstance(value, str) and value.strip()[:1] in ("[", "{"):
            try:
                out[name] = json.loads(value)
                continue
            except ValueError:
                pass
        out[name] = value
    return out


def _sorted_json(value: Any) -> list[str]:
    return sorted(json.dumps(v, sort_keys=True) for v in value)


def compare(harness: dict[str, Any], app: dict[str, Any]) -> list[str]:
    diffs: list[str] = []

    def check(label: str, a: Any, b: Any) -> None:
        if a != b:
            diffs.append(f"{label}\n  harness: {a!r}\n  app:     {b!r}")

    check("system_prompt", harness.get("system_prompt"), app.get("system_prompt"))
    check("messages (to first user turn)", head_messages(harness.get("messages", [])), head_messages(app.get("messages", [])))
    check("used_node_ids", set(harness.get("used_node_ids") or []), set(app.get("used_node_ids") or []))
    check("used_node_hints", harness.get("used_node_hints") or {}, app.get("used_node_hints") or {})
    check("used_snapshots", _sorted_json(harness.get("used_snapshots") or []), _sorted_json(app.get("used_snapshots") or []))
    check("field_contract_stored", harness.get("field_contract_stored") or [], app.get("field_contract_stored") or [])
    check("inputs", decode_inputs(harness.get("inputs") or {}), decode_inputs(app.get("inputs") or {}))
    check("lore_enabled", bool(harness.get("lore_enabled")), bool(app.get("lore_enabled")))
    check("lore_free", bool(harness.get("lore_free")), bool(app.get("lore_free")))
    return diffs


def fetch_chat(case: str, chat_id: str) -> dict[str, Any]:
    """A chat as the backend serves it — the same reader run.py uses for its own records,
    so neither side parses the on-disk format."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fixture_gen import load_fixture
    from lwa_client import Client, discover_backend

    project = Client(discover_backend(), load_fixture(case)["root"])
    try:
        return project.get(f"/api/chats/{chat_id}")
    finally:
        project.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("harness", type=Path, help="a harness meta_<n>.json (or a chat saved as JSON)")
    parser.add_argument("app", help="the hand run's chat id (read from the backend), or a chat saved as JSON")
    parser.add_argument("--case", help="the fixture case the hand run used; required with a chat id")
    args = parser.parse_args()
    if Path(args.app).is_file():
        app = load_chat(Path(args.app))
    elif args.case:
        app = fetch_chat(args.case, args.app)
    else:
        parser.error("give --case with a chat id")
    diffs = compare(load_chat(args.harness), app)
    for diff in diffs:
        print(f"DIFFERENT: {diff}")
    if diffs:
        sys.exit(1)
    print("parity: the harness's chat matches the hand run on every mirrored field.")


if __name__ == "__main__":
    main()
