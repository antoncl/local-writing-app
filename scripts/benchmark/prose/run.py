"""Run the built-in prompts Draft scene and Continue over the prose fixtures (#2613).

Drives the dev backend over HTTP in the frontend's own call sequence
(docs/design/measuring-prose-quality.md §7), so every call runs the real backend
code and the harness mirrors only the *order*. The mirror is checked against a
hand run by `parity.py`.

Draft scene is a conversation prompt. Sequence, per brief per draft:
  1. POST /api/chats                      chatSessions.svelte.ts (openChatFromPromptEntry)
  2. PUT  /api/nodes/{chat}               the same file: the seeded `inputs` save
  3. POST /api/ai/preview                 components/editor/body/chat/promptTemplateLock.ts
                                          (system prompt = system messages' blocks joined
                                          "" per message and "\\n\\n" across messages)
  4. PUT  /api/nodes/{chat}               lib/chat/chatSessionRecord.svelte.ts::toPayload
                                          (the lock record), as ChatBodyView.persistActiveChat
  5. POST /api/ai/chat/stream             ChatBodyView.svelte::streamAssistantReply; the
                                          reply is appended and the record saved again
  6. POST /api/ai/entry-patch/{scene}/extract
                                          lib/stores/chatCommit.svelte.ts::extractPatch
                                          (read-only: the scene is never written)
Continue is one-shot: POST /api/ai/generate/stream, the Continue path of
lib/editor-core/aiSuggestion.svelte.ts.

A context_pick input value is the encoded JSON STRING of a NodePickerRef list
(lib/utils/promptInputs.ts::encodePickerValue / coerceInputValue), compact like JS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_gen import BOOK_YAML, CASES, book_sha256, load_fixture  # noqa: E402
from lwa_client import REPO, ApiError, Client, discover_backend  # noqa: E402
from setup_backend import load_models, select_models  # noqa: E402

PROMPT_TITLES = {"draft_scene": "Draft scene", "continue": "Continue"}
# The app sends an empty composer only when the rendered prompt ends in a user
# turn (ChatBodyView.svelte, endsInUserTurn); otherwise the writer must type a
# first message. A prompt that ends in system text gets this one, the same on
# every run, so the drafts stay comparable. Recorded in run.json.
OPENING_MESSAGE = "Draft the scene."


class StepFailed(RuntimeError):
    """A step the model could not complete: `status` is out_of_reach or error."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


def encode_pick(scene_id: str, title: str) -> str:
    ref = {"id": scene_id, "kind": "manuscript", "title": title, "entry_type": "manuscript:scene"}
    return json.dumps([ref], separators=(",", ":"), ensure_ascii=False)


def lock_from_preview(preview: dict[str, Any]) -> dict[str, Any]:
    """Mirror promptTemplateLock.ts: flatten blocks, join system messages, keep the turns."""
    def flatten(message: dict[str, Any]) -> str:
        return "".join(block["text"] for block in message["blocks"])

    messages = preview.get("messages") or []
    return {
        "system_prompt": "\n\n".join(flatten(m) for m in messages if m["role"] == "system"),
        "turns": [{"role": m["role"], "content": flatten(m)} for m in messages if m["role"] in ("user", "assistant")],
        "lore_enabled": preview.get("lore_enabled", False),
        "lore_free": preview.get("lore_free", False),
        "used_node_ids": preview.get("used_node_ids") or [],
        "used_node_hints": preview.get("used_node_hints") or {},
        "used_snapshots": preview.get("used_snapshots") or [],
        "field_contract_stored": preview.get("field_contract_stored") or [],
    }


def message_record(message: dict[str, Any]) -> dict[str, Any]:
    """One transcript message as toPayload writes it."""
    return {
        "role": message["role"],
        "content": message["content"],
        "thinking": message.get("thinking", ""),
        "truncated": bool(message.get("truncated")),
        "input_truncated": bool(message.get("input_truncated")),
        "stopped": False,
        "usage": message.get("usage"),
        "cost_usd": message.get("cost_usd"),
        "provider": message.get("provider"),
        "model": message.get("model"),
        "latency_ms": message.get("latency_ms"),
        "lore_fit": message.get("lore_fit"),
        "journal_added": message.get("journal_added") or [],
        "lore_updated": message.get("lore_updated") or [],
    }


def assistant_message(text: str, done: dict[str, Any]) -> dict[str, Any]:
    """The reply as ChatBodyView stamps it from the `done` line."""
    return {
        "role": "assistant",
        "content": text,
        "thinking": done.get("_thinking", ""),
        "truncated": bool(done.get("truncated")),
        "input_truncated": bool(done.get("input_truncated")),
        **{k: done.get(k) for k in ("usage", "cost_usd", "provider", "model", "latency_ms", "lore_fit")},
        "journal_added": done.get("journal_added") or [],
        "lore_updated": done.get("lore_updated") or [],
    }


