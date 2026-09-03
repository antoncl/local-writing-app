"""Project schema migrations.

Conventions:
- `CURRENT_VERSION` is the schema version the codebase represents.
- New projects are stamped with `schema_version: CURRENT_VERSION` on creation;
  they never run migrations on first open.
- Existing projects without `schema_version` are treated as version 0.
- Each entry in `MIGRATIONS` runs once to take the project from N-1 to N.
- Migrations run inside open_project, after the manifest is detected but before
  any other side effects. The whole project is zipped to
  `<root>/.migration-backups/v{from}-{utc-ts}.zip` first; the last 3 backups are
  kept and older ones are pruned.

Adding a migration:
1. Bump CURRENT_VERSION.
2. Append `RootMigration(version, "short description", migrator_fn)` to MIGRATIONS.
3. `migrator_fn(root: Path) -> None` mutates files in place; raise on failure.

Defensive reads are still the default for additive changes. Only add a migration
when failing to migrate would break something downstream.

Two shapes (ADR-0071 §1): `RootMigration` is for project-shaped changes — folders,
cross-file moves, `*.structure.yaml`, the schema — its `fn` mutates the project
root. `DocumentMigration` is for content transforms of one document in isolation
— its `fn` takes/returns a `MigratableDocument` and never sees the root or
sibling files. Reach for `DocumentMigration` when the content that needs
migrating doesn't always live under the project tree: a snapshot restored later
(ADR-0043) only has the document body to migrate against, so only the document
shape can reach it. `migrate_document` applies the `DocumentMigration` subladder
to a single document; the project-wide pass that runs it over every owned
document is slice 2 (#366).

A third shape, `ChainMigration` (ADR-0082 slice 4, #1785), is for a step that
needs to know what an ANCESTOR layer just did: `fn` mutates one layer's root
like `RootMigration`, but also takes a `ChainContext` that
`MigrationRunnerMixin._run_migrations` threads outermost-first across the whole
declared chain, so a descendant layer's step sees names an ancestor's step
already minted.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# Independent of MIGRATIONS on purpose: it is the version the code represents,
# not the height of the ladder. Deriving it (e.g. max(m[0] for m in MIGRATIONS))
# would throw on an empty registry and take the stamp-forward path down with it.
CURRENT_VERSION = 10
KEEP_BACKUPS = 3
BACKUP_DIRNAME = ".migration-backups"
# `snapshots/` is excluded because migrations never touch it: snapshots are
# immutable at rest and migrate at *restore*, over that one body, on the way out
# (ADR-0043). So the pre-migration zip has nothing to protect there, and
# excluding it keeps the three retained backups from each carrying a full copy
# of the project's history. Immutability at rest is what buys this; the two
# decisions stand or fall together.
SKIP_FROM_BACKUP = {".migration-backups", ".cache", "snapshots"}

logger = logging.getLogger(__name__)

MigrationFn = Callable[[Path], None]


@dataclass(frozen=True)
class MigratableDocument:
    """One document's content in isolation (ADR-0071 §1): the entire parsed
    front-matter mapping + the markdown body — exactly what
    _read_markdown_with_front_matter yields. A DocumentMigrationFn transforms this
    and nothing else: no root, no filesystem, no sibling documents."""

    front_matter: dict[str, Any]
    body: str


DocumentMigrationFn = Callable[[MigratableDocument], MigratableDocument]


@dataclass(frozen=True)
class RootMigration:
    """A project-shaped step (folders, cross-file moves, *.structure.yaml, the
    schema): fn mutates the project ROOT in place (ADR-0071 §1)."""

    version: int
    description: str
    fn: MigrationFn


@dataclass(frozen=True)
class DocumentMigration:
    """A content step: fn transforms ONE document in isolation (ADR-0071 §1/§3).
    Must be idempotent (re-applying to an already-migrated document is a no-op —
    ADR-0071 §2) and authored against the KNOWN format at its version transition,
    never reading the live schema."""

    version: int
    description: str
    fn: DocumentMigrationFn


@dataclass
class ChainContext:
    """Threaded across one open's whole chain migration run, outermost layer
    first (ADR-0082 slice 4, #1785 — the old `_TagRegistryMerger`'s union,
    stated once instead of re-derived per reader).

    `name_to_id` is the general tag vocabulary: lower-cased title -> tag-node
    id, over every `tag:tag` node minted so far at any layer already
    processed this run. First-seen (outermost) casing wins on a case-only
    clash, same rule the retired registry merge used. `machine_names` is the
    separate assistant-tag vocabulary (`tag:assistant_tag`, out-of-tree at the
    machine layer) — seeded once from whatever `machine_tag_names()` already
    finds on disk before the chain runs, then grown in place by a layer's own
    step when it mints a not-yet-seen assistant-tag name.

    A mutable dataclass, not frozen: every layer's step mutates the same two
    dicts in place so a later layer (or a later pass within one layer) sees
    an earlier mint without threading a new context back out.
    """

    name_to_id: dict[str, str] = field(default_factory=dict)
    machine_names: dict[str, str] = field(default_factory=dict)


ChainMigrationFn = Callable[[Path, ChainContext], None]


@dataclass(frozen=True)
class ChainMigration:
    """A project-shaped step like `RootMigration`, but `fn` also takes the
    chain-wide `ChainContext` (ADR-0082 slice 4) — for a step whose result at
    one layer depends on what an ancestor layer's own run of the same step
    already did (e.g. minting a tag node only once across the chain)."""

    version: int
    description: str
    fn: ChainMigrationFn


MigrationStep = RootMigration | DocumentMigration | ChainMigration


def _create_snippets_folder(root: Path) -> None:
    """v1→v2: introduce the snippets/ folder for the snippet node kind."""
    (root / "snippets").mkdir(exist_ok=True)


def _create_research_structure(root: Path) -> None:
    """v4→v5: introduce the research kind. Create research/notes/ for
    note markdown files and seed an empty research.structure.yaml so
    the validate/read paths don't have to special-case its absence
    (docs/research-strategy.md, slice 1)."""
    (root / "research" / "notes").mkdir(parents=True, exist_ok=True)
    structure_path = root / "research.structure.yaml"
    if structure_path.exists():
        return
    initial = {
        "root": {
            "id": "root",
            "type": "root",
            "title": "Research",
            "children": [],
        }
    }
    structure_path.write_text(
        yaml.safe_dump(initial, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _ensure_cascade_fields(root: Path, field_ids: tuple[str, ...]) -> None:
    """Ensure `field_ids` are present in the project's metadata.schema.yaml
    `cascade_fields` list. There is deliberately no resolver-side default (that
    would be the Python constant ADR-0079 rejects), so the value must land in YAML.

    Idempotent (ADR-0071 §2): existing entries are kept and only the missing ids
    are appended. A project with no schema file gets a minimal one — the merge
    treats every top-level key as optional."""
    schema_path = root / "metadata.schema.yaml"
    data: dict[str, Any] = {}
    if schema_path.exists():
        loaded = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    existing = data.get("cascade_fields")
    cascade = list(existing) if isinstance(existing, list) else []
    for field_id in field_ids:
        if field_id not in cascade:
            cascade.append(field_id)
    data["cascade_fields"] = cascade
    schema_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _backfill_narration_cascade_fields(root: Path) -> None:
    """v5→v6: seed `cascade_fields: [pov_mode, pov]` so narration inherits down the
    manuscript structure (ADR-0079). New projects get this from the scaffold;
    existing ones predate the key."""
    _ensure_cascade_fields(root, ("pov_mode", "pov"))


def _backfill_tense_cascade_field(root: Path) -> None:
    """v6→v7: add `tense` to `cascade_fields` so tense inherits down the manuscript
    like pov_mode/pov (ADR-0079, #1737). A separate step because existing projects
    already ran v6; new projects get the full set from the scaffold."""
    _ensure_cascade_fields(root, ("tense",))


def _lift_plot_template_genre(doc: MigratableDocument) -> MigratableDocument:
    """v7→v8: `plot:template` genre moved out of the `template:` spec block into a
    `long_text` node-metadata field (#1744), so a writer can author it in the panel
    like any node field instead of only by hand-editing front matter. Lift
    `template.genre` → `metadata.genre` on owned template clones. A no-op for every
    other document, and idempotent: once genre has left the `template:` block there
    is nothing to lift, and an existing `metadata.genre` is never clobbered."""
    front_matter = doc.front_matter
    if front_matter.get("entry_type") != "plot:template":
        return doc
    template = front_matter.get("template")
    if not isinstance(template, dict) or "genre" not in template:
        return doc
    new_template = {key: value for key, value in template.items() if key != "genre"}
    existing_metadata = front_matter.get("metadata")
    new_metadata = dict(existing_metadata) if isinstance(existing_metadata, dict) else {}
    new_metadata.setdefault("genre", template["genre"])
    return MigratableDocument(
        {**front_matter, "template": new_template, "metadata": new_metadata}, doc.body
    )


def _migrate_invocations_to_csv(root: Path) -> None:
    """v8→v9: the AI-invocations ledger moves from a YAML list
    (`ai_invocations.yaml`) to an append-only CSV (`ai_invocations.csv`), so a
    new row is an O(1) line append instead of a whole-file rewrite (#1801).
    Read the old list — tolerating both historical shapes, a bare list or
    `{invocations: [...]}` — write every row through the shared CSV flattener,
    then drop the YAML.

    Idempotent (ADR-0071 §2): with the CSV already present the YAML is just
    removed (the CSV is authoritative and never re-derived from it); an absent
    YAML is a no-op. Authored against the known v8 format — it reuses only the
    ledger's stable column contract, never the live reader."""
    from app.services.project.ai_invocations import (
        INVOCATION_CSV_COLUMNS,
        invocation_record_to_csv_row,
    )

    yaml_path = root / "ai_invocations.yaml"
    csv_path = root / "ai_invocations.csv"
    if csv_path.exists():
        yaml_path.unlink(missing_ok=True)
        return
    if not yaml_path.exists():
        return
    loaded = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if isinstance(loaded, list):
        rows: Any = loaded
    elif isinstance(loaded, dict) and isinstance(loaded.get("invocations"), list):
        rows = loaded["invocations"]
    else:
        rows = []
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVOCATION_CSV_COLUMNS)
        writer.writeheader()
        for record in rows:
            if isinstance(record, dict):
                writer.writerow(invocation_record_to_csv_row(record))
    yaml_path.unlink()


# --- v9→v10: tags.yaml + tags/assistant_tags occurrences → tag-kind nodes ----
# (ADR-0082 slice 4, #1785). The `tags` value type is gone (slice 2); a name in
# a `tags.yaml` registry becomes a `tag:tag` node, and every list-valued
# `tags`/`assistant_tags` occurrence across a layer's own documents becomes a
# list of tag-node ids. No service-instance method is called from any function
# below — `_create_research_structure` is the precedent (raw file IO only), so
# a step here can run against an ANCESTOR layer that the currently-open
# ProjectService is not bound to.

TAG_ID_PATTERN = re.compile(r"^tag_[0-9a-f]{10}$")
# A chat's `inputs` JSON carries a selector ref for a tag axis pick as
# `tag:<kind>:<name>` (the pre-migration id shape the picker emitted) — `kind`
# is the KIND OF NODE the selector targets (e.g. "lore"), not the tag's own
# vocabulary. Post-migration the same pick is `tagged:<kind>:<id>`.
_CHAT_TAG_REF_ID = re.compile(r"^tag:(?P<kind>[^:]+):(?P<name>.+)$")

# The `entity_ref_list` shape every retired `type: tags` field/input becomes
# (ADR-0082 §2's own built-in fields, e.g. `default_schema.py`'s `tags`
# field, are the precedent this mirrors). A schema field spells the picker
# constraint as `picker_config`; a prompt input spells the identical shape as
# `target` — `_TAG_PICKER_SHAPE` is reused for both, keyed onto whichever name
# the caller needs.
_TAG_PICKER_SHAPE: dict[str, Any] = {
    "sources": [{"kind": "tag", "expr": {"type": "tag:tag"}}],
    "create_missing": True,
}

# Mirrors `ProjectService._sanitize_filename`'s two constants — copied rather
# than imported so a chain step never reaches for a service-instance method
# (module docstring).
_FILENAME_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FILENAME_WHITESPACE = re.compile(r"\s+")
_FILENAME_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _sanitize_filename(title: str) -> str:
    """Copy of `ProjectService._sanitize_filename` (module docstring: a chain
    step writes files directly, never through a service-instance method)."""
    sanitized = _FILENAME_ILLEGAL_CHARS.sub("_", title)
    sanitized = _FILENAME_WHITESPACE.sub(" ", sanitized).strip()
    sanitized = sanitized.rstrip(". ")
    if len(sanitized) > 100:
        sanitized = sanitized[:100].rstrip(". ")
    if not sanitized:
        sanitized = "Untitled"
    base = sanitized.split(".")[0].upper()
    if base in _FILENAME_WINDOWS_RESERVED:
        sanitized = "_" + sanitized
    return sanitized


def _unique_filepath(folder: Path, sanitized: str) -> Path:
    """Copy of `ProjectService._unique_filepath`'s new-file half (no
    `current_path` — every caller here is minting a brand new node)."""
    candidate = folder / f"{sanitized}.md"
    if not candidate.exists():
        return candidate
    i = 2
    while True:
        candidate = folder / f"{sanitized} ({i}).md"
        if not candidate.exists():
            return candidate
        i += 1


def _read_front_matter(path: Path) -> tuple[dict[str, Any], str]:
    """Copy of `ProjectService._read_markdown_with_front_matter`'s lenient
    (non-strict) half: a file this can't parse reads as `({}, <the raw
    text>)`, so a caller checking `if not front_matter: continue` skips a
    hand-broken document rather than taking the whole layer's migration down."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    _, rest = text.split("---\n", 1)
    if "\n---\n" not in rest:
        return {}, text
    front, body = rest.split("\n---\n", 1)
    body = body.lstrip("\n")
    try:
        data = yaml.safe_load(front) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return data, body


def _write_front_matter(path: Path, front_matter: dict[str, Any], body: str) -> None:
    """Copy of `ProjectService._write_markdown_with_front_matter` — the
    content-transform framing (one `\\n` before the body, whatever the reader
    handed back), so re-serialising an existing document does not churn its
    body formatting. `mint_tag_node` below uses the OTHER framing
    (`_write_node_entry_file`'s, a blank line before the body) because it is
    authoring a brand new node, not round-tripping one."""
    front_matter_text = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip()
    path.write_text(f"---\n{front_matter_text}\n---\n{body}", encoding="utf-8", newline="\n")


def mint_tag_node(folder: Path, title: str, entry_type: str, *, color: str | None = None) -> str:
    """Write a brand new body-less tag node under `folder` and return its id.

    Front matter mirrors `ProjectService._write_node_entry_file` byte-for-byte
    (a blank line before the — empty — body): `id`, `title`, `entry_type`,
    `metadata` (always present, `{}` when there is no color, matching
    `create_tag_entry`'s own write). Shared by M3 (a machine `tag:assistant_tag`
    minted from `assistant-tags.yaml`) and the chain step below (a project
    `tag:tag` minted from `tags.yaml` or an unmapped name met along the way).
    """
    folder.mkdir(parents=True, exist_ok=True)
    tag_id = f"tag_{uuid.uuid4().hex[:10]}"
    front_matter_data: dict[str, Any] = {"id": tag_id, "title": title, "entry_type": entry_type}
    front_matter_data["metadata"] = {"color": color} if color else {}
    front_matter_text = yaml.safe_dump(front_matter_data, sort_keys=False, allow_unicode=True).strip()
    path = _unique_filepath(folder, _sanitize_filename(title))
    path.write_text(f"---\n{front_matter_text}\n---\n\n", encoding="utf-8", newline="\n")
    return tag_id


def _ensure_tag_id(
    name: str, folder: Path, name_to_id: dict[str, str], entry_type: str, *, color: str | None = None
) -> str:
    """The name→id resolver every conversion below shares: case-insensitive
    lookup in `name_to_id` first (an ancestor's — or this same run's — mint,
    first-seen casing wins), else mint a fresh node under `folder` and record
    it. Returns `""` for a blank name (nothing to mint)."""
    clean = name.strip()
    if not clean:
        return ""
    key = clean.lower()
    existing = name_to_id.get(key)
    if existing:
        return existing
    tag_id = mint_tag_node(folder, clean, entry_type, color=color)
    name_to_id[key] = tag_id
    return tag_id


def _resolve_or_mint_one(item: str, folder: Path, name_to_id: dict[str, str], entry_type: str) -> str:
    """One list/`tagged:`-adjacent name: pass an already-migrated id through
    unchanged, else resolve/mint it."""
    if TAG_ID_PATTERN.match(item):
        return item
    return _ensure_tag_id(item, folder, name_to_id, entry_type)


def _resolve_name_list(
    raw: Any, folder: Path, name_to_id: dict[str, str], entry_type: str
) -> tuple[list[str], bool]:
    """A `metadata.tags`/`metadata.assistant_tags`/rewritten-input value: a
    list of names and/or already-migrated ids → a list of ids, minting any
    unmapped name at `folder`. Non-list input passes through unresolved
    (`changed=False`) — a hand-edited scalar is left for a human, not guessed
    at. `changed` is also True when a blank/non-string item is dropped."""
    if not isinstance(raw, list):
        return raw, False
    resolved: list[str] = []
    changed = False
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            changed = True
            continue
        new_item = _resolve_or_mint_one(item.strip(), folder, name_to_id, entry_type)
        if new_item != item:
            changed = True
        if new_item:
            resolved.append(new_item)
    return resolved, changed


def _read_legacy_tags_yaml(path: Path) -> list[tuple[str, str | None]]:
    """`tags.yaml`'s own reader (the retired `TagsMixin._read_layer_tags`'
    precedent, slice 3): `{tags: [...]}`, each item a bare name string or
    `{name, scope, color}`. `scope` is dropped — a vocabulary's picker
    constraint now lives on the FIELD (`picker_config`), not per-tag."""
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    raw = data.get("tags") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    records: list[tuple[str, str | None]] = []
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
            if name:
                records.append((name, None))
        elif isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            if name:
                color = item.get("color")
                records.append((name, color if isinstance(color, str) else None))
    return records


def _mint_layer_tags_from_yaml(layer_root: Path, ctx: ChainContext) -> None:
    """Step 1 (M4): every `tags.yaml` record not already in `ctx.name_to_id`
    (case-insensitive — a name an ancestor already minted mints nothing here)
    becomes a `tag:tag` node under `<layer>/tags/`. Renames `tags.yaml` →
    `tags.yaml.migrated` whenever the file exists, whether or not it had
    anything to mint — the rename alone is what makes a re-run a no-op."""
    yaml_path = layer_root / "tags.yaml"
    for name, color in _read_legacy_tags_yaml(yaml_path):
        _ensure_tag_id(name, layer_root / "tags", ctx.name_to_id, "tag:tag", color=color)
    if yaml_path.exists():
        yaml_path.replace(layer_root / "tags.yaml.migrated")


def _convert_document_metadata(
    front_matter: dict[str, Any], *, kind: str, layer_root: Path, machine_root: Path, ctx: ChainContext
) -> bool:
    """Step 2 (M4): a node document's own `metadata.tags`/`metadata.assistant_tags`
    — `tags` resolves through the general vocabulary (`ctx.name_to_id`, minted
    at THIS layer); `assistant_tags` through the machine vocabulary
    (`ctx.machine_names`, minted at the MACHINE `tags/`, since a prompt may
    name an assistant tag the roster never had). An `assistant` document's old
    `tags` key (the pre-rename field name) is renamed to `assistant_tags` and
    resolved through the machine vocabulary too — the same rule M3 applies to
    the machine roster itself, kept here too in case a project layer ever
    carries its own `assistants/` folder (`references.NODE_FAMILIES` does not
    special-case a layer out of that family)."""
    metadata = front_matter.get("metadata")
    if not isinstance(metadata, dict):
        return False
    changed = False
    if kind == "assistant" and "tags" in metadata:
        raw = metadata.pop("tags")
        resolved, _ = _resolve_name_list(raw, machine_root / "tags", ctx.machine_names, "tag:assistant_tag")
        metadata["assistant_tags"] = resolved
        changed = True
    else:
        if "tags" in metadata:
            resolved, item_changed = _resolve_name_list(
                metadata["tags"], layer_root / "tags", ctx.name_to_id, "tag:tag"
            )
            if item_changed:
                metadata["tags"] = resolved
                changed = True
        if "assistant_tags" in metadata:
            resolved, item_changed = _resolve_name_list(
                metadata["assistant_tags"], machine_root / "tags", ctx.machine_names, "tag:assistant_tag"
            )
            if item_changed:
                metadata["assistant_tags"] = resolved
                changed = True
    return changed


def _convert_override_rows(
    front_matter: dict[str, Any], *, layer_root: Path, machine_root: Path, ctx: ChainContext
) -> bool:
    """Step 2 (M4): an `overrides/*.md` row whose `field` is `tags`/
    `assistant_tags` carries a comma-joined name list as `value` (the
    whole-collection `replace`-marker shape `lore_mutations._split_collection_value`
    reads); resolve each name to an id and rejoin."""
    rows = front_matter.get("rows")
    if not isinstance(rows, list):
        return False
    changed = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        field_name = row.get("field")
        value = row.get("value")
        if field_name not in ("tags", "assistant_tags") or not isinstance(value, str):
            continue
        names = [item.strip() for item in value.split(",") if item.strip()]
        if not names:
            continue
        if field_name == "tags":
            ids = [_resolve_or_mint_one(n, layer_root / "tags", ctx.name_to_id, "tag:tag") for n in names]
        else:
            ids = [
                _resolve_or_mint_one(n, machine_root / "tags", ctx.machine_names, "tag:assistant_tag")
                for n in names
            ]
        new_value = ",".join(i for i in ids if i)
        if new_value != value:
            row["value"] = new_value
            changed = True
    return changed


def _convert_view_expr_node(
    node: Any, ctx: ChainContext, unresolved_log: list[str]
) -> tuple[Any, bool]:
    """Step 3 (M4): one recursive walk over a `ViewExpr`-shaped tree (a saved
    view's `spec`, or a chat selector ref's `selector`) that handles BOTH
    conversions the tree can carry — `tagged: "<name>"` → `tagged: <id>`
    (looked up, never minted here: an unresolved name selects nothing under
    ADR-0036 and is left as-is, logged) and a `field: {key: "tags", ...}`
    predicate (the assistant view's TAG axis, pre-rename) → `key:
    "assistant_tags"` — rather than two passes, so `intersect`/`union`/
    `filter`/... nesting is only walked once."""
    if isinstance(node, dict):
        changed = False
        new_node: dict[str, Any] = {}
        for key, value in node.items():
            if key == "tagged" and isinstance(value, str):
                if TAG_ID_PATTERN.match(value):
                    new_node[key] = value
                    continue
                lookup = value.strip().lower()
                resolved = ctx.name_to_id.get(lookup) or ctx.machine_names.get(lookup)
                if resolved:
                    new_node[key] = resolved
                    changed = True
                else:
                    new_node[key] = value
                    unresolved_log.append(f"tagged:{value}")
                continue
            if key == "field" and isinstance(value, dict) and value.get("key") == "tags":
                new_field = dict(value)
                new_field["key"] = "assistant_tags"
                new_node[key] = new_field
                changed = True
                continue
            child, child_changed = _convert_view_expr_node(value, ctx, unresolved_log)
            new_node[key] = child
            changed = changed or child_changed
        return new_node, changed
    if isinstance(node, list):
        new_list = []
        changed = False
        for item in node:
            child, child_changed = _convert_view_expr_node(item, ctx, unresolved_log)
            new_list.append(child)
            changed = changed or child_changed
        return new_list, changed
    return node, False


def _convert_chat_ref(ref: Any, ctx: ChainContext, unresolved_log: list[str]) -> tuple[Any, bool]:
    """One `NodePickerRef`-shaped dict from a chat's `inputs`: a `tag:<kind>:
    <name>` id (the pre-migration tag-axis pick, ADR-0082 slice 2b) becomes
    `tagged:<kind>:<id>`; its `selector` (if any) walks through
    `_convert_view_expr_node` too. Any other ref (a concrete member pick, or
    an id that does not match the tag-ref shape) passes through untouched. An
    unresolvable name leaves the WHOLE ref untouched and logs it — a stale id
    is safer than a half-converted ref."""
    if not isinstance(ref, dict):
        return ref, False
    ref_id = ref.get("id")
    if not isinstance(ref_id, str):
        return ref, False
    match = _CHAT_TAG_REF_ID.match(ref_id)
    if not match:
        return ref, False
    lookup = match.group("name").strip().lower()
    resolved = ctx.name_to_id.get(lookup) or ctx.machine_names.get(lookup)
    if not resolved:
        unresolved_log.append(ref_id)
        return ref, False
    new_ref = dict(ref)
    new_ref["id"] = f"tagged:{match.group('kind')}:{resolved}"
    selector = ref.get("selector")
    if isinstance(selector, dict):
        new_selector, _ = _convert_view_expr_node(selector, ctx, unresolved_log)
        new_ref["selector"] = new_selector
    return new_ref, True


def _convert_chat_inputs(front_matter: dict[str, Any], ctx: ChainContext, unresolved_log: list[str]) -> bool:
    """Step 3 (M4): a chat's `inputs.<name>` value is the picker codec's wire
    shape (`promptInputs.ts`'s `encodePickerValue`) — a JSON-encoded STRING
    array, or (a persisted older seed) an already-decoded array. Either way,
    re-encode in the SAME shape it was found in."""
    inputs = front_matter.get("inputs")
    if not isinstance(inputs, dict):
        return False
    changed = False
    for key, raw_value in list(inputs.items()):
        was_string = isinstance(raw_value, str)
        if was_string:
            if not raw_value.strip():
                continue
            try:
                parsed = json.loads(raw_value)
            except (ValueError, TypeError):
                continue
        elif isinstance(raw_value, list):
            parsed = raw_value
        else:
            continue
        if not isinstance(parsed, list):
            continue
        new_list = []
        value_changed = False
        for item in parsed:
            new_item, item_changed = _convert_chat_ref(item, ctx, unresolved_log)
            new_list.append(new_item)
            value_changed = value_changed or item_changed
        if value_changed:
            inputs[key] = json.dumps(new_list) if was_string else new_list
            changed = True
    return changed


def _convert_prompt_input_defs(input_defs: Any) -> bool:
    """Step 3 tail (M4): a `PromptInputDefinition`-shaped list (a prompt's own
    `inputs`, or an entry type's `default_inputs`) — any `type: "tags"` item
    becomes `entity_ref_list` with a `target` carrying the tag-picker shape."""
    if not isinstance(input_defs, list):
        return False
    changed = False
    for item in input_defs:
        if isinstance(item, dict) and item.get("type") == "tags":
            item["type"] = "entity_ref_list"
            item["target"] = dict(_TAG_PICKER_SHAPE)
            changed = True
    return changed


def _convert_schema_field_def(field_def: dict[str, Any]) -> None:
    """A `MetadataFieldDefinition`/`GroupMember`-shaped dict, mutated in
    place: `type: "tags"` → `entity_ref_list` with the tag-picker
    `picker_config`."""
    field_def["type"] = "entity_ref_list"
    field_def["picker_config"] = dict(_TAG_PICKER_SHAPE)


def _convert_member_list_tags_type(members: Any) -> bool:
    """A `list[GroupMember]`-shaped value (a field's own `item_members`, or a
    reusable group's `members`): convert any `type: "tags"` entry in place."""
    if not isinstance(members, list):
        return False
    changed = False
    for member in members:
        if isinstance(member, dict) and member.get("type") == "tags":
            _convert_schema_field_def(member)
            changed = True
    return changed


def _convert_schema_fields_tags_type(fields: Any) -> bool:
    """The top-level `fields:` map: each field's own `type`, plus its
    `item_members` (ADR-0081's nested list-item shape)."""
    if not isinstance(fields, dict):
        return False
    changed = False
    for field_def in fields.values():
        if not isinstance(field_def, dict):
            continue
        if field_def.get("type") == "tags":
            _convert_schema_field_def(field_def)
            changed = True
        if _convert_member_list_tags_type(field_def.get("item_members")):
            changed = True
    return changed


def _convert_schema_groups_tags_type(groups: Any) -> bool:
    """The `groups:` map of reusable L2 group definitions: each one's `members`."""
    if not isinstance(groups, dict):
        return False
    changed = False
    for group_def in groups.values():
        if isinstance(group_def, dict) and _convert_member_list_tags_type(group_def.get("members")):
            changed = True
    return changed


def _convert_schema_entry_types_tags_type(entry_types: Any) -> bool:
    """The `entry_types:` map: each type's `default_inputs` (the prompt-input
    twin of a field-def conversion, `_convert_prompt_input_defs`)."""
    if not isinstance(entry_types, dict):
        return False
    changed = False
    for entry_type_def in entry_types.values():
        if isinstance(entry_type_def, dict) and _convert_prompt_input_defs(
            entry_type_def.get("default_inputs")
        ):
            changed = True
    return changed


def _migrate_schema_tags_type(schema_path: Path) -> None:
    """Step 4 (M4): `metadata.schema.yaml` at this layer — `type: "tags"`
    everywhere it can appear (a field, a field's list-item members, a
    reusable group's members, a type's seeded `default_inputs`). A no-op file
    (nothing to convert, or no file at all) is left untouched — no rewrite
    churn."""
    if not schema_path.exists():
        return
    try:
        data = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return
    if not isinstance(data, dict):
        return
    # A list literal, not a generator/tuple passed straight to `any()`: every
    # branch must actually RUN (each converts a different part of the tree),
    # so this must not short-circuit on the first True the way `any()` over a
    # lazily-evaluated argument would.
    results = [
        _convert_schema_fields_tags_type(data.get("fields")),
        _convert_schema_groups_tags_type(data.get("groups")),
        _convert_schema_entry_types_tags_type(data.get("entry_types")),
    ]
    changed = any(results)
    if changed:
        schema_path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n"
        )


def _migrate_one_node_document(
    path: Path, *, kind: str, layer_root: Path, machine_root: Path, ctx: ChainContext, unresolved_log: list[str]
) -> None:
    """Steps 2+3 (M4) for ONE already-collected node document: the generic
    `metadata.tags`/`metadata.assistant_tags` conversion, plus whatever
    kind-specific tree a view/chat/prompt also carries a tag reference in.
    Writes back only when something actually changed."""
    front_matter, body = _read_front_matter(path)
    if not front_matter:
        return
    changed = _convert_document_metadata(
        front_matter, kind=kind, layer_root=layer_root, machine_root=machine_root, ctx=ctx
    )
    if kind == "view":
        spec = front_matter.get("spec")
        if isinstance(spec, dict):
            new_spec, spec_changed = _convert_view_expr_node(spec, ctx, unresolved_log)
            if spec_changed:
                front_matter["spec"] = new_spec
                changed = True
    if kind == "chat" and _convert_chat_inputs(front_matter, ctx, unresolved_log):
        changed = True
    if kind == "prompt" and _convert_prompt_input_defs(front_matter.get("inputs")):
        changed = True
    if changed:
        _write_front_matter(path, front_matter, body)


def _migrate_one_override(path: Path, *, layer_root: Path, machine_root: Path, ctx: ChainContext) -> None:
    """Step 2 (M4) for one `overrides/*.md` file — its `rows[].value` where
    `field` is `tags`/`assistant_tags`."""
    front_matter, body = _read_front_matter(path)
    if not front_matter:
        return
    if _convert_override_rows(front_matter, layer_root=layer_root, machine_root=machine_root, ctx=ctx):
        _write_front_matter(path, front_matter, body)


def _migrate_layer_tags(root: Path, ctx: ChainContext) -> None:
    """v9→v10 (ADR-0082 slice 4, #1785): convert ONE layer's own on-disk
    `tags` value-type shapes into the node model. `root` is that layer's own
    folder — an ancestor being migrated ahead of the open project, or the
    open project itself; `ctx` is the running chain-wide context (mutated in
    place, so a later layer sees an earlier one's mints)."""
    from app.services import machine_settings as ms_service
    from app.services.project.overrides import OVERRIDES_FOLDER
    from app.services.project.references import NODE_FAMILIES

    machine_root = ms_service.config_path().parent
    unresolved: list[str] = []

    _mint_layer_tags_from_yaml(root, ctx)

    for family in NODE_FAMILIES:
        folder = root / family.folder_name
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.md")):
            _migrate_one_node_document(
                path,
                kind=family.kind,
                layer_root=root,
                machine_root=machine_root,
                ctx=ctx,
                unresolved_log=unresolved,
            )

    overrides_folder = root / OVERRIDES_FOLDER
    if overrides_folder.exists():
        for path in sorted(overrides_folder.glob("*.md")):
            _migrate_one_override(path, layer_root=root, machine_root=machine_root, ctx=ctx)

    _migrate_schema_tags_type(root / "metadata.schema.yaml")

    if unresolved:
        logger.warning(
            "v10 tag migration at %s: %d unresolved tag reference(s) left as-is: %s",
            root,
            len(unresolved),
            ", ".join(sorted(set(unresolved))),
        )


# Migrations run in registry order. Version numbers are history and are never
# reused or renumbered, so a retired step leaves a gap. Two gaps now: 3 (create
# project.md) was removed with #343 — it wrote a constant `id: project`, which
# collides at every layer of a nested chain; and 4 (move chat cost_usd_total
# into ai_invocations.yaml) was removed with #76 — pre-1.0 the only projects
# that would run it are recreated from scratch, so it had already served its
# purpose and was pure carrying cost. A folder sitting at a retired version is
# carried forward by the remaining steps and the final stamp-to-CURRENT_VERSION.
MIGRATIONS: list[MigrationStep] = [
    RootMigration(2, "create snippets/ folder for snippet node kind", _create_snippets_folder),
    RootMigration(5, "create research/ folder and research.structure.yaml", _create_research_structure),
    RootMigration(
        6,
        "seed cascade_fields=[pov_mode, pov] into metadata.schema.yaml (ADR-0079)",
        _backfill_narration_cascade_fields,
    ),
    RootMigration(
        7,
        "add tense to cascade_fields so it inherits down the manuscript (ADR-0079, #1737)",
        _backfill_tense_cascade_field,
    ),
    DocumentMigration(
        8,
        "lift plot:template genre from the template: block into a node-metadata field (#1744)",
        _lift_plot_template_genre,
    ),
    RootMigration(
        9,
        "move the ai_invocations ledger from a YAML list to an append-only CSV (#1801)",
        _migrate_invocations_to_csv,
    ),
    ChainMigration(
        10,
        "convert tags.yaml + tags/assistant_tags occurrences into tag-kind node "
        "references, per declared chain layer (ADR-0082 slice 4, #1785)",
        _migrate_layer_tags,
    ),
]


def read_project_version(root: Path) -> int:
    manifest_path = root / "project.yaml"
    if not manifest_path.exists():
        return 0
    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return 0
    if not isinstance(data, dict):
        return 0
    value = data.get("schema_version")
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def write_project_version(root: Path, version: int) -> None:
    manifest_path = root / "project.yaml"
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RuntimeError("project.yaml is not a YAML mapping; refusing to stamp schema_version.")
    data["schema_version"] = version
    manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def pending_migrations(current: int) -> list[MigrationStep]:
    return [m for m in MIGRATIONS if current < m.version <= CURRENT_VERSION]


def migrate_document(doc: MigratableDocument, from_version: int) -> MigratableDocument:
    """Apply the document-scoped subladder from `from_version` to CURRENT_VERSION,
    in version order, over one body — no root, no service (ADR-0071 §4). The
    isolated entry point behind the snapshot restore (slice 3) and the project
    document pass (slice 2)."""
    for step in MIGRATIONS:
        if isinstance(step, DocumentMigration) and from_version < step.version <= CURRENT_VERSION:
            doc = step.fn(doc)
    return doc


def backup_project(root: Path, from_version: int) -> Path:
    backup_dir = root / BACKUP_DIRNAME
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_path = backup_dir / f"v{from_version}-{timestamp}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            top = relative.parts[0]
            if top in SKIP_FROM_BACKUP:
                continue
            archive.write(path, relative)
    prune_old_backups(root)
    return archive_path


def prune_old_backups(root: Path, keep: int = KEEP_BACKUPS) -> None:
    backup_dir = root / BACKUP_DIRNAME
    if not backup_dir.exists():
        return
    archives = sorted(
        backup_dir.glob("v*-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for stale in archives[keep:]:
        try:
            stale.unlink()
        except OSError:
            logger.warning("Could not prune stale migration backup: %s", stale)


def migrate_project(root: Path) -> list[str]:
    """Run pending migrations for the project at `root`. Thin entry point — the
    orchestration (root steps + the document pass) lives on
    ProjectService._run_migrations (ADR-0071 §4), which needs the service's seams.
    """
    from app.scope import WorkScope
    from app.services.project_service import ProjectService

    return ProjectService(WorkScope(root=root))._run_migrations()
