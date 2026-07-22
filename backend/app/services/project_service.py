from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from app.models import (
    Backlink,
    LoreEntry,
    MetadataSchema,
    MetadataValue,
    Scene,
)
from app.scope import WorkScope
from app.services.migrations import migrate_project
from app.services.project.ai_invocations import AiInvocationsMixin
from app.services.project.assistants import AssistantEntriesMixin
from app.services.project.chats import ChatSessionsMixin
from app.services.project.computed_metadata import ComputedMetadataMixin
from app.services.project.embedded_todos import EmbeddedTodosMixin

# Re-exported so the historic import path
# `from app.services.project_service import ProjectServiceError` keeps working.
from app.services.project.errors import ProjectServiceError
from app.services.project.layers import LayerWalkMixin
from app.services.project.lifecycle import ProjectLifecycleMixin
from app.services.project.lore import LoreEntriesMixin
from app.services.project.lore_mutations import LoreMutationsMixin
from app.services.project.manuscript import ManuscriptMixin
from app.services.project.metadata_values import MetadataValuesMixin
from app.services.project.mutation_sets import MutationSetEntriesMixin
from app.services.project.node_index_patch import NodeIndexPatchMixin
from app.services.project.node_ops import NodeOpsMixin
from app.services.project.project_node import ProjectNodeMixin
from app.services.project.prompts import PromptEntriesMixin
from app.services.project.references import ReferencesMixin
from app.services.project.research import ResearchNotesMixin
from app.services.project.scene_snapshots import SceneSnapshotsMixin
from app.services.project.scene_todos import SceneTodoAnchorsMixin
from app.services.project.schema import MetadataSchemaMixin
from app.services.project.search import SearchMixin
from app.services.project.tags import TagsMixin
from app.services.project.todos import TodosMixin
from app.services.project.views import ViewsMixin

logger = logging.getLogger(__name__)