def chat_payload(
    chat: dict[str, Any], assistant_id: str, lock: dict[str, Any], history: list[dict[str, Any]],
    inputs: dict[str, str],
) -> dict[str, Any]:
    """The lock record: every field chatSessionRecord.svelte.ts::toPayload sends."""
    return {
        "title": chat["title"],
        "prompt_entry_id": chat["prompt_entry_id"],
        "assistant_id": assistant_id,
        "system_prompt": lock["system_prompt"],
        "subject": chat["subject"],
        "staged_set": "",
        "lore_enabled": lock["lore_enabled"],
        "lore_free": lock["lore_free"],
        "used_node_ids": lock["used_node_ids"],
        "used_node_hints": lock["used_node_hints"],
        "used_snapshots": lock["used_snapshots"],
        "field_contract_stored": lock["field_contract_stored"],
        "pinned": False,
        "context_items": [],
        "messages": [message_record(m) for m in history],
        "inputs": inputs,
    }


def done_summary(done: dict[str, Any]) -> dict[str, Any]:
    keys = ("provider", "model", "stop_reason", "truncated", "usage", "cost_usd", "latency_ms")
    return {k: done.get(k) for k in keys}


def cost_of(*values: Any) -> float:
    return sum(v for v in values if isinstance(v, int | float))


def open_chat(
    project: Client, prompt: dict[str, Any], assistant_id: str, title: str, subject: str, inputs: dict[str, Any]
) -> dict[str, Any]:
    chat = project.post(
        "/api/chats",
        {"prompt_entry_id": prompt["id"], "assistant_id": assistant_id, "title": title, "subject": subject},
    )
    # The launch's seeded inputs, saved before the pane opens (chatSessions.svelte.ts).
    project.put(
        f"/api/nodes/{chat['id']}",
        {
            "title": chat["title"], "prompt_entry_id": chat["prompt_entry_id"],
            "assistant_id": chat["assistant_id"], "system_prompt": "", "subject": chat["subject"],
            "pinned": False, "context_items": [], "messages": [], "inputs": inputs,
        },
    )
    return chat


def start_chat(project: Client, prompt: dict[str, Any], assistant_id: str, scene: dict[str, str], n: int) -> dict[str, Any]:
    ref = {"id": scene["id"], "kind": "manuscript", "title": scene["title"], "entry_type": "manuscript:scene"}
    title = f"{scene['title']} - {prompt['title']} (draft {n})"
    return open_chat(project, prompt, assistant_id, title, scene["id"], {"entry": [ref]})


def blank_input_value(input_type: str) -> Any:
    """promptInputs.ts::blankOptionalInputValue: what the app sends for an input left blank."""
    if input_type in ("text", "long_text"):
        return ""
    if input_type == "context_pick":
        return "[]"
    return None


def dialog_drafts(prompt: dict[str, Any]) -> dict[str, Any]:
    """What the inputs dialog holds for a writer who changes nothing: each declared `default`
    (PromptInvocationDialog.svelte::open seeds `String(default)`), a number coerced back as
    promptInputs.ts::coerceInputValue does on submit. Inputs with no default stay blank."""
    drafts: dict[str, Any] = {}
    for declared in prompt.get("effective_inputs") or []:
        default = declared.get("default")
        if default is None:
            continue
        drafts[declared["name"]] = default if declared["type"] == "number" else str(default)
    return drafts


def preview_inputs(prompt: dict[str, Any], drafts: dict[str, Any]) -> dict[str, Any]:
    """promptResolution.ts::inputValuesFromDrafts for a writer who fills in only the scene:
    every declared input is sent, a blank optional one as its blank value. The harness
    leaves the rest blank so the template's own defaults apply, as they do in the app."""
    inputs: dict[str, Any] = {}
    for declared in prompt.get("effective_inputs") or []:
        name = declared["name"]
        if drafts.get(name):
            inputs[name] = drafts[name]
        elif not declared.get("required"):
            inputs[name] = blank_input_value(declared["type"])
    return inputs


