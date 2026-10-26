"""The builder test of the prose harness (#2623, measuring-prose-quality.md §4.3).

  builder.py run --out BUILD_OUT [--models M ...] [--authors KEY ...]
  builder.py report BUILD_OUT

For each builder model (`--models`, default every model in models.yaml) and each of four authors
(`fixture/authors.yaml`, public-domain pages) the built-in style builder (*Build a style note*,
`backend/app/builtin_library/prompts/build-a-style-note.md`, in a project of its own) is handed the pages and asked to infer the style note. The
judge is then shown each of the author's three held-out excerpts with that model's four notes,
unlabelled, and says which note describes the writing. Bar, per model: 9 of 12 excerpts matched
to the right note; a note that names the author or the work fails outright. No drafting (§4.3).

Everything goes through the dev backend's routes, in the sequence run.py mirrors for Draft scene:
  GET  /api/prompts                         the built-in is read from the project's prompt listing,
                                             as the frontend lists it; its id is recorded in the
                                             workspace's fixture.json under `prompt`.
  POST /api/chats ... POST /api/ai/chat/stream  as run.drive_draft_scene, with no entry picked
  POST /api/ai/entry-draft/extract           routers/ai.py::extract_entry_draft, the create-mode
                                             extraction chatCommit.svelte.ts runs for a NEW lore:style_note
                                             (`draftExtractHost`); read-only, the note is never written

Resumable: a built note and an answered match already on disk are kept.
Layout under BUILD_OUT: notes/<model>/<key>.json|.md, matches/<model>/<key>_<i>.json, result.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from functools import partial
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from builder_core import (  # noqa: E402
    BUILDER_PROMPT,
    BUILDER_TITLE,
    EXCERPTS_PER_AUTHOR,
    FOLLOW_UP,
    LABELS,
    MAX_FOLLOW_UPS,
    NOTE_TYPE,
    SYSTEM_MATCH,
    first_user_turn,
    leaks,
    load_authors,
    match_message,
    match_order,
    needs_follow_up,
    render_result,
    tally,
)
from fixture_gen import builder_root, ensure_project, load_book, write_json  # noqa: E402
from judge import CALL_TIMEOUT_S, ask, is_done, pick_judge  # noqa: E402
from lwa_client import Client, discover_backend  # noqa: E402
from run import (  # noqa: E402
    StepFailed,
    assistant_message,
    cache_slots,
    chat_payload,
    cost_of,
    done_summary,
    open_chat,
    preview_lock,
    run_cell,
)
from setup_backend import load_judges, load_models, select_models, setup_project  # noqa: E402

# run_cell's `kind` for the builder chat: it takes the chat record the way a Draft scene chat does.
CHAT_KIND = "draft_scene"
BUILDER_MAX_TOKENS = 8192


def ensure_prompt(project: Client) -> dict[str, Any]:
    """The built-in builder as the project lists it (the listing record carries the effective inputs).
    Read, never installed: a project copy would sit beside the built-in under the same title."""
    for entry in project.get("/api/prompts")["entries"]:
        if entry.get("title") == BUILDER_TITLE:
            return entry
    raise SystemExit(f"No built-in prompt titled {BUILDER_TITLE!r}: is the backend serving this checkout?")


def ensure_workspace(base_url: str, book: dict[str, Any], key: str, assistants: list[dict[str, Any]]) -> dict[str, Any]:
    """The author's builder project: no style note, the built-in builder, an assistant per
    builder model and judge (the judge matches in the same project)."""
    fixture = ensure_project(base_url, book, builder_root(key))
    # The builder reads the rules off the pages and then writes the note, often in one reply: give
    # its assistants room (a 4096 cap cut Sonnet off mid-note, #2624). Only this workspace's
    # assistants; the drafting projects keep the drafting cap the baseline was run with.
    roomy = [{**a, "max_tokens": max(a.get("max_tokens") or 0, BUILDER_MAX_TOKENS)} for a in assistants]
    fixture["assistants"] = setup_project(base_url, fixture["root"], fixture.get("assistants", {}), roomy)
    project = Client(base_url, fixture["root"])
    try:
        fixture["prompt"] = ensure_prompt(project)["id"]
    finally:
        project.close()
    write_json(builder_root(key), fixture)
    return fixture


def stream_turn(
    project: Client, chat: dict[str, Any], assistant_id: str, lock: dict[str, Any],
    history: list[dict[str, Any]], meta: dict[str, Any],
) -> str:
    """Send the history, append and save the reply as the app does; a truncated reply is out of reach."""
    text, done = project.stream_ndjson(
        "/api/ai/chat/stream",
        {
            "assistant_id": assistant_id,
            "system_prompt": lock["system_prompt"],
            "messages": [{"role": m["role"], "content": m["content"]} for m in history],
            "chat_id": chat["id"],
        },
    )
    meta["stream"] = done_summary(done)
    meta["cost_usd"] = cost_of(meta.get("cost_usd"), done.get("cost_usd"))
    history.append(assistant_message(text, done))
    project.put(f"/api/nodes/{chat['id']}", {**chat_payload(chat, assistant_id, lock, history, {}), **cache_slots(done)})
    if done.get("truncated"):
        raise StepFailed("out_of_reach", "the reply was truncated")
    return text


def extract_note(
    project: Client, assistant_id: str, chat_id: str, history: list[dict[str, Any]], meta: dict[str, Any]
) -> tuple[str, str]:
    """The create-mode extraction for a new style note; returns `(title, body)`. Read-only."""
    result = project.post(
        "/api/ai/entry-draft/extract",
        {
            "messages": [{"role": m["role"], "content": m["content"]} for m in history],
            "assistant_id": assistant_id, "chat_id": chat_id, "entry_type": NOTE_TYPE,
        },
    )
    patch = result.get("patch") or {}
    meta["extraction"] = {
        "ok": result.get("ok"), "error": result.get("error"), "garbled": patch.get("garbled"),
        "garbled_reason": patch.get("garbled_reason"), "cost_usd": result.get("cost_usd"),
        "usage": result.get("usage"),
    }
    meta["cost_usd"] = cost_of(meta.get("cost_usd"), result.get("cost_usd"))
    if not result.get("ok") or not result.get("patch"):
        raise StepFailed("error", result.get("error") or "The model returned nothing to commit.")
    if patch.get("garbled") or not patch.get("body"):
        raise StepFailed("out_of_reach", f"no usable note: {patch.get('garbled_reason') or 'no body'}")
    return (patch.get("fields") or {}).get("title") or "Inferred style", patch["body"]


def converse(
    project: Client, prompt: dict[str, Any], assistant_id: str, author: dict[str, Any], meta: dict[str, Any]
) -> str:
    """The builder conversation for one author; the note's body, with its title in `meta`."""
    chat = open_chat(project, prompt, assistant_id, f"Style builder - {author['key']}", "", {})
    meta["chat_id"] = chat["id"]
    # No entry picked, no inherited notes: every input is left blank, as for a writer who fills in nothing.
    lock, preview = preview_lock(project, prompt, assistant_id, {}, "")
    meta["cache_blocks"] = preview.get("cache_blocks")
    history = list(lock["turns"])
    project.put(f"/api/nodes/{chat['id']}", chat_payload(chat, assistant_id, lock, history, {}))
    history.append({"role": "user", "content": first_user_turn(author["pages"])})
    meta["follow_ups"] = 0
    while True:
        reply = stream_turn(project, chat, assistant_id, lock, history, meta)
        meta["turns"] = len(history)
        if not needs_follow_up(reply):
            break
        if meta["follow_ups"] == MAX_FOLLOW_UPS:
            meta["reply"] = reply
            raise StepFailed("out_of_reach", f"no proposed note after {MAX_FOLLOW_UPS} follow-ups")
        meta["follow_ups"] += 1
        history.append({"role": "user", "content": FOLLOW_UP})
    meta["note_title"], body = extract_note(project, assistant_id, chat["id"], history, meta)
    return body


