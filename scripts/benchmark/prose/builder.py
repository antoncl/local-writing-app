"""The builder test of the prose harness (#2623, measuring-prose-quality.md §4.3).

  builder.py run --out BUILD_OUT [--models M ...] [--drafts 3] [--brief KEY] [--authors KEY ...]
  builder.py report BUILD_OUT

For each of four authors (`fixture/authors.yaml`, public-domain pages) the style builder
(`fixture/style-builder.md`, installed in a project of its own) is handed the pages and asked to
infer the style note. The note is then given to Draft scene, a brief is drafted `--drafts` times per
model, and the judge says which of the four authors' excerpts, unnamed, each draft is closest to.
Bar: 9 of 12 attributed correctly; a note that names the author or the work fails outright.

Everything goes through the dev backend's routes, in the sequence run.py mirrors for Draft scene:
  POST /api/prompts, PUT /api/prompts/{id}   routers/lore.py; lib/api/prompts.ts (createPromptEntry,
                                             savePromptEntry). The app mints the prompt's id, so the
                                             front matter's `id` is not sent; the id used is recorded
                                             in the workspace's fixture.json under `prompt`.
  POST /api/chats ... POST /api/ai/chat/stream  as run.drive_draft_scene, with no entry picked
  POST /api/ai/entry-draft/extract           routers/ai.py::extract_entry_draft, the create-mode
                                             extraction chatCommit.svelte.ts runs for a NEW lore:note
                                             (`draftExtractHost`); read-only, the note is never written

Resumable: a built note, a draft and an attribution already on disk are kept.
Layout under BUILD_OUT: notes/<key>.json|.md, drafts/<key>/<model>/draft_scene/<brief>/draft_<n>.md
(+ meta_<n>.json, attribution_<n>.json), result.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import partial
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from builder_core import (  # noqa: E402
    BUILDER_PROMPT,
    FOLLOW_UP,
    MAX_FOLLOW_UPS,
    SYSTEM_ATTRIBUTION,
    attribution_message,
    excerpt_order,
    first_user_turn,
    leaks,
    load_authors,
    needs_follow_up,
    render_result,
    split_front_matter,
    tally,
)
from checks import iter_drafts  # noqa: E402
from fixture_gen import builder_root, ensure_project, load_book, write_json  # noqa: E402
from judge import CALL_TIMEOUT_S, ask, is_done, pick_judge  # noqa: E402
from lwa_client import ApiError, Client, discover_backend  # noqa: E402
from run import (  # noqa: E402
    StepFailed,
    assistant_message,
    cache_slots,
    chat_payload,
    cost_of,
    done_summary,
    drive_draft_scene,
    find_prompts,
    open_chat,
    preview_lock,
    run_cell,
    write_draft,
)
from setup_backend import load_judges, load_models, select_models, setup_project  # noqa: E402

BRIEF_PROMPT = "draft_scene"
# run_cell's `kind` for the builder chat: it takes the chat record the way a Draft scene chat does.
CHAT_KIND = "draft_scene"


def ensure_prompt(project: Client, known_id: str | None) -> dict[str, Any]:
    """Install style-builder.md as a project prompt (or update the one recorded) and read it back."""
    front, body = split_front_matter(BUILDER_PROMPT.read_text(encoding="utf-8"))
    entry = None
    if known_id:
        try:
            entry = project.get(f"/api/prompts/{known_id}")
        except ApiError:
            entry = None
    if entry is None:
        entry = project.post("/api/prompts", {"title": front["title"], "entry_type": front["entry_type"]})
    saved = project.put(
        f"/api/prompts/{entry['id']}",
        {
            "title": front["title"], "body": body, "base_revision": entry["revision"],
            "entry_type": front["entry_type"], "metadata": {}, "inputs": front["inputs"],
            "offer_on": front.get("offer_on", []), "context_strategy": front.get("context_strategy"),
        },
    )
    return project.get(f"/api/prompts/{saved['id']}")


def ensure_workspace(base_url: str, book: dict[str, Any], key: str, builder: dict[str, Any]) -> dict[str, Any]:
    """The author's builder project: no style note, the builder prompt installed, an assistant for it."""
    fixture = ensure_project(base_url, book, builder_root(key))
    fixture["assistants"] = setup_project(base_url, fixture["root"], fixture.get("assistants", {}), [builder])
    project = Client(base_url, fixture["root"])
    try:
        fixture["prompt"] = ensure_prompt(project, fixture.get("prompt"))["id"]
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
    """The create-mode extraction for a new lore:note; returns `(title, body)`. Read-only."""
    result = project.post(
        "/api/ai/entry-draft/extract",
        {
            "messages": [{"role": m["role"], "content": m["content"]} for m in history],
            "assistant_id": assistant_id, "chat_id": chat_id, "entry_type": "lore:note",
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


def build_note(base_url: str, book: dict[str, Any], author: dict[str, Any], builder: dict[str, Any], out: Path) -> dict[str, Any]:
    """Run (or resume) the builder for one author; saves notes/<key>.json and, when ok, .md."""
    path = out / "notes" / f"{author['key']}.json"
    if path.is_file():
        kept = json.loads(path.read_text(encoding="utf-8"))
        if kept["status"] != "error":
            print(f"{author['key']}: note kept ({kept['status']})", flush=True)
            return kept
    fixture = ensure_workspace(base_url, book, author["key"], builder)
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
    print(f"{author['key']}: note {record['status']}, {record['follow_ups']} follow-ups, leaks: {found or 'none'}", flush=True)
    return record


def draft_folder(out: Path, key: str, model: str, brief: str) -> Path:
    return out / "drafts" / key / model / BRIEF_PROMPT / brief


def pending_drafts(out: Path, key: str, models: list[dict[str, Any]], brief: str, count: int) -> list[tuple[dict[str, Any], int]]:
    """The `(model, n)` drafts of `brief` not yet on disk."""
    return [
        (m, n) for m in models for n in range(1, count + 1)
        if not (draft_folder(out, key, m["name"], brief) / f"draft_{n}.md").is_file()
    ]


def drafting_fixture(
    base_url: str, book: dict[str, Any], key: str, note: dict[str, Any], models: list[dict[str, Any]]
) -> dict[str, Any]:
    """The author's drafting project (the inferred note as its style note) with an assistant per model."""
    root = builder_root(key, drafts=True)
    fixture = ensure_project(base_url, book, root, {"title": note["note_title"], "body": note["note_body"]})
    fixture["assistants"] = setup_project(base_url, fixture["root"], fixture.get("assistants", {}), models)
    write_json(root, fixture)
    return fixture


def draft_pending(
    base_url: str, fixture: dict[str, Any], key: str, todo: list[tuple[dict[str, Any], int]], brief: str, out: Path
) -> None:
    """Draft `brief` for each pending `(model, n)` with Draft scene and save it as run.py does."""
    project = Client(base_url, fixture["root"])
    try:
        prompt = find_prompts(project.get("/api/prompts")["entries"])[BRIEF_PROMPT]
        for model, n in todo:
            drive = partial(drive_draft_scene, project, prompt, fixture["assistants"][model["name"]], fixture["scenes"][brief], n)
            draft, meta = run_cell(project, BRIEF_PROMPT, drive, 0)
            write_draft(draft_folder(out, key, model["name"], brief), n, draft, meta)
            print(f"{key}/{model['name']}/{brief} #{n}: {meta['status']}", flush=True)
    finally:
        project.close()


def attribute_drafts(base_url: str, out: Path, model_ids: dict[str, str]) -> None:
    """The judge's attribution for every ok draft that has none yet, saved as attribution_<n>.json."""
    authors = {a["key"]: a for a in load_authors()}
    judges = load_judges()
    clients: dict[str, Client] = {}
    try:
        for item in iter_drafts(out / "drafts"):
            if item["meta"].get("status", "ok") != "ok":
                continue
            key, model, n = item["case"], item["model"], item["n"]
            path = draft_folder(out, key, model, item["brief"]) / f"attribution_{n}.json"
            if path.is_file() and is_done(json.loads(path.read_text(encoding="utf-8"))):
                continue
            which = pick_judge(model_ids[model], judges)
            fixture = json.loads((builder_root(key, drafts=True) / "fixture.json").read_text(encoding="utf-8"))
            client = clients.setdefault(key, Client(base_url, fixture["root"], timeout=CALL_TIMEOUT_S))
            order = excerpt_order(key, model, n)
            message = attribution_message(item["text"], [authors[k]["excerpt"] for k in order])
            verdict = ask(client, fixture["assistants"][judges[which]["name"]], SYSTEM_ATTRIBUTION, message, tuple("ABCD"))
            record = {"order": order, **verdict, "judge": which, "judge_model": judges[which]["model"]}
            record["correct"] = order["ABCD".index(verdict["answer"])] == key if verdict["answer"] in tuple("ABCD") else None
            path.write_text(json.dumps(record, indent=2), encoding="utf-8")
            print(f"{key}/{model} #{n} [{which}]: {verdict['answer']} correct={record['correct']}", flush=True)
    finally:
        for client in clients.values():
            client.close()


def collect(out: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Every note and draft record under BUILD_OUT, as `core.tally` takes them."""
    notes = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "notes").glob("*.json"))}
    drafts = []
    for item in iter_drafts(out / "drafts"):
        path = draft_folder(out, item["case"], item["model"], item["brief"]) / f"attribution_{item['n']}.json"
        drafts.append({
            "key": item["case"], "model": item["model"], "status": item["meta"].get("status", "ok"),
            "cost_usd": item["meta"].get("cost_usd"),
            "attribution": json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None,
        })
    return notes, drafts


def report(out: Path) -> str:
    notes, drafts = collect(out)
    authors = [a for a in load_authors() if a["key"] in notes]
    text = render_result(tally(notes, drafts, authors))
    (out / "result.md").write_text(text, encoding="utf-8")
    return text


def run(args: argparse.Namespace) -> None:
    base_url = discover_backend()
    all_models = load_models()
    models = select_models(all_models, args.models)
    judges = list(load_judges().values())
    builder = (
        select_models(all_models, [args.builder_model])[0] if args.builder_model
        else next((m for m in all_models if m.get("primary")), all_models[0])
    )
    names = [m["name"] for m in [*models, *judges]]
    if len(names) != len(set(names)):
        raise SystemExit(f"Model and judge names must be distinct: {', '.join(sorted(names))}")
    book = load_book()
    brief = args.brief or book["scenes"][0]["key"]
    if brief not in {s["key"] for s in book["scenes"]}:
        raise SystemExit(f"Unknown brief {brief!r}.")
    authors = [a for a in load_authors() if not args.authors or a["key"] in args.authors]
    out = args.out
    for author in authors:
        note = build_note(base_url, book, author, builder, out)
        if note["status"] != "ok":
            continue
        # Always (re)set the drafting project's assistants, not only when drafts are pending: a
        # changed setting (a judge's output cap, say) must reach the judge before it attributes.
        fixture = drafting_fixture(base_url, book, author["key"], note, [*models, *judges])
        todo = pending_drafts(out, author["key"], models, brief, args.drafts)
        if todo:
            draft_pending(base_url, fixture, author["key"], todo, brief, out)
    attribute_drafts(base_url, out, {m["name"]: m["model"] for m in all_models})
    print(report(out))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="build the notes, draft from them, attribute, report")
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--models", nargs="+", help="drafting models from models.yaml (default: all)")
    run_parser.add_argument("--drafts", type=int, default=3)
    run_parser.add_argument("--brief", help="a scene key from book.yaml (default: the first)")
    run_parser.add_argument("--authors", nargs="+", choices=[a["key"] for a in load_authors()])
    run_parser.add_argument("--builder-model", help="the model that runs the builder (default: the primary, else the first)")
    report_parser = sub.add_parser("report", help="print and write result.md for a BUILD_OUT")
    report_parser.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        run(args)
    else:
        print(report(args.out))


if __name__ == "__main__":
    main()