class ProjectService(
    AiInvocationsMixin,
    AssistantEntriesMixin,
    ChatSessionsMixin,
    ComputedMetadataMixin,
    EmbeddedTodosMixin,
    LoreEntriesMixin,
    LoreMutationsMixin,
    LayerWalkMixin,
    ManuscriptMixin,
    MetadataSchemaMixin,
    MetadataValuesMixin,
    NodeIndexPatchMixin,
    NodeOpsMixin,
    ProjectLifecycleMixin,
    ProjectNodeMixin,
    PromptEntriesMixin,
    ReferencesMixin,
    ResearchNotesMixin,
    SceneSnapshotsMixin,
    SceneTodoAnchorsMixin,
    SearchMixin,
    TagsMixin,
    TodosMixin,
    MutationSetEntriesMixin,
    ViewsMixin,
):
    def __init__(self, scope: WorkScope | None = None) -> None:
        """Bind this service to one unit of work's scope, for good (#399).

        The scope is the *only* instance state, and it is immutable: `root_path`
        is a read-only property, so no helper can re-point a service mid-unit
        and nothing later in the unit can observe a different project than the
        one it started in (ADR-0045). `None` means no project is open — a real
        state the machine-level assistant surfaces run in — and every caller
        that needs a root asks through `_require_project()`.

        Use `opened_at` / `created_at` to get a bound service from a path.
        """
        self._scope = scope

    @property
    def scope(self) -> WorkScope | None:
        return self._scope

    @property
    def root_path(self) -> Path | None:
        return self._scope.root if self._scope is not None else None

    @property
    def last_migrations(self) -> tuple[str, ...]:
        return self._scope.migrations_applied if self._scope is not None else ()

    @classmethod
    def created_at(
        cls, root_path: Path, title: str, projects_base_folder: Path | None = None
    ) -> ProjectService:
        """Scaffold a new project on disk and return a service bound to it."""
        service = cls(WorkScope(root=root_path.expanduser().resolve()))
        service._scaffold_new_project(title, projects_base_folder)
        return service

    @classmethod
    def opened_at(cls, root_path: Path, projects_base_folder: Path | None = None) -> ProjectService:
        """Migrate an existing project folder and return a service bound to it."""
        root = root_path.expanduser().resolve()
        if not (root / "project.yaml").exists():
            raise ProjectServiceError("No project.yaml found in that folder.", 404)
        try:
            migrations = migrate_project(root)
        except Exception as exc:  # noqa: BLE001
            raise ProjectServiceError(f"Project migration failed: {exc}", 500) from exc
        service = cls(WorkScope(root=root, migrations_applied=tuple(migrations)))
        if projects_base_folder is not None:
            service._rebase_projects_base_folder(projects_base_folder)
        return service

    def _entry_markdown_paths(self, root: Path) -> list[Path]:
        return [*(root / "scenes").glob("*.md"), *(root / "lore").glob("*.md")]

    def _is_relative_to(self, path: Path, possible_parent: Path) -> bool:
        try:
            path.resolve().relative_to(possible_parent.resolve())
        except ValueError:
            return False
        return True

    def _initial_metadata_from_defaults(
        self, entry_type_id: str, schema: MetadataSchema
    ) -> dict[str, MetadataValue]:
        """Seed a new entry's metadata with each field's `default` (#38).

        Walks the resolved field list for `entry_type_id` (which already
        includes inherited fields), looks up each field on the schema, and
        copies any non-null `default` into the result. Computed fields
        never seed — they're derived at read time. Fields that don't carry
        a default (None) are skipped, preserving the previous "blank by
        default" behaviour wherever no author opt-in exists.
        """
        entry_type = schema.entry_types.get(entry_type_id)
        if entry_type is None:
            return {}
        out: dict[str, MetadataValue] = {}
        for field_id in entry_type.fields:
            field = schema.fields.get(field_id)
            if field is None or field.default is None:
                continue
            if field.type == "computed":
                continue
            out[field_id] = deepcopy(field.default)
        return out

    def _backlinks_to_targets(self, target_ids: set[str], *, exclude_source_ids: set[str] | None = None) -> list[Backlink]:
        """What references any of `target_ids` — the delete guards' question.

        Reads the index's reverse adjacency map (#305), same as `list_backlinks`.
        Until #305 this was a second, independent copy of that walk, and the two
        drifted the moment either changed: one would report a node as
        unreferenced while the other refused the delete over the same node.
        One source of edges, one answer.

        Note the de-dup: a source that reaches the target set through two fields
        is two edges, and both are legitimate rows (they name different fields),
        but a source reaching *several* targets through the *same* field must
        still be one row — the caller asks "what points into this set", not
        "how many ways".
        """
        if not target_ids:
            return []
        excluded = exclude_source_ids or set()
        node_index = self._build_node_index()
        schema = self.read_metadata_schema()
        backlinks: list[Backlink] = []
        seen: set[tuple[str, str]] = set()
        for target_id in target_ids:
            for edge in node_index.edges_by_dst.get(target_id, []):
                if edge.src in excluded or (edge.src, edge.field_id) in seen:
                    continue
                entry = node_index.by_id.get(edge.src)
                field = schema.fields.get(edge.field_id)
                if entry is None or field is None:
                    continue
                seen.add((edge.src, edge.field_id))
                backlinks.append(
                    Backlink(
                        id=entry.id,
                        title=entry.title or entry.id,
                        kind=entry.kind,
                        entry_type=entry.entry_type,
                        field_id=edge.field_id,
                        field_name=field.name,
                    )
                )
        backlinks.sort(key=lambda link: (link.kind, link.title.lower(), link.field_id))
        return backlinks

    def _check_entry_type_kind(self, entry_type: str, expected_kind: str) -> None:
        schema = self.read_metadata_schema()
        definition = schema.entry_types.get(entry_type)
        if definition is None:
            raise ProjectServiceError(f"Unknown entry_type {entry_type}.", 422)
        if definition.kind != expected_kind:
            raise ProjectServiceError(
                f"Entry type {entry_type} is kind '{definition.kind}', expected '{expected_kind}'.",
                422,
            )
        if definition.abstract:
            raise ProjectServiceError(
                f"Cannot create entries of abstract entry_type {entry_type}.",
                422,
            )

    # --- Chat sessions (Phase 3) ---
    #
    # Persistent chat sessions live in `<project>/chats/<chat_id>.yaml` —
    # a sidecar store, not a Node kind. Their CRUD lives in
    # ChatSessionsMixin (services/project/chats.py). `_utcnow_iso` stays here
    # as a generic timestamp utility that both the chat writer and the
    # AiInvocationsMixin (services/project/ai_invocations.py) consume.

    @staticmethod
    def _utcnow_iso() -> str:
        # Microsecond precision keeps sort order stable across rapid back-to-back
        # saves (e.g. user creates two chats and saves them in the same second).
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def _write_node_entry_file(
        self,
        path: Path,
        node_id: str,
        title: str,
        entry_type: str,
        metadata: dict[str, Any],
        body: str,
        *,
        extra: dict[str, Any] | None = None,
        omit_empty_metadata: bool = False,
    ) -> None:
        front_matter_data: dict[str, Any] = {
            "id": node_id,
            "title": title,
            "entry_type": entry_type,
        }
        # A prompt has almost nothing to say about itself — title + entry_type
        # is essentially it — and its Jinja body is content, not metadata. So
        # prompts drop the `metadata: {}` wrapper entirely when empty (#28). A
        # non-empty map (a future model_hint etc.) is still written. Other kinds
        # keep emitting `metadata` unconditionally.
        if not (omit_empty_metadata and not metadata):
            front_matter_data["metadata"] = metadata
        if extra:
            # Extra top-level front-matter keys (e.g. `inputs` on prompt entries).
            # Empty/None values are skipped to keep the file tidy.
            for key, value in extra.items():
                if value in (None, "", [], {}):
                    continue
                front_matter_data[key] = value
        front_matter = yaml.safe_dump(
            front_matter_data,
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body_text = body.rstrip() + "\n" if body.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body_text}")

    def _require_project(self) -> Path:
        if self.root_path is None:
            raise ProjectServiceError("No project is open.", 409)
        return self.root_path

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            try:
                data = yaml.safe_load(handle) or {}
            except yaml.YAMLError as exc:
                # Same contract as the front-matter readers below: a syntax
                # error in a hand-edited file is a 422 with the parser's
                # message, not a raw YAMLError escaping to a 500.
                raise ProjectServiceError(f"Malformed YAML in {path.name}: {exc}", 422) from exc
        if not isinstance(data, dict):
            raise ProjectServiceError(f"{path.name} must contain a YAML object.")
        return data

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> None:
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        self._atomic_write(path, text)

    def _atomic_write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp:
            temp.write(text)
            temp.flush()
            temp_path = Path(temp.name)
        temp_path.replace(path)

    def _read_markdown_with_front_matter(self, path: Path, *, strict: bool = False) -> tuple[dict[str, Any], str]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return {}, text
        _, rest = text.split("---\n", 1)
        if "\n---\n" not in rest:
            if strict:
                raise ProjectServiceError(f"Malformed front matter in {path.name}: missing closing ---.", 422)
            return {}, text
        front, body = rest.split("\n---\n", 1)
        # Strip the format separator newlines between the closing `---` and the
        # body. Without this, a save/read round-trip accumulates one extra
        # leading "\n" each cycle, because the writer emits `---\n\n{body}` but
        # the split on `\n---\n` leaves one `\n` attached to the body — which
        # then gets written back with the writer's own separator on top.
        body = body.lstrip("\n")
        try:
            data = yaml.safe_load(front) or {}
        except yaml.YAMLError as exc:
            if strict:
                raise ProjectServiceError(f"Malformed front matter in {path.name}: {exc}", 422) from exc
            return {}, text
        if not isinstance(data, dict):
            if strict:
                raise ProjectServiceError(f"Malformed front matter in {path.name}: front matter must be a YAML object.", 422)
            data = {}
        return data, body

    def _read_front_matter_only(self, path: Path, *, strict: bool = False) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            first_line = handle.readline()
            if first_line.strip() != "---":
                return {}
            lines: list[str] = []
            for line in handle:
                if line.strip() == "---":
                    break
                lines.append(line)
            else:
                if strict:
                    raise ProjectServiceError(f"Malformed front matter in {path.name}: missing closing ---.", 422)
                return {}
        try:
            data = yaml.safe_load("".join(lines)) or {}
        except yaml.YAMLError as exc:
            if strict:
                raise ProjectServiceError(f"Malformed front matter in {path.name}: {exc}", 422) from exc
            return {}
        if not isinstance(data, dict):
            if strict:
                raise ProjectServiceError(f"Malformed front matter in {path.name}: front matter must be a YAML object.", 422)
            return {}
        return data

    def _write_markdown_with_front_matter(self, path: Path, front_matter: dict[str, Any], body: str) -> None:
        front_matter_text = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip()
        self._atomic_write(path, f"---\n{front_matter_text}\n---\n{body}")

    _FILENAME_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
    _FILENAME_WHITESPACE = re.compile(r"\s+")
    _FILENAME_WINDOWS_RESERVED = frozenset(
        {"CON", "PRN", "AUX", "NUL"}
        | {f"COM{i}" for i in range(1, 10)}
        | {f"LPT{i}" for i in range(1, 10)}
    )

    def _sanitize_filename(self, title: str) -> str:
        sanitized = self._FILENAME_ILLEGAL_CHARS.sub("_", title)
        sanitized = self._FILENAME_WHITESPACE.sub(" ", sanitized).strip()
        sanitized = sanitized.rstrip(". ")
        if len(sanitized) > 100:
            sanitized = sanitized[:100].rstrip(". ")
        if not sanitized:
            sanitized = "Untitled"
        base = sanitized.split(".")[0].upper()
        if base in self._FILENAME_WINDOWS_RESERVED:
            sanitized = "_" + sanitized
        return sanitized

    def _unique_filepath(self, folder: Path, sanitized: str, current_path: Path | None = None) -> Path:
        current_resolved = current_path.resolve() if current_path else None
        candidate = folder / f"{sanitized}.md"
        if not candidate.exists() or (current_resolved and candidate.resolve() == current_resolved):
            return candidate
        i = 2
        while True:
            candidate = folder / f"{sanitized} ({i}).md"
            if not candidate.exists() or (current_resolved and candidate.resolve() == current_resolved):
                return candidate
            i += 1

    def _filepath_for_new_node(self, folder: Path, title: str) -> Path:
        return self._unique_filepath(folder, self._sanitize_filename(title))

    def _maybe_rename_node_file(self, path: Path, new_title: str) -> Path:
        sanitized = self._sanitize_filename(new_title)
        # The file already owns a valid name for this title when its stem is the
        # sanitized title or that title with a collision suffix ("Name" /
        # "Name (2)"). Renaming purely to drop a freed-up suffix churns a
        # perfectly good filename on every save (and risks the transient-lock
        # failure below) — so rename only when the title genuinely changed away
        # from the current name, not to re-canonicalize an owned one.
        if self._filename_represents_title(path.stem, sanitized):
            return path
        target = self._unique_filepath(path.parent, sanitized, current_path=path)
        if target == path:
            return path
        try:
            self._rename_with_retry(path, target)
        except OSError:
            # The on-disk filename is cosmetic — the front-matter `id` is the
            # canonical identity (filenames are not), and reads resolve by id.
            # The content is already saved by this point, so a rename failure
            # (a transient Windows lock that outlasts the retries, or any other
            # OS error) must not fail the save. Keep the current filename; a
            # later save re-attempts the rename.
            logger.warning("kept filename %s; rename to %s failed", path.name, target.name)
            return path
        return target

    @staticmethod
    def _filename_represents_title(stem: str, sanitized_title: str) -> bool:
        # True when `stem` is the sanitized title, or that title with a numeric
        # collision suffix ("Name" or "Name (2)") — i.e. the file already owns a
        # valid name for this title and needs no rename.
        return re.fullmatch(rf"{re.escape(sanitized_title)}(?: \(\d+\))?", stem) is not None

    @staticmethod
    def _rename_with_retry(path: Path, target: Path, *, attempts: int = 5, delay: float = 0.05) -> None:
        # Windows briefly locks a just-written file (Defender / the search
        # indexer scans it) — the rename right after an atomic write then hits
        # PermissionError (WinError 32). The lock clears in milliseconds, so
        # back off and retry before giving up.
        for attempt in range(attempts):
            try:
                path.rename(target)
                return
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(delay)

    def _write_scene_file(self, path: Path, scene: Scene) -> None:
        front_matter = yaml.safe_dump(
            {
                "id": scene.id,
                "title": scene.title,
                "entry_type": scene.entry_type,
                "status": scene.status,
                "metadata": scene.metadata,
            },
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body = scene.body.rstrip() + "\n" if scene.body.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body}")

    def _write_lore_entry_file(self, path: Path, entry: LoreEntry) -> None:
        front_matter = yaml.safe_dump(
            {
                "id": entry.id,
                "title": entry.title,
                "entry_type": entry.entry_type,
                "metadata": entry.metadata,
            },
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body = entry.body.rstrip() + "\n" if entry.body.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body}")

    def _revision(self, path: Path) -> str:
        digest = hashlib.sha256()
        digest.update(path.read_bytes())
        return digest.hexdigest()

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:10]}"