def note_record(key: str, body: str, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": key, "status": meta["status"], "note_title": meta.get("note_title"), "note_body": body or None,
        "turns": meta.get("turns"), "follow_ups": meta.get("follow_ups"), "chat_id": meta.get("chat_id"),
        "cost_usd": meta.get("cost_usd"), "chat_record": meta.get("chat_record"),
        **{k: meta[k] for k in ("error", "extraction", "reply", "attempts", "wall_s", "stream") if k in meta},
    }


def build_note(
    base_url: str, fixture: dict[str, Any], author: dict[str, Any], builder: dict[str, Any], out: Path
) -> dict[str, Any]:
    """Run (or resume) the builder for one author with one model; saves notes/<model>/<key>.json and,
    when ok, .md."""
    path = out / "notes" / builder["name"] / f"{author['key']}.json"
    label = f"{builder['name']}/{author['key']}"
    if path.is_file():
        kept = json.loads(path.read_text(encoding="utf-8"))
        if kept["status"] != "error":
            print(f"{label}: note kept ({kept['status']})", flush=True)
            return kept
    project = Client(base_url, fixture["root"])
    try:
        # The listing record, as run.py uses: it carries `effective_inputs`, which the preview
        # seeds as blank values (a single GET doesn't, and the template then sees no `entry`).
        prompt = next(e for e in project.get("/api/prompts")["entries"] if e["id"] == fixture["prompt"])
        drive = partial(converse, project, prompt, fixture["assistants"][builder["name"]], author)
        body, meta = run_cell(project, CHAT_KIND, drive, 0)
    finally:
        project.close()
    record = note_record(author["key"], body, meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    if record["status"] == "ok":
        path.with_suffix(".md").write_text(body, encoding="utf-8")
    found = leaks(body, author["leak_terms"])
    print(f"{label}: note {record['status']}, {record['follow_ups']} follow-ups, leaks: {found or 'none'}", flush=True)
    return record


def match_excerpts(
    base_url: str, fixtures: dict[str, dict[str, Any]], authors: list[dict[str, Any]],
    builder: dict[str, Any], out: Path,
) -> None:
    """The judge's match for every excerpt not yet answered, saved as matches/<model>/<key>_<i>.json.
    Needs every author's note from `builder` to be ok; otherwise no trial of this model can run."""
    model, keys = builder["name"], [a["key"] for a in authors]
    bodies = {}
    for key in keys:
        path = out / "notes" / model / f"{key}.json"
        note = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if note.get("status") != "ok":
            print(f"{model}: no ok note for {key}; its matches are out of reach", flush=True)
            return
        bodies[key] = note["note_body"]
    judges = load_judges()
    which = pick_judge(builder["model"], judges)
    for author in authors:
        key = author["key"]
        client = Client(base_url, fixtures[key]["root"], timeout=CALL_TIMEOUT_S)
        try:
            for i in range(EXCERPTS_PER_AUTHOR):
                path = out / "matches" / model / f"{key}_{i}.json"
                if path.is_file() and is_done(json.loads(path.read_text(encoding="utf-8"))):
                    continue
                order = match_order(model, key, i, keys)
                message = match_message(author["excerpts"][i], [bodies[k] for k in order])
                choices = tuple(LABELS[: len(order)])
                assistant = fixtures[key]["assistants"][judges[which]["name"]]
                verdict = ask(client, assistant, SYSTEM_MATCH, message, choices)
                record = {"order": order, **verdict, "judge": which, "judge_model": judges[which]["model"]}
                record["correct"] = order[choices.index(verdict["answer"])] == key if verdict["answer"] in choices else None
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(record, indent=2), encoding="utf-8")
                print(f"{model}/{key}_{i} [{which}]: {verdict['answer']} correct={record['correct']}", flush=True)
        finally:
            client.close()


