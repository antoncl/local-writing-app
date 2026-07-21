"""Node-index + reference-resolution slice of ProjectService (#14 backend split).

`_build_node_index` walks every node markdown file (scenes, lore, prompts,
research, chats, plus the machine assistants layer) into an in-memory
`NodeIndex` keyed by id — and, in that same front-matter pass, extracts the
field-qualified reference edges plus their reverse adjacency map (#305, so
answering a reference-graph request no longer parses the chain three times);
the reference API (`resolve_references`, `list_reference_candidates`) and the
node-identity helpers (`_node_id_for_path`, `_path_for_node_id`,
`_safe_relative`, `_read_body_summary`) build on it. Backlinks are *not* served
from here — the frontend computes them from the reference graph (#203), and the
delete guards use `_backlinks_to_targets`; the per-node `list_backlinks` endpoint
that once lived here was retired in #325. This mixin owns that subsystem; almost
every other slice consumes `_build_node_index` / `_node_id_for_path` /
`_path_for_node_id` via `self` → MRO, so they keep resolving unchanged.

Method bodies moved verbatim. Shared helpers they call (`self._require_project`,
`self._read_yaml`, `self._read_markdown_with_front_matter`,
`self._read_front_matter_only`, `self.read_metadata_schema`,
`self.visit_layers` — the one layer walk, in `layers.py` since #329, which
stamps each layer's id, label, rank and is_root/is_machine flags so this slice
no longer builds `IndexLayer` inline) live elsewhere on the composed class.
`NodeIndex`/`NodeIndexEntry` come from the shared `node_index` module so this
slice imports them without a cycle.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.models import (
    PROJECT_NODE_FILENAME,
    MetadataSchema,
    ReferenceCandidate,
    ReferenceCandidatesResponse,
    ReferenceGraphResponse,
    ReferenceResolveResponse,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.layers import MANIFEST_FILENAME, SCHEMA_FILENAME, LayerVisitor
from app.services.project.node_index import (
    IndexLayer,
    NodeFamily,
    NodeIndex,
    NodeIndexEntry,
    ReferenceEdge,
)
from app.services.project.node_index_snapshot import (
    Manifest,
    SnapshotUnusable,
    fingerprint_for,
    snapshot_path,
)
from app.services.project.node_index_snapshot import load as snapshot_load
from app.services.project.node_index_snapshot import serialize as snapshot_serialize

log = logging.getLogger(__name__)

# The Node-shaped kinds the index walks, once per layer of the chain.
NODE_FAMILIES = [
    NodeFamily("scene", "scenes", "scene:scene"),
    # Research notes walk `research/notes/`. Treated like lore (cross-layer)
    # rather than scenes (book-scoped) — universe- or series-level research
    # notes are a natural use case.
    NodeFamily("research", "research/notes", "research:note"),
    NodeFamily("lore", "lore", "lore:lore_note"),
    NodeFamily("prompt", "prompts", "prompt:base"),
    NodeFamily("assistant", "assistants", "assistant:assistant"),
    # Reusable mutation sets (#62): body-less Node files under `mutation-sets/`.
    # Layered like lore/prompts (a werewolf transform can live at any project
    # level).
    NodeFamily("mutation_set", "mutation-sets", "mutation_set:mutation_set"),
    # Saved views (0.5.0, #35/#78): body-less Node files under `views/`, each
    # carrying a ViewSpec in front matter. Layered like mutation sets — a view
    # can live at any project level.
    NodeFamily("view", "views", "view:view"),
]

# The one family the out-of-tree machine layer contributes. Looked up rather
# than re-spelled as a literal — a second copy of the triple would drift.
MACHINE_LAYER_FAMILIES = [family for family in NODE_FAMILIES if family.kind == "assistant"]


class _NodeIndexBuilder(LayerVisitor):
    """The index build's per-layer logic, as a `LayerVisitor` (#329).

    This used to be the body of `_build_node_index`'s own `enumerate` over the
    chain. Holding it as a visitor is what keeps the traversal itself in one
    place: the walker decides *which* layers and in *what order*, this decides
    what to do at each.
    """

    def __init__(
        self,
        service: ReferencesMixin,
        *,
        index: NodeIndex,
        root: Path,
        schema: MetadataSchema | None,
    ) -> None:
        self._service = service
        self._index = index
        self._root = root
        self._schema = schema

    def visit_layer(self, layer: IndexLayer) -> None:
        for family in self._service._families_for_layer(layer):
            self._service._collect_layer_entries(
                layer=layer,
                family=family,
                index=self._index,
                duplicate_relative_to=self._root,
                schema=self._schema,
            )
        # Chat sessions live as YAML files (not Node-shaped .md), so they need
        # their own collector. Read-only for now: this makes them discoverable
        # as nodes (kind="chat") for reference graphs and the unified-CRUD
        # migration to come, but ChatSession storage remains the source of
        # truth (Phase 3b-i / decisions-node-editor-modularization).
        if layer.is_root:
            self._service._collect_chat_entries(layer=layer, index=self._index)
        if not layer.is_machine:
            self._service._collect_project_node_entry(
                layer=layer, index=self._index, schema=self._schema
            )


class _ManifestBuilder(LayerVisitor):
    """Fingerprints every file the index build will read (#306).

    A visitor over the same walk, globbing the same folders with the same
    semantics as the collectors — `*.md`, **non-recursively**, per family folder.
    That is not incidental: a recursive walk would report a nested file as an
    addition on every open, forever, because the index would never index it.

    Why re-glob rather than record paths as the collectors visit them: additions.
    A file that was never indexed has no entry to record, so a manifest derived
    from the index can only ever re-stat what it already knew — drop a `.md` into
    an ancestor's `lore/` from Explorer, or `git pull` a layer, and it stays
    invisible. Globbing is also what makes the two manifests comparable: the
    stored one and the current one come from this same code, so equality means
    what it says.
    """

    def __init__(self, service: ReferencesMixin) -> None:
        self._service = service
        self.manifest: Manifest = {}

    def record(self, path: Path) -> None:
        self.manifest[str(path)] = fingerprint_for(path)

    def visit_layer(self, layer: IndexLayer) -> None:
        for family in self._service._families_for_layer(layer):
            for path in sorted((layer.folder / family.folder_name).glob("*.md")):
                self.record(path)
        if layer.is_root:
            for path in sorted((layer.folder / "chats").glob("*.yaml")):
                self.record(path)
        if not layer.is_machine:
            # Recorded even when absent — `project.md` is required to exist
            # (#343) so its disappearance is a change, and a layer *gaining* a
            # `metadata.schema.yaml` or `project.yaml` changes how every node in
            # the chain resolves without touching a single node file.
            self.record(layer.folder / PROJECT_NODE_FILENAME)
            self.record(layer.folder / MANIFEST_FILENAME)
            self.record(layer.folder / SCHEMA_FILENAME)


class ReferencesMixin:
    def _build_index_manifest(self, root: Path) -> Manifest:
        """Fingerprint every file an index build over `root` reads.

        Per layer, over the walk — so it covers exactly the layers the walk
        actually yielded, whatever rule decided that.

        **It deliberately does not fingerprint how far the walk goes.** The
        extent rule probes ancestors *above* the outermost layer for a
        `metadata.schema.yaml`, and one appearing there lengthens the chain
        without changing any file this records. That is caught one level up, by
        comparing the walk's resulting layer folders against the snapshot's
        (`node_index_snapshot.load`): a longer chain is a different chain, and a
        different chain is a hard rebuild before freshness is even consulted.

        Checking the walk's *output* rather than its *inputs* is what keeps the
        extent question deferred where #329 put it. When #337 stipulates the
        root, or #318's wizard authors the bound, the walk yields a different
        sequence and this notices — with nothing here to edit.
        """
        builder = _ManifestBuilder(self)
        self.visit_layers(builder, root, include_machine=True)
        return builder.manifest

    def _load_index_snapshot(
        self, root: Path, *, layers: list[IndexLayer], manifest: Manifest
    ) -> NodeIndex | None:
        """The snapshot, when it is still true. None means "build it".

        Three of the failure paths are operationally distinct and deliberately
        handled differently. **Missing** is the normal first open and says
        nothing. **Corrupt** is evidence of a bug — something wrote a file we
        cannot read back — and is logged loudly even though it self-heals.
        **Version-mismatched** is expected after an upgrade, and the stale file
        is unlinked rather than left to be rewritten, so a downgrade cannot find
        a newer payload sitting under a name it trusts.
        """
        path = snapshot_path(root)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        # `ValueError` is here for `UnicodeDecodeError`: a snapshot truncated by
        # a power cut, or corrupted on disk, is *bytes* we cannot decode, and
        # that is raised by `read_text` before any JSON handling can see it.
        # Left uncaught it escapes `_build_node_index` and 500s every endpoint
        # that touches the index — a derived, self-healing file making the
        # project unopenable, which is the exact inversion of this design.
        except (OSError, ValueError) as exc:
            log.warning("Discarding an unreadable node-index snapshot at %s: %s", path, exc)
            return None
        try:
            return snapshot_load(text, root=root, layers=layers, manifest=manifest)
        except SnapshotUnusable as exc:
            if exc.reason == "corrupt":
                log.warning("Discarding an unreadable node-index snapshot at %s: %s", path, exc.detail)
            elif exc.reason == "version":
                log.info("Node-index snapshot format changed; rebuilding %s", path)
                path.unlink(missing_ok=True)
            return None

    def _write_index_snapshot(
        self, root: Path, index: NodeIndex, *, layers: list[IndexLayer], manifest: Manifest
    ) -> None:
        """Persist a freshly built index. Best-effort by construction: the
        snapshot is derived, so failing to write one costs the next open its
        speed and nothing else. A read-only project folder must not make the
        index unbuildable."""
        if index.degraded:
            # See `NodeIndex.degraded`. Writing nothing means the next open
            # rebuilds, and gets a clean index the moment the condition clears.
            log.warning("Not caching a degraded node index for %s; it will be rebuilt.", root)
            return
        try:
            self._atomic_write(snapshot_path(root), snapshot_serialize(index, root=root, layers=layers, manifest=manifest))
        except OSError as exc:
            log.warning("Could not write the node-index snapshot for %s: %s", root, exc)

    def _build_node_index(self, root: Path | None = None) -> NodeIndex:
        """Walk the layer chain once, producing both the id→entry map and the
        reference edges (#305).

        Edge extraction is schema-driven, so the merged schema is read up front
        and threaded into the collectors — the front matter each file yields is
        parsed exactly once, for both purposes.

        **A schema that will not load must not make the index unbuildable.**
        Reading the schema is new work on this path: before #305 the index never
        touched it, so a typo in any layer's `metadata.schema.yaml` — including
        an *ancestor's*, which no one editing this book would think to look at —
        would otherwise take down every index consumer, from `list_lore_entries`
        to `_path_for_node_id` on each save. The failure degrades to "no edges"
        plus an `index.errors` row. Callers that want the schema still fail
        loudly on their own read; this one does not fail on their behalf.
        """
        root = root or self._require_project()
        layers = self.collect_layers(root, include_machine=True)
        # Fingerprinted **before** the build, not after. A file written while
        # the build runs is then either missed by both (consistent) or indexed
        # but unrecorded — which reads as an addition next time and rebuilds.
        # Stamping afterwards inverts that: the manifest would vouch for content
        # the index never saw, and the snapshot would be silently short a node.
        manifest = self._build_index_manifest(root)
        cached = self._load_index_snapshot(root, layers=layers, manifest=manifest)
        if cached is not None:
            return cached
        index = NodeIndex()
        try:
            schema: MetadataSchema | None = self.read_metadata_schema()
        # Malformed YAML arrives as ProjectServiceError (`_read_yaml` wraps it),
        # a bad shape as pydantic ValidationError (a ValueError), and a locked
        # or unreadable file as OSError.
        except (ProjectServiceError, ValueError, OSError) as exc:
            schema = None
            index.errors.append(f"Invalid metadata schema; no reference edges were indexed: {exc}")
            # An unreadable schema costs the *whole project* its reference
            # edges, so persisting that result would freeze an empty reference
            # graph and backlinks panel in place — the schema file is unchanged,
            # so every later open matches the manifest and serves it. One
            # unlucky read (a cloud-sync placeholder, an AV scanner, a
            # concurrent checkout) would otherwise brick the graph until the
            # user edited something unrelated. A malformed schema is content and
            # is cached; a schema we could not *read* is not.
            index.degraded = isinstance(exc, OSError)
        # One walk, machine layer included (#329). It comes first and carries
        # assistants only — it lives outside the project tree and holds the
        # user's roster. Project layers follow outermost-ancestor first, so a
        # descendant entry overwrites an ancestor's on collision.
        self.visit_layers(
            _NodeIndexBuilder(self, index=index, root=root, schema=schema),
            root,
            include_machine=True,
        )
        # One post-walk pass: order the candidate lists innermost-first, derive
        # `by_id` / `edges_by_src` from the winners, emit the shadow warnings and
        # build the reverse edge map. Nothing before this point resolves a
        # shadow — that is what stops the walk destroying an ancestor.
        index.resolve()
        self._write_index_snapshot(root, index, layers=layers, manifest=manifest)
        return index

    def _collect_chat_entries(self, *, layer: IndexLayer, index: NodeIndex) -> None:
        """Walk <project>/chats/*.yaml and add an index entry per session.

        Storage stays YAML — this is just a discovery layer so chats are
        addressable from the unified node index alongside other kinds.
        """
        chats_dir = layer.folder / "chats"
        if not chats_dir.exists():
            return
        for path in sorted(chats_dir.glob("*.yaml")):
            try:
                data = self._read_yaml(path)
            except Exception as exc:
                index.errors.append(f"Failed to read chat session {path.name}: {exc}")
                # Same rule as the schema read: a chat we could not open is
                # missing from the index entirely, and its file is unchanged, so
                # a snapshot would keep it missing across every later open.
                index.degraded = index.degraded or isinstance(exc, OSError)
                continue
            if not isinstance(data, dict):
                continue
            raw_id = data.get("id")
            if not isinstance(raw_id, str) or not raw_id.strip():
                continue
            chat_id = raw_id.strip()
            raw_title = data.get("title")
            title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else "Untitled chat"
            entry = NodeIndexEntry(
                id=chat_id,
                kind="chat",
                entry_type="chat:chat_session",
                path=path,
                title=title,
                source_layer_id=layer.id,
                source_layer_label=layer.label,
            )
            if index.candidates.get(chat_id):
                # Chat ids are prefixed (`chat_…`) and minted via _new_id, so
                # cross-kind collisions shouldn't happen in practice. If one
                # ever does, surface it rather than silently shadowing: `kind`
                # partitions identity, so a chat and a lore entry sharing an id
                # are two things colliding, not one shadowing the other.
                index.errors.append(
                    f"Chat id {chat_id} collides with an existing entry."
                )
                continue
            index.add(entry)

    def _collect_project_node_entry(
        self, *, layer: IndexLayer, index: NodeIndex, schema: MetadataSchema | None = None
    ) -> None:
        """Index the layer's `project.md` (#334).

        The project node sits at the layer root rather than in a kind-folder, so
        `_collect_layer_entries`' `folder/folder_name/*.md` glob never reached
        it — the one Node-shaped file the index did not see.

        Its identity is read off the file like every other node's. The file
        *name* is the same word at every layer, which is exactly why the id must
        not be (#343) — `_require_node_id` refuses the filename-stem fallback
        here, because the stem would hand every layer the same id.

        `project.md` is required to exist (`create_project` writes it first, and
        `validate_project` / `repair_project` own the damaged case since #343), so
        a layer without one contributes no entry rather than an entry pointing at
        a file that isn't there.
        """
        path = layer.folder / PROJECT_NODE_FILENAME
        if not path.exists():
            return
        try:
            front_matter = self._read_front_matter_only(path, strict=True)
            node_id = self._require_node_id(path, front_matter)
        except ProjectServiceError as exc:
            index.errors.append(exc.message)
            return
        duplicate = index.entry_for_layer(node_id, layer.id)
        if duplicate is not None:
            # The same guard every other collector applies. Without it the
            # `(layer, id)` edge key stops being a key, and two files at one
            # layer fight over one edge list.
            index.errors.append(
                f"Duplicate front matter id {node_id} in "
                f"{self._safe_relative(duplicate.path, layer.folder)} and "
                f"{self._safe_relative(path, layer.folder)}."
            )
            return
        raw_entry_type = front_matter.get("entry_type") or "project:project"
        entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "project:project"
        raw_title = front_matter.get("title")
        title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else layer.label
        entry = NodeIndexEntry(
            id=node_id,
            kind="project",
            entry_type=entry_type,
            path=path,
            title=title,
            source_layer_id=layer.id,
            source_layer_label=layer.label,
        )
        index.add(entry)
        try:
            edges = self._reference_edges_for_entry(entry, schema, front_matter=front_matter)
        except ProjectServiceError as exc:
            index.errors.append(f"{self._safe_relative(path, layer.folder)}: {exc.message} Its references were not indexed.")
            edges = []
        if edges:
            index.edges_by_layer_src[(layer.id, node_id)] = edges

    def _families_for_layer(self, layer: IndexLayer) -> list[NodeFamily]:
        """Which node families this layer contributes — the per-layer logic the
        index walk used to inline (#329).

        The machine layer is out-of-tree: assistants only. Scenes stay
        book-scoped, so they come from the open project alone.
        """
        if layer.is_machine:
            return MACHINE_LAYER_FAMILIES
        return [family for family in NODE_FAMILIES if family.kind != "scene" or layer.is_root]

    def _collect_machine_layer_assistants(
        self,
        index: NodeIndex,
        *,
        duplicate_relative_to: Path,
        schema: MetadataSchema | None = None,
    ) -> None:
        """Collect the machine layer on its own, for the no-project-open case.

        With a project open the machine layer is an ordinary layer in the walk
        (`visit_layers(..., include_machine=True)`); this stays for
        `_build_assistant_index`, which serves the assistant roster before any
        project has been opened and so has no chain to walk.
        """
        layer = self.machine_layer()
        if layer is None:
            return
        for family in self._families_for_layer(layer):
            self._collect_layer_entries(
                layer=layer,
                family=family,
                index=index,
                duplicate_relative_to=duplicate_relative_to,
                schema=schema,
            )

    def _collect_layer_entries(
        self,
        *,
        layer: IndexLayer,
        family: NodeFamily,
        index: NodeIndex,
        duplicate_relative_to: Path,
        schema: MetadataSchema | None = None,
    ) -> None:
        folder = layer.folder
        for path in sorted((folder / family.folder_name).glob("*.md")):
            try:
                front_matter = self._read_front_matter_only(path, strict=True)
            except ProjectServiceError as exc:
                index.errors.append(exc.message)
                continue

            raw_node_id = front_matter.get("id")
            if raw_node_id is None:
                node_id = path.stem
                index.warnings.append(
                    f"{family.kind.title()} file {self._safe_relative(path, folder)} is missing front matter id; using filename stem as legacy id."
                )
            elif isinstance(raw_node_id, str) and raw_node_id.strip():
                node_id = raw_node_id.strip()
            else:
                node_id = path.stem
                index.errors.append(
                    f"{family.kind.title()} file {self._safe_relative(path, folder)} has invalid front matter id; it must be text."
                )

            raw_entry_type = front_matter.get("entry_type") or family.default_entry_type
            entry_type = raw_entry_type if isinstance(raw_entry_type, str) else family.default_entry_type
            raw_title = front_matter.get("title")
            title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else node_id
            entry = NodeIndexEntry(
                id=node_id,
                kind=family.kind,
                entry_type=entry_type,
                path=path,
                title=title,
                source_layer_id=layer.id,
                source_layer_label=layer.label,
            )
            duplicate = index.entry_for_layer(node_id, layer.id)
            if duplicate is not None:
                # Two files claiming one id *at the same layer* — an error, not a
                # shadow. Shadowing is a relationship between layers; within one
                # layer there is no order to resolve by.
                index.errors.append(
                    f"Duplicate front matter id {node_id} in "
                    f"{self._safe_relative(duplicate.path, duplicate_relative_to)} and "
                    f"{self._safe_relative(path, duplicate_relative_to)}."
                )
                continue
            # A descendant claiming an ancestor's id joins the candidate list;
            # nothing is overwritten. The shadow warning is emitted once, by
            # `index.resolve()`, where the whole list is visible.
            index.add(entry)
            # Same front matter, no second read: the edges this node declares
            # are extracted here rather than in a later per-entry pass (#305).
            # Keyed by (layer, id) for the same reason the entry is: a shadowed
            # ancestor must keep its edges, or un-shadowing it on delete (#307)
            # would restore the node with its references silently missing.
            try:
                edges = self._reference_edges_for_entry(entry, schema, front_matter=front_matter)
            except ProjectServiceError as exc:
                # `metadata:` that isn't a mapping. The node still indexes — it
                # just contributes no edges — but that has to be *said*, or its
                # references vanish from the graph and the backlinks panel with
                # no signal anywhere.
                index.errors.append(
                    f"{self._safe_relative(path, duplicate_relative_to)}: {exc.message} "
                    f"Its references were not indexed."
                )
                edges = []
            if edges:
                index.edges_by_layer_src[(layer.id, node_id)] = edges

    def _safe_relative(self, path: Path, anchor: Path) -> Path | str:
        try:
            return path.relative_to(anchor)
        except ValueError:
            return path

    def _front_matter_id(self, path: Path, front_matter: dict[str, Any] | None = None) -> str | None:
        """The one place a node's identity is read off a file. None if absent."""
        if front_matter is None:
            front_matter = self._read_front_matter_only(path, strict=True)
        raw_node_id = front_matter.get("id")
        if isinstance(raw_node_id, str) and raw_node_id.strip():
            return raw_node_id.strip()
        return None

    def _node_id_for_path(self, path: Path, front_matter: dict[str, Any] | None = None) -> str:
        """…or the filename stem. The legacy rule, sound while a node's file is
        named from the id it was written with."""
        return self._front_matter_id(path, front_matter) or path.stem

    def _require_node_id(self, path: Path, front_matter: dict[str, Any] | None = None) -> str:
        """…or refuse. For a file whose name carries no identity of its own:
        `project.md` is the same word at every layer (#343), so the stem would
        hand every layer the same id, and minting one here would invent an
        identity that reaches no file."""
        node_id = self._front_matter_id(path, front_matter)
        if node_id is None:
            raise ProjectServiceError(
                f"{path.name} has no front matter id. It identifies the node; restore it or recreate the file.",
                422,
            )
        return node_id

    def _path_for_node_id(self, node_id: str, kind: str) -> Path:
        root = self._require_project()
        index = self._build_node_index(root)
        entry = index.by_id.get(node_id)
        if entry and entry.kind == kind:
            return entry.path
        folder_by_kind = {
            "scene": "scenes",
            "lore": "lore",
            "prompt": "prompts",
            "research": "research/notes",
            "mutation_set": "mutation-sets",
            "view": "views",
        }
        label_by_kind = {
            "scene": "Scene",
            "lore": "Lore Entry",
            "prompt": "Prompt",
            "research": "Research Note",
            "mutation_set": "Mutation set",
            "view": "View",
        }
        fallback_folder = folder_by_kind.get(kind, "lore")
        fallback_path = root / fallback_folder / f"{node_id}.md"
        if fallback_path.exists():
            return fallback_path
        raise ProjectServiceError(f"{label_by_kind.get(kind, 'Entry')} {node_id} does not exist.", 404)

    def _read_body_summary(self, path: Path, *, max_chars: int = 160) -> str:
        try:
            with path.open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
                if first_line.strip() == "---":
                    for line in handle:
                        if line.strip() == "---":
                            break
                for line in handle:
                    text = line.strip()
                    if not text or text.startswith("#"):
                        continue
                    if len(text) > max_chars:
                        return text[: max_chars - 1].rstrip() + "…"
                    return text
        except OSError:
            return ""
        return ""

    def _entry_type_matches(self, entry_type_id: str, target_entry_type: str, schema: MetadataSchema) -> bool:
        if entry_type_id == target_entry_type:
            return True
        seen: set[str] = set()
        current = schema.entry_types.get(entry_type_id)
        while current and current.parent and current.parent not in seen:
            if current.parent == target_entry_type:
                return True
            seen.add(current.parent)
            current = schema.entry_types.get(current.parent)
        return False

    def _candidate_from_index_entry(self, entry: NodeIndexEntry, *, include_summary: bool) -> ReferenceCandidate:
        return ReferenceCandidate(
            id=entry.id,
            title=entry.title or entry.id,
            kind=entry.kind,
            entry_type=entry.entry_type,
            summary=self._read_body_summary(entry.path) if include_summary else "",
            found=True,
            source_layer_id=entry.source_layer_id,
            source_layer_label=entry.source_layer_label,
        )

    def resolve_references(self, ids: list[str]) -> ReferenceResolveResponse:
        index = self._build_node_index()
        candidates: list[ReferenceCandidate] = []
        for node_id in ids:
            entry = index.by_id.get(node_id)
            if entry is None:
                candidates.append(
                    ReferenceCandidate(id=node_id, title=node_id, kind="", entry_type="", summary="", found=False)
                )
                continue
            candidates.append(self._candidate_from_index_entry(entry, include_summary=True))
        return ReferenceResolveResponse(candidates=candidates)

    def _reference_edges_for_entry(
        self,
        entry: NodeIndexEntry,
        schema: MetadataSchema | None,
        *,
        front_matter: dict[str, Any] | None = None,
    ) -> list[ReferenceEdge]:
        """The field-qualified edges one node declares through its entity_ref*
        fields, in field-declaration order.

        The single point where an edge is derived from a node — the index walk
        passes the front matter it already parsed; re-extraction for a single
        changed file re-reads it. Empty when the node has no schema type, is
        unreadable, or references nothing.

        Raises `ProjectServiceError` when the node's `metadata:` is not a
        mapping. That is deliberately *not* swallowed here: the index walk
        records it against the file, and a caller re-extracting one node wants
        the error rather than a silently empty result.
        """
        if schema is None:
            return []
        entry_definition = schema.entry_types.get(entry.entry_type)
        if entry_definition is None:
            return []
        if front_matter is None:
            try:
                front_matter = self._read_front_matter_only(entry.path, strict=True)
            except ProjectServiceError:
                return []
        metadata = self._normalise_metadata(front_matter.get("metadata"), entry.path)
        edges: list[ReferenceEdge] = []
        for field_id in entry_definition.fields:
            field = schema.fields.get(field_id)
            if field is None:
                continue
            edges.extend(self._edges_from_field(entry.id, field_id, field.type, metadata.get(field_id)))
        return edges

    def _edges_from_field(
        self, src: str, field_id: str, field_type: str, value: object
    ) -> list[ReferenceEdge]:
        """The edges one `entity_ref` / `entity_ref_list` value contributes.

        Deduped within the field — a target listed twice is one edge — but not
        across fields, since the field is part of the edge's identity.
        """
        if field_type == "entity_ref":
            candidates: list[object] = [value]
        elif field_type == "entity_ref_list" and isinstance(value, list):
            candidates = list(value)
        else:
            return []
        targets = [item for item in candidates if isinstance(item, str) and item]
        return [
            ReferenceEdge(src=src, dst=target, field_id=field_id)
            for target in dict.fromkeys(targets)
        ]

    def reference_graph(self) -> ReferenceGraphResponse:
        """Forward reference adjacency for the whole project (#184 Phase 2).

        A projection of the edges the index already carries — the ids each node
        references through any `entity_ref` / `entity_ref_list` field, flattened
        across fields and deduped in field-declaration order. The frontend
        inverts this into a reverse index the view evaluator's `references`
        computed field projects over. Only nodes that reference something appear
        as keys."""
        node_index = self._build_node_index()
        # `edges_by_src` never holds an empty list, so every key is a node that
        # references something — no filtering needed here.
        refs = {
            src: list(dict.fromkeys(edge.dst for edge in edges))
            for src, edges in node_index.edges_by_src.items()
        }
        return ReferenceGraphResponse(refs=refs)

    def list_reference_candidates(
        self,
        *,
        kind: str | None = None,
        entry_type: str | None = None,
        exclude_id: str | None = None,
    ) -> ReferenceCandidatesResponse:
        index = self._build_node_index()
        schema = self.read_metadata_schema() if entry_type else None
        candidates: list[ReferenceCandidate] = []
        for entry in index.by_id.values():
            if exclude_id and entry.id == exclude_id:
                continue
            if kind and entry.kind != kind:
                continue
            if entry_type and schema is not None and not self._entry_type_matches(entry.entry_type, entry_type, schema):
                continue
            candidates.append(self._candidate_from_index_entry(entry, include_summary=False))
        candidates.sort(key=lambda candidate: (candidate.entry_type, candidate.title.lower(), candidate.id))
        return ReferenceCandidatesResponse(candidates=candidates)