def preview_lock(
    project: Client, prompt: dict[str, Any], assistant_id: str, drafts: dict[str, Any], subject: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Render the prompt as the app does and return `(lock, raw preview)`."""
    preview = project.post(
        "/api/ai/preview",
        {
            "assistant_id": assistant_id,
            "template_source": prompt["body"],
            "target_scene_id": "",
            "subject": subject,
            "inputs": preview_inputs(prompt, drafts),
            "resolution_scene_id": "",
            "commit": False,
        },
    )
    if preview.get("error"):
        raise StepFailed("error", f"Couldn't render prompt template: {preview['error'].get('message')}")
    return lock_from_preview(preview), preview


def render_lock(project: Client, prompt: dict[str, Any], assistant_id: str, scene: dict[str, str]) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    drafts = {"entry": encode_pick(scene["id"], scene["title"])}
    lock, preview = preview_lock(project, prompt, assistant_id, drafts, scene["id"])
    return lock, drafts, preview


def extract_draft(project: Client, scene_id: str, assistant_id: str, chat_id: str, history: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    result = project.post(
        f"/api/ai/entry-patch/{scene_id}/extract",
        {
            "messages": [{"role": m["role"], "content": m["content"]} for m in history],
            "assistant_id": assistant_id,
            "chat_id": chat_id,
            "follow_ups": True,
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
    if patch.get("garbled"):
        raise StepFailed("out_of_reach", f"garbled: {patch.get('garbled_reason')}")
    if patch.get("body") is None:
        raise StepFailed("out_of_reach", "the extraction proposed no body")
    return patch["body"]


def drive_draft_scene(project: Client, prompt: dict[str, Any], assistant_id: str, scene: dict[str, str], n: int, meta: dict[str, Any]) -> str:
    chat = start_chat(project, prompt, assistant_id, scene, n)
    meta["chat_id"] = chat["id"]
    lock, drafts, preview = render_lock(project, prompt, assistant_id, scene)
    meta["cache_blocks"] = preview.get("cache_blocks")
    history = list(lock["turns"])
    node = f"/api/nodes/{chat['id']}"
    # The lock is saved before the writer's own message joins the history, as the app does.
    project.put(node, chat_payload(chat, assistant_id, lock, history, drafts))
    if not history or history[-1]["role"] != "user":
        history.append({"role": "user", "content": OPENING_MESSAGE})
        meta["opening_message"] = OPENING_MESSAGE
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
    meta["cost_usd"] = cost_of(done.get("cost_usd"))
    history.append(assistant_message(text, done))
    project.put(node, {**chat_payload(chat, assistant_id, lock, history, drafts), **cache_slots(done)})
    if done.get("truncated"):
        meta["reply"] = text
        raise StepFailed("out_of_reach", "the reply was truncated")
    return extract_draft(project, scene["id"], assistant_id, chat["id"], history, meta)


def cache_slots(done: dict[str, Any]) -> dict[str, Any]:
    usage = done.get("usage") or {}
    return {"cache_write_slots": ["system"]} if usage.get("cache_write_tokens", 0) > 0 else {}


def drive_continue(project: Client, prompt: dict[str, Any], assistant_id: str, case: dict[str, str], meta: dict[str, Any]) -> str:
    scene = project.get(f"/api/scenes/{case['id']}")
    text, done = project.stream_ndjson(
        "/api/ai/generate/stream",
        {
            "template_source": prompt["body"],
            "target_scene_id": case["id"],
            "session_id": case["id"],
            # The inputs dialog opens for Continue (it has visible inputs) with the declared
            # defaults seeded, and the writer presses Run: aiSuggestion.svelte.ts ~L505.
            "inputs": preview_inputs(prompt, dialog_drafts(prompt)),
            "resolution_scene_id": "",
            "text_before": scene["body"],
            "text_after": "",
            "assistant_id": assistant_id,
            "commit": False,
        },
    )
    meta["stream"] = done_summary(done)
    meta["cost_usd"] = cost_of(done.get("cost_usd"))
    if done.get("truncated"):
        meta["reply"] = text
        raise StepFailed("out_of_reach", "the reply was truncated")
    return text


def run_cell(project: Client, kind: str, drive: Any, retries: int) -> tuple[str, dict[str, Any]]:
    """Run one draft; a failed step is recorded, never swallowed. Retries only when asked."""
    meta: dict[str, Any] = {}
    draft = ""
    spent = 0.0
    attempt_costs: list[float] = []
    for attempt in range(1, retries + 2):
        meta = {"attempts": attempt, "status": "ok"}
        started = time.monotonic()
        try:
            draft = drive(meta)
        except StepFailed as exc:
            meta.update(status=exc.status, error=str(exc))
        except httpx.TimeoutException as exc:
            meta.update(status="out_of_reach", error=f"timeout: {type(exc).__name__}")
        except (ApiError, httpx.HTTPError) as exc:
            meta.update(status="error", error=str(exc))
        meta["wall_s"] = round(time.monotonic() - started, 2)
        attempt_costs.append(meta.get("cost_usd") or 0)
        spent += attempt_costs[-1]
        if meta["status"] == "ok":
            break
    meta["cost_usd"] = spent
    meta["attempt_costs"] = attempt_costs
    if kind == "draft_scene" and meta.get("chat_id"):
        meta["chat_record"] = _fetch_chat(project, meta["chat_id"])
    return draft, meta


def _fetch_chat(project: Client, chat_id: str) -> Any:
    try:
        return project.get(f"/api/chats/{chat_id}")
    except ApiError as exc:
        return {"error": str(exc)}


def write_draft(folder: Path, n: int, draft: str, meta: dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"draft_{n}.md").write_text(draft, encoding="utf-8")
    (folder / f"meta_{n}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def find_prompts(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for key, title in PROMPT_TITLES.items():
        match = next((e for e in entries if e["title"] == title), None)
        if match is None:
            raise SystemExit(f"Built-in prompt {title!r} not found in GET /api/prompts.")
        found[key] = match
    return found


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_record(prompts: dict[str, dict[str, Any]], entries: list[dict[str, Any]]) -> dict[str, Any]:
    """The two prompts used, plus a hash over EVERY prompt and snippet the library holds: a
    snippet the prompts include (Prose generation settings, ...) changes the run too."""
    library = sorted((e["title"], _sha(e["body"])) for e in entries)
    return {
        "prompts": {k: {"id": p["id"], "sha256": _sha(p["body"])} for k, p in prompts.items()},
        "library_sha256": _sha(json.dumps(library, ensure_ascii=False)),
    }


def git_head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False)
    return result.stdout.strip() or "unknown"


def run_model(
    projects: dict[str, Client], fixture: dict[str, Any], model: dict[str, Any],
    prompts: dict[str, dict[str, Any]], out: Path, args: argparse.Namespace,
) -> float:
    """`projects` maps a prompt kind to the Client for the project that kind runs in: Draft
    scene in the briefs' project, Continue in the lead-ins' own (fixture_gen._make_continues)."""
    follow = fixture["continue"]
    assistants = {"draft_scene": fixture.get("assistants", {}), "continue": follow.get("assistants", {})}
    for kind, known in assistants.items():
        if not known.get(model["name"]):
            raise SystemExit(f"No assistant for {model['name']} in case {fixture['case']} ({kind}): run setup_backend.py.")
    base = out / fixture["case"] / model["name"]
    jobs: list[tuple[str, str, Any]] = []
    for key, scene in fixture["scenes"].items():
        jobs.append(("draft_scene", key, scene))
    for key, case in follow["cases"].items():
        jobs.append(("continue", key, case))
    total = 0.0
    for kind, key, item in jobs:
        project = projects[kind]
        assistant_id = assistants[kind][model["name"]]
        for n in range(1, args.drafts + 1):
            if kind == "draft_scene":
                drive = partial(drive_draft_scene, project, prompts[kind], assistant_id, item, n)
            else:
                drive = partial(drive_continue, project, prompts[kind], assistant_id, item)
            draft, meta = run_cell(project, kind, drive, args.retries)
            write_draft(base / kind / key, n, draft, meta)
            total += meta.get("cost_usd") or 0.0
            print(f"{fixture['case']}/{model['name']}/{kind}/{key} #{n}: {meta['status']}", flush=True)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--models", nargs="+", help="model names from models.yaml (default: all)")
    parser.add_argument("--drafts", type=int, default=3)
    parser.add_argument("--retries", type=int, default=0, help="explicit retries per draft (default 0)")
    parser.add_argument("--out", type=Path, help="output folder (default tmp/benchmark-runs/prose/<UTC stamp>)")
    args = parser.parse_args()
    base_url = discover_backend()
    models = select_models(load_models(), args.models)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = args.out or REPO / "tmp" / "benchmark-runs" / "prose" / stamp
    out.mkdir(parents=True, exist_ok=True)
    run: dict[str, Any] = {
        "git_head": git_head(), "timestamp": stamp, "cases": args.cases, "models": models,
        "drafts": args.drafts, "book_yaml_sha256": book_sha256(), "book_yaml": BOOK_YAML.name,
        "prompts": None, "cost_usd_by_model": {m["name"]: 0.0 for m in models},
        "opening_message": OPENING_MESSAGE,
    }
    try:
        for case in args.cases:
            fixture = load_fixture(case)
            if fixture.get("book_sha256") != book_sha256() or "continue" not in fixture:
                raise SystemExit(
                    f"Fixture {case!r} was not built from the current book.yaml: run fixture_gen.py --regen."
                )
            project = Client(base_url, fixture["root"])
            follow = Client(base_url, fixture["continue"]["root"])
            try:
                entries = project.get("/api/prompts")["entries"]
                prompts = find_prompts(entries)
                record = prompt_record(prompts, entries)
                if run["prompts"] not in (None, record):
                    raise SystemExit(f"Prompt text differs between case projects (at {case}).")
                run["prompts"] = record
                projects = {"draft_scene": project, "continue": follow}
                for model in models:
                    run["cost_usd_by_model"][model["name"]] += run_model(projects, fixture, model, prompts, out, args)
            finally:
                project.close()
                follow.close()
    finally:
        (out / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    print(f"run written to {out}")


if __name__ == "__main__":
    main()