def collect(out: Path) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """The model names and every note and match record under BUILD_OUT, as `core.tally` takes them."""
    notes: dict[str, dict[str, Any]] = {}
    matches: dict[str, dict[str, Any]] = {}
    for folder in sorted((out / "notes").glob("*")):
        notes[folder.name] = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))}
        matches[folder.name] = {
            p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "matches" / folder.name).glob("*.json"))
        }
    return sorted(notes), notes, matches


def report(out: Path) -> str:
    models, notes, matches = collect(out)
    built = {key for model_notes in notes.values() for key in model_notes}
    authors = [a for a in load_authors() if a["key"] in built]
    text = render_result(tally(notes, matches, authors, models))
    (out / "result.md").write_text(text, encoding="utf-8")
    return text


def stamp_builder(out: Path) -> None:
    """Record which builder text BUILD_OUT was made with, and refuse a different one: kept notes
    are reused, so a changed builder would mix two versions in one result."""
    sha = hashlib.sha256(BUILDER_PROMPT.read_bytes()).hexdigest()
    path = out / "builder.json"
    if path.is_file():
        made = json.loads(path.read_text(encoding="utf-8")).get("builder_sha256")
        if made != sha:
            raise SystemExit(f"{out} was made with a different builder text: use a new --out to measure this one.")
        return
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"builder_sha256": sha}, indent=2), encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    base_url = discover_backend()
    models = select_models(load_models(), args.models)
    judges = list(load_judges().values())
    names = [m["name"] for m in [*models, *judges]]
    if len(names) != len(set(names)):
        raise SystemExit(f"Model and judge names must be distinct: {', '.join(sorted(names))}")
    book = load_book()
    authors = [a for a in load_authors() if not args.authors or a["key"] in args.authors]
    out = args.out
    stamp_builder(out)
    # Always (re)set each workspace's assistants, not only when work is pending: a changed setting
    # (a judge's output cap, say) must reach the judge before it matches.
    fixtures = {a["key"]: ensure_workspace(base_url, book, a["key"], [*models, *judges]) for a in authors}
    for model in models:
        for author in authors:
            build_note(base_url, fixtures[author["key"]], author, model, out)
        match_excerpts(base_url, fixtures, authors, model, out)
    print(report(out))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="build the notes, match the excerpts to them, report")
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--models", nargs="+", help="builder models from models.yaml (default: all)")
    run_parser.add_argument("--authors", nargs="+", choices=[a["key"] for a in load_authors()])
    report_parser = sub.add_parser("report", help="print and write result.md for a BUILD_OUT")
    report_parser.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        run(args)
    else:
        print(report(args.out))


if __name__ == "__main__":
    main()
