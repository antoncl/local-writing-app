"""Generate the built-in prose test set's projects (#2613, measuring-prose-quality.md §3).

Two projects per style case (the four briefs, and the Continue lead-ins in `<case>-continue`
so a lead-in never sees the briefs' later events), all built from the frozen `fixture/book.yaml`, so the
cast, the briefs and the narration are identical across styles and only the style
note differs. Everything goes through the dev backend's HTTP routes - the same
ones the frontend uses - never by writing project files, so the fixture is what
the app itself would have written.

Routes (confirmed from the code):
  POST  /api/project/create     routers/project.py::create_project (CreateProjectRequest)
  GET/PUT /api/project/node     routers/project.py; frontend lib/api/project.ts::saveProjectNode
                                writes the project's own metadata (`pov_mode`, `tense`)
  POST  /api/lore               routers/lore.py::create_lore_entry (CreateLoreEntryRequest:
                                title + entry_type only), then
  PUT   /api/lore/{id}          SaveLoreEntryRequest (body, metadata) with the create's revision
  POST  /api/scenes             routers/scenes.py::create_scene (CreateSceneRequest: title only), then
  PUT   /api/scenes/{id}        SaveSceneRequest (body, metadata) with the create's revision

Reference values: an `entity_ref` (`pov`) is the bare node id string and an
`entity_ref_list` (`characters`) is a list of bare id strings
(backend/tests/test_ai_helpers.py ~L144-156 writes them that way).

Idempotent: an existing case folder with `fixture.json` is reused; `--regen`
deletes and rebuilds it (only ever inside `tmp/benchmark-fixtures/prose/`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lwa_client import Client, discover_backend  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
BOOK_YAML = Path(__file__).resolve().parent / "fixture" / "book.yaml"
FIXTURE_ROOT = REPO / "tmp" / "benchmark-fixtures" / "prose"
CASES = ("frank", "lush", "hardboiled", "wry", "none")


def case_root(case: str) -> Path:
    return FIXTURE_ROOT / case


def continue_case_root(case: str) -> Path:
    return FIXTURE_ROOT / f"{case}-continue"


def book_sha256() -> str:
    return hashlib.sha256(BOOK_YAML.read_bytes()).hexdigest()


def load_book() -> dict[str, Any]:
    return yaml.safe_load(BOOK_YAML.read_text(encoding="utf-8"))


def load_fixture(case: str) -> dict[str, Any]:
    path = case_root(case) / "fixture.json"
    if not path.is_file():
        raise SystemExit(f"No fixture for case {case!r} ({path}). Run fixture_gen.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


def write_fixture(case: str, fixture: dict[str, Any]) -> None:
    write_json(case_root(case), fixture)


def builder_root(key: str, drafts: bool = False) -> Path:
    """The builder test's projects for one author (#2623): the workspace, and the drafting project."""
    return FIXTURE_ROOT / (f"builder-{key}-drafts" if drafts else f"builder-{key}")


def _remove_roots(*roots: Path) -> None:
    """Delete folders - and only those that resolve inside the fixture root."""
    root = FIXTURE_ROOT.resolve()
    for target in (r.resolve() for r in roots):
        if root not in target.parents:
            raise SystemExit(f"Refusing to delete {target}: not inside {root}")
        if target.exists():
            shutil.rmtree(target)


def _remove_case(case: str) -> None:
    _remove_roots(case_root(case), continue_case_root(case))


def _save_lore(project: Client, entry: dict[str, Any], body: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return project.put(
        f"/api/lore/{entry['id']}",
        {
            "title": entry["title"],
            "body": body,
            "base_revision": entry["revision"],
            "entry_type": entry["entry_type"],
            "metadata": metadata,
        },
    )


def _save_scene(
    project: Client, scene: dict[str, Any], body: str, metadata: dict[str, Any]
) -> dict[str, Any]:
    return project.put(
        f"/api/scenes/{scene['id']}",
        {
            "title": scene["title"],
            "body": body,
            "base_revision": scene["revision"],
            "entry_type": scene["entry_type"],
            "metadata": metadata,
        },
    )


def _set_narration(project: Client, book: dict[str, Any]) -> None:
    node = project.get("/api/project/node")
    metadata = {**node["metadata"]}
    for key in ("pov_mode", "tense"):
        metadata[key] = book["project"][key]
    project.put(
        "/api/project/node",
        {
            "title": node["title"],
            "body": node["body"],
            "base_revision": node["revision"],
            "entry_type": node["entry_type"],
            "metadata": metadata,
        },
    )


def _make_characters(project: Client, book: dict[str, Any]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for character in book["characters"]:
        created = project.post("/api/lore", {"title": character["title"], "entry_type": "lore:character"})
        metadata: dict[str, Any] = {}
        if character.get("aliases"):
            metadata["aliases"] = list(character["aliases"])
        _save_lore(project, created, character["body"], metadata)
        ids[character["key"]] = created["id"]
    return ids


def _make_note(project: Client, book: dict[str, Any], case: str) -> dict[str, str] | None:
    note = book["style_notes"].get(case)
    return None if note is None else _create_note(project, note)


def _create_note(project: Client, note: dict[str, str]) -> dict[str, str]:
    """A style note (`title`, `body`) set to context policy always."""
    created = project.post("/api/lore", {"title": note["title"], "entry_type": "lore:note"})
    _save_lore(project, created, note["body"], {"context_policy": "always"})
    return {"id": created["id"], "title": note["title"]}


def _scene_metadata(spec: dict[str, Any], characters: dict[str, str], summary: str | None) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "pov": characters[spec["pov"]],
        "characters": [characters[key] for key in spec["characters"]],
    }
    if summary is not None:
        metadata["summary"] = summary
    return metadata


def _make_briefs(project: Client, book: dict[str, Any], characters: dict[str, str]) -> dict[str, dict[str, str]]:
    scenes: dict[str, dict[str, str]] = {}
    for spec in book["scenes"]:
        created = project.post("/api/scenes", {"title": spec["title"]})
        _save_scene(project, created, "", _scene_metadata(spec, characters, spec["summary"].strip()))
        scenes[spec["key"]] = {"id": created["id"], "title": spec["title"]}
    return scenes


def _make_continues(
    project: Client, book: dict[str, Any], characters: dict[str, str]
) -> dict[str, dict[str, str]]:
    """The Continue lead-ins: scenes with a body and no summary, in a project of their own so
    the story so far never carries the briefs' later events into a lead-in (and a lead-in never
    sits inside a brief's scene, which would make Draft scene a redraft there)."""
    by_key = {s["key"]: s for s in book["scenes"]}
    continues: dict[str, dict[str, str]] = {}
    for spec in book["continue_cases"]:
        source = by_key[spec["scene"]]
        created = project.post("/api/scenes", {"title": spec["title"]})
        _save_scene(project, created, spec["before"], _scene_metadata(source, characters, None))
        continues[spec["key"]] = {"id": created["id"], "title": spec["title"], "scene": spec["scene"]}
    return continues


def _remove_seeded_scenes(project: Client, root: Path) -> None:
    """A new project starts with an "Untitled Scene" (`services/project/lifecycle.py`). Left in, it
    would sit before the first brief, so it is deleted through the app's own route. No route lists
    scenes, and a just-created project holds only that one, so its id is read from disk."""
    for path in sorted((root / "scenes").glob("*.md")):
        front = path.read_text(encoding="utf-8").split("\n---", 1)[0]
        ids = [line.split(":", 1)[1].strip() for line in front.splitlines() if line.startswith("id:")]
        for scene_id in ids:
            project.delete(f"/api/scenes/{scene_id}")


def _new_project(base_url: str, root: Path, book: dict[str, Any]) -> tuple[Client, str]:
    """Create one project through the API, clear its seeded scene, set the narration."""
    unscoped = Client(base_url)
    info = unscoped.post(
        "/api/project/create", {"root_path": str(root), "title": book["project"]["title"], "inherits": []}
    )
    unscoped.close()
    project = Client(base_url, info["root_path"])
    _remove_seeded_scenes(project, Path(info["root_path"]))
    _set_narration(project, book)
    return project, info["root_path"]


def build_case(base_url: str, book: dict[str, Any], case: str) -> dict[str, Any]:
    case_root(case).parent.mkdir(parents=True, exist_ok=True)
    project, brief_root = _new_project(base_url, case_root(case), book)
    try:
        characters = _make_characters(project, book)
        note = _make_note(project, book, case)
        scenes = _make_briefs(project, book, characters)
    finally:
        project.close()
    # Same cast, note and narration, but only the lead-ins (see _make_continues).
    project, continue_root = _new_project(base_url, continue_case_root(case), book)
    try:
        continue_characters = _make_characters(project, book)
        continue_note = _make_note(project, book, case)
        continues = _make_continues(project, book, continue_characters)
    finally:
        project.close()
    return {
        "case": case,
        "root": brief_root,
        "book_sha256": book_sha256(),
        "characters": characters,
        "note": note,
        "scenes": scenes,
        "continue": {
            "root": continue_root,
            "characters": continue_characters,
            "note": continue_note,
            "cases": continues,
        },
    }


def note_sha256(note: dict[str, str] | None) -> str | None:
    return None if note is None else hashlib.sha256(note["body"].encode("utf-8")).hexdigest()


def build_style_project(
    base_url: str, root: Path, book: dict[str, Any], note: dict[str, str] | None
) -> dict[str, Any]:
    """One briefs project like a style case's, with `note` as its style note (None: no note)."""
    project, made_root = _new_project(base_url, root, book)
    try:
        characters = _make_characters(project, book)
        made = None if note is None else _create_note(project, note)
        scenes = _make_briefs(project, book, characters)
    finally:
        project.close()
    return {
        "root": made_root, "book_sha256": book_sha256(), "characters": characters, "note": made,
        "note_sha256": note_sha256(note),
        "scenes": scenes,
    }


def ensure_project(
    base_url: str, book: dict[str, Any], root: Path, note: dict[str, str] | None = None, regen: bool = False
) -> dict[str, Any]:
    """Build (or reuse) a project at `root` and record it in its `fixture.json`. A recorded project is
    reused only when it holds the same note body; any other is deleted and rebuilt."""
    path = root / "fixture.json"
    wanted = note_sha256(note)
    if not regen and path.is_file():
        fixture = json.loads(path.read_text(encoding="utf-8"))
        if fixture.get("note_sha256") == wanted and fixture.get("book_sha256") == book_sha256():
            return fixture
    _remove_roots(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    fixture = build_style_project(base_url, root, book, note)
    write_json(root, fixture)
    return fixture


def write_json(root: Path, fixture: dict[str, Any]) -> None:
    (root / "fixture.json").write_text(json.dumps(fixture, indent=2), encoding="utf-8")


def ensure_case(base_url: str, book: dict[str, Any], case: str, regen: bool) -> dict[str, Any]:
    if regen:
        _remove_case(case)
    elif (case_root(case) / "fixture.json").is_file():
        print(f"{case}: reusing {case_root(case)}")
        return load_fixture(case)
    fixture = build_case(base_url, book, case)
    write_fixture(case, fixture)
    print(f"{case}: built {fixture['root']} and {fixture['continue']['root']}")
    return fixture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--regen", action="store_true", help="delete and rebuild the case folders")
    args = parser.parse_args()
    base_url = discover_backend()
    book = load_book()
    for case in args.cases:
        ensure_case(base_url, book, case, args.regen)


if __name__ == "__main__":
    main()
