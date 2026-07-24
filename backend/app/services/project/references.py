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
from app.services.project.node_index_gate import ResolvedIndex, node_index_gate
from app.services.project.node_index_patch import PatchNotApplicable
from app.services.project.node_index_snapshot import (
    LoadedSnapshot,
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

# Every kind whose files the index extracts reference edges from: the node
# families above, plus the per-layer project node (#334), which lives at the
# layer root rather than in a kind folder and so is collected separately.
# Chats are absent on purpose — they are YAML sessions, indexed for
# addressability only, and no collector derives edges from them.
#
# Derived rather than re-spelled, because the two consumers that must agree
# with edge extraction are destructive-adjacent: `_purge_references_to` rewrites
# the user's files, and `_strip_dangling_references` hides values on read. A
# hand-maintained allow-list drifting from this set is exactly #345 — it said
# `{"scene", "lore"}` while the index had grown six more families, so every
# other kind kept its dangling references forever.
REFERENCE_BEARING_KINDS = frozenset({family.kind for family in NODE_FAMILIES} | {"project"})


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
    def _build_index_manifest(self, layers: list[IndexLayer]) -> Manifest:
        """Fingerprint every file an index build over these layers reads.

        Takes the already-collected sequence rather than re-walking: the caller
        needs the layers anyway, and a second walk re-reads `project.yaml` and
        re-runs the ancestor probe for nothing (~1.7 ms of a ~7 ms warm call).
        This is `LayerCollector`'s sanctioned second shape — collect once, then
        iterate the collected sequence — not a bypass of the walk.

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
        for layer in layers:
            builder.visit_layer(layer)
        return builder.manifest

    def _load_index_snapshot(
        self, root: Path, *, layers: list[IndexLayer], manifest: Manifest
    ) -> LoadedSnapshot | None:
        """The snapshot, when it is still true. None means "build it".

        The failure paths are operationally distinct and logged differently.
        **Missing** is the normal first open and says nothing. **Corrupt** is
        evidence of a bug — something wrote a file we cannot read back — and is
        logged loudly. **Version-mismatched** is expected after an upgrade and
        is unremarkable.

        None of them deletes the file. An earlier version unlinked on a version
        mismatch, which reads as tidy and is a live hazard: that branch runs for
        every project on the first open after a format bump, and on Windows a
        single open handle — a scanner, a backup agent, a second instance — makes
        `unlink` raise `PermissionError` out of the *read* path, 500ing every
        index consumer. The rebuild overwrites the file moments later anyway, so
        the deletion bought nothing that the write does not already do.
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
                log.info("Node-index snapshot is from another build; rebuilding %s", path)
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
        """The funnel every index consumer goes through — now memoized (#392).

        A warm hit returns the in-memory index held by `node_index_gate` for this
        resolution scope with **no disk work at all**: no manifest sweep, no
        snapshot read. A miss builds it cold (`_resolve_index_cold`, below) and
        publishes it; the gate collapses a concurrent stampede to one build. The
        memo is dropped on every scope change (`CurrentScope.set` → `invalidate`)
        and maintained in place by the write funnel (`_apply_index_write`), so
        two consecutive consumers in one request build the index once and a
        prose-only save leaves it untouched.
        """
        # Canonicalised **once, here**, so the gate key, the snapshot's location,
        # its `root` key and the manifest's keys are all in the same normal form
        # as the layer folders the walk yields (`layers.py` resolves too), and so
        # the write funnel's `path.resolve()` compares equal to a stored entry's
        # path. Normalising at each comparison instead would be a second place
        # that decides a path's normal form — the shape of #356.
        root = (root or self._require_project()).resolve()
        return node_index_gate.resolve(root, lambda: self._resolve_index_cold(root))

    def _resolve_index_cold(self, root: Path) -> ResolvedIndex:
        """Build the index for `root` from disk — the gate's miss path.

        Walks the layer chain once, producing both the id→entry map and the
        reference edges (#305). Edge extraction is schema-driven, so the merged
        schema is read up front and threaded into the collectors — the front
        matter each file yields is parsed exactly once, for both purposes. Serves
        a fresh snapshot as-is, patches a stale one in place (#307), or rebuilds.

        **A schema that will not load must not make the index unbuildable.**
        Reading the schema is new work on this path: before #305 the index never
        touched it, so a typo in any layer's `metadata.schema.yaml` — including
        an *ancestor's*, which no one editing this book would think to look at —
        would otherwise take down every index consumer, from `list_lore_entries`
        to `_path_for_node_id` on each save. The failure degrades to "no edges"
        plus an `index.errors` row. Callers that want the schema still fail
        loudly on their own read; this one does not fail on their behalf.

        Returns the built index **with** the layers and manifest it was built
        against, so the write funnel can patch and re-fingerprint without
        re-walking or re-globbing.
        """
        # `root` is already resolved by the caller (`_build_node_index`), the one
        # place canonicalisation happens.
        layers = self.collect_layers(root, include_machine=True)
        # Fingerprinted **before** the build, not after. A file written while
        # the build runs is then either missed by both (consistent) or indexed
        # but unrecorded — which reads as an addition next time and rebuilds.
        # Stamping afterwards inverts that: the manifest would vouch for content
        # the index never saw, and the snapshot would be silently short a node.
        manifest = self._build_index_manifest(layers)
        loaded = self._load_index_snapshot(root, layers=layers, manifest=manifest)
        if loaded is not None and loaded.is_fresh:
            # The snapshot carries the edges but not the schema they were drawn
            # from; the memo stashes it (#392) so the change-gate reuses it
            # rather than re-reading on every save. This one read rides the warm
            # open, not the hot save path.
            return ResolvedIndex(root, loaded.index, tuple(layers), manifest, self._read_schema_or_none(root))
        index = NodeIndex()
        try:
            # `root`, not the singleton. Edge extraction is schema-driven, so
            # indexing one project's files against another's schema yields an
            # index with the wrong edges — and it is then written to *this*
            # project's snapshot with *this* project's manifest, so it validates
            # as fresh forever after. Every explicit-root caller had this latent
            # mismatch (#381); the purge only made it reachable under a race.
            schema: MetadataSchema | None = self.read_metadata_schema(root)
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
        # A stale snapshot is a **work list**, not a write-off (#307): re-parse
        # the handful of paths that moved and patch in place. It declines
        # (`PatchNotApplicable`) whenever the diff reaches something it does not
        # model — a schema edit, which fans out across the chain, or a path no
        # layer owns — and then this falls through to the full walk below.
        #
        # A failed schema read is not patchable either: the patch would extract
        # edges against `None` and quietly drop the references of every file it
        # touched, while leaving every other node's intact. That is a corrupt
        # index rather than a degraded one.
        if loaded is not None and schema is not None:
            try:
                patched = self._patch_node_index(
                    loaded.index, changed=loaded.changed, layers=layers, root=root, schema=schema
                )
            except PatchNotApplicable as exc:
                log.debug("Rebuilding the node index for %s instead of patching: %s", root, exc)
            else:
                self._write_index_snapshot(root, patched, layers=layers, manifest=manifest)
                return ResolvedIndex(root, patched, tuple(layers), manifest, schema)
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
        return ResolvedIndex(root, index, tuple(layers), manifest, schema)

    def _read_schema_or_none(self, root: Path) -> MetadataSchema | None:
        """The merged schema, or None when it will not load — the value the memo
        stashes on the snapshot-serve path (#392). Mirrors the cold build's
        posture (an unreadable schema costs edges, not correctness) but without
        the `index.errors` row, since the served snapshot already carries its
        own diagnostics."""
        try:
            return self.read_metadata_schema(root)
        except (ProjectServiceError, ValueError, OSError):
            return None

    # ---- write funnel: the change-gate (#392) -------------------------------
    #
    # Every in-app mutation of an indexed node file routes through one of these,
    # so the memo is maintained by construction rather than by every write path
    # remembering to notify it. The node-write primitives call them
    # (`_write_scene_file`, `_write_lore_entry_file`, `_write_node_entry_file`,
    # the project-node write), as do the one delete helper (`_delete_node_file`)
    # and the rename (`_maybe_rename_node_file`). A guard test forbids a bare
    # `.unlink(`/hand-rolled node write under `services/project/`, so the funnel
    # cannot be bypassed unnoticed.

    def _apply_index_write(self, paths: tuple[Path, ...], *, structural: bool) -> None:
        """Maintain the memo after writing/deleting/renaming node file(s).

        `structural=False` (a plain save) runs the change-gate: re-derive the one
        file's index signature and compare it to the held entry — a prose-only
        save changes nothing the index holds (id, kind, entry_type, title, path,
        or a reference field's value), so the memo is left untouched and no
        snapshot is written. `structural=True` (a delete or rename) always
        patches, because the path set itself changed.

        Called for **every** write via `_maintain_index_after_write`, so a path
        that is not an index input (a config file, the snapshot, a file outside
        the chain) is a no-op — the mutate below leaves the memo untouched. Also
        a no-op when no project is open or no index is held for this scope: the
        next `_build_node_index` builds cold and sees the write through the
        manifest sweep, so nothing is lost.
        """
        if self.root_path is None:
            return
        root = self.root_path.resolve()
        resolved = tuple(path.resolve() for path in paths)
        node_index_gate.apply(
            root,
            lambda current: self._mutate_index_for_write(current, resolved, structural),
            self._flush_resolved_index,
        )

    def _flush_resolved_index(self, resolved: ResolvedIndex) -> None:
        """Write the deferred snapshot for a patched memo (#476).

        The gate holds this as a thunk and fires it at a boundary (next read,
        scope change, shutdown). Everything the write needs rides on the
        `ResolvedIndex`, so it is self-contained — the gate can flush without a
        live `ProjectService`, and the write is against the exact index that was
        published, never a later one."""
        self._write_index_snapshot(
            resolved.root, resolved.index, layers=list(resolved.layers), manifest=resolved.manifest
        )

    def _mutate_index_for_write(
        self, current: ResolvedIndex, paths: tuple[Path, ...], structural: bool
    ) -> ResolvedIndex | None:
        """The gate callback: patch `current` for `paths`, or return None (no-op).

        Runs under the gate lock. On `PatchNotApplicable` — the diff reaches
        something the patch does not model (a diagnostic it cannot retract, a
        fan-out file) — it rebuilds cold and republishes, so the memo is never
        left describing a pre-write state.
        """
        layers = list(current.layers)
        # Keep only paths this index actually holds. `_patch_unit` places a node
        # file against the walk's own folder rules and raises for anything else,
        # so an unplaceable path — a config file, the snapshot, a write outside
        # the chain — drops out here and the memo is left untouched.
        placeable = []
        for path in paths:
            try:
                self._patch_unit(path, layers)
            except PatchNotApplicable:
                continue
            placeable.append(path)
        if not placeable:
            return None
        # Reuse the schema the memo was built with (#392) rather than re-reading
        # the uncached layer-chain schema the save already read moments ago. It
        # cannot be stale relative to `current.index`: a schema-file write fans
        # out and invalidates the whole memo, so a held schema and its index
        # always agree.
        schema: MetadataSchema | None = current.schema
        if schema is None:
            # The memo was built without a loadable schema (a degraded,
            # edge-less index). Without it, neither the signature comparison nor
            # the patch can compute a written file's edges — so a reference
            # change would be silently dropped. Rebuild cold instead, which
            # re-reads the schema and re-derives the state, exactly as this path
            # did before the schema was memoised.
            return self._resolve_index_cold(current.root)
        if self._write_leaves_index_unchanged(current, placeable, structural, layers, schema):
            return None  # nothing the index holds moved — leave the memo untouched.
        new_index = self._clone_node_index(current.index)
        changed = tuple(str(path) for path in placeable)
        try:
            self._patch_node_index(
                new_index, changed=changed, layers=layers, root=current.root, schema=schema
            )
        except PatchNotApplicable as exc:
            log.debug("Rebuilding the node index for %s instead of patching a write: %s", current.root, exc)
            return self._resolve_index_cold(current.root)
        manifest = dict(current.manifest)
        for path in placeable:
            fingerprint = fingerprint_for(path)
            if fingerprint is None:
                # A deleted node file is *absent* from a freshly globbed
                # manifest, so drop the key rather than storing None — otherwise
                # the next cold open's diff would flag it forever.
                manifest.pop(str(path), None)
            else:
                manifest[str(path)] = fingerprint
        # The snapshot write is **deferred** (#476): the gate registers a pending
        # flush against this `ResolvedIndex` and fires it at the next boundary, so
        # a burst of structural writes coalesces to one snapshot serialization
        # instead of one per file. Carry the schema forward (#392): a patched memo
        # must keep the schema its predecessor held, or the next save's change-gate
        # would see None and rebuild — or worse, silently drop an edge change it
        # could not compute.
        return ResolvedIndex(current.root, new_index, current.layers, manifest, schema)

    def _write_leaves_index_unchanged(
        self,
        current: ResolvedIndex,
        placeable: list[Path],
        structural: bool,
        layers: list[IndexLayer],
        schema: MetadataSchema,
    ) -> bool:
        """Whether the write changes nothing the index holds, so the memo can be
        left untouched — no clone, no patch, no snapshot flush.

        Two no-op shapes, one per gesture:

        - a plain single-file save (`#392`): the file's index signature (id,
          kind, entry_type, title, edges) is unmoved — a prose-only edit;
        - a **structural** write (`#476`): it skips the signature comparison (a
          delete moves the path set), but is still a no-op when *every* path was
          absent from the index **and** is gone from disk now — a delete of a
          file that was never indexed (already gone, or an unindexed note). A
          path that had an entry (a real delete) or exists now (a rename's new
          name, a restore) fails the test and takes the patch path.
        """
        if structural:
            for path in placeable:
                was_indexed = self._index_signature_from_memo(current.index, path) is not None
                if was_indexed or path.exists():
                    return False
            return True
        if len(placeable) == 1:
            before = self._index_signature_from_memo(current.index, placeable[0])
            after = self._index_signature_from_disk(placeable[0], layers, schema)
            return before is not None and before == after
        return False

    def _index_signature_from_memo(
        self, index: NodeIndex, path: Path
    ) -> tuple[str, str, str, str, tuple[ReferenceEdge, ...]] | None:
        """What the held index records for the file at `path`: its identity
        fields plus its edges. None when no entry there — a brand-new file, which
        is a change, so the caller must patch."""
        for entries in index.candidates.values():
            for entry in entries:
                if entry.path == path:
                    edges = tuple(index.edges_by_layer_src.get((entry.source_layer_id, entry.id), ()))
                    return (entry.id, entry.kind, entry.entry_type, entry.title, edges)
        return None

    _SIGNATURE_STRUCTURAL = object()

    def _index_signature_from_disk(
        self, path: Path, layers: list[IndexLayer], schema: MetadataSchema | None
    ) -> object:
        """The same signature, re-derived from the file as it now sits on disk.

        Returns a distinct sentinel — never equal to any memo signature — when
        the file is malformed, unplaceable, or otherwise uncertain, so the caller
        falls through to the patch/rebuild path rather than trusting a partial
        read.
        """
        try:
            unit = self._patch_unit(path, layers)
        except PatchNotApplicable:
            return self._SIGNATURE_STRUCTURAL
        probe = NodeIndex()
        if unit.kind == "family":
            if not path.exists():
                return None
            assert unit.family is not None
            self._collect_entry_file(
                path, layer=unit.layer, family=unit.family, index=probe,
                duplicate_relative_to=unit.layer.folder, schema=schema,
            )
        elif unit.kind == "project_node":
            self._collect_project_node_entry(layer=unit.layer, index=probe, schema=schema)
        elif unit.kind == "chat":
            # One file, not the whole chats/ folder (#392) — a chat's signature
            # is (id, title), readable from the file that was just written.
            self._collect_chat_file(path, layer=unit.layer, index=probe)
        else:  # pragma: no cover - _patch_unit yields no other kind
            return self._SIGNATURE_STRUCTURAL
        if probe.errors or probe.has_unparsed_nodes:
            # A malformed write. Force the structural path so the diagnostic is
            # collected by a rebuild rather than silently dropped here.
            return self._SIGNATURE_STRUCTURAL
        return self._index_signature_from_memo(probe, path)

    def _clone_node_index(self, index: NodeIndex) -> NodeIndex:
        """A patchable copy of a published index.

        Entries and edges are frozen, so only the container lists need copying:
        the patch mutates `candidates` / `edges_by_layer_src` in place and
        `resolve()`s at the end. Leaving the original untouched is what lets a
        concurrent reader keep serving it (model B)."""
        clone = NodeIndex()
        clone.candidates = {node_id: list(entries) for node_id, entries in index.candidates.items()}
        clone.edges_by_layer_src = {key: list(edges) for key, edges in index.edges_by_layer_src.items()}
        clone.warnings = list(index.warnings)
        clone.errors = list(index.errors)
        clone.degraded = index.degraded
        clone.has_unparsed_nodes = index.has_unparsed_nodes
        clone._shadow_warnings = list(index._shadow_warnings)
        return clone

    def _delete_node_file(self, path: Path) -> None:
        """Unlink an indexed node file and un-shadow the memo (#392).

        The single delete primitive the node slices call instead of a bare
        `path.unlink()`, so a delete maintains the memo the way a save does. A
        delete is always structural: removing a book-level node that shadowed an
        ancestor's must make the ancestor visible again (#307), which the patch
        does by re-resolving a shorter candidate list.
        """
        if path.exists():
            path.unlink()
        # Notify even when the file was already gone: the caller treated it as a
        # delete, and a memo entry may still describe it.
        self._apply_index_write((path,), structural=True)

    def _delete_node_files(self, paths: tuple[Path, ...]) -> None:
        """Batch form of `_delete_node_file` for a subtree delete (#476).

        A chapter delete unlinks every scene under it. Routing each through
        `_delete_node_file` would maintain the index once per file — and because
        the surrounding loop resolves the index to map each id to its path, the
        deferred flush fires between deletes, so a 20-scene chapter wrote ~20
        snapshots. Collecting the paths first and maintaining the index **once**
        collapses that to a single deferred flush: one clone, one patch over all
        paths, one write at the next boundary. `_patch_node_index` already takes
        a tuple of paths, so the batch is free on the maintenance side.
        """
        for path in paths:
            if path.exists():
                path.unlink()
        if paths:
            self._apply_index_write(paths, structural=True)

    def _collect_chat_entries(self, *, layer: IndexLayer, index: NodeIndex) -> None:
        """Walk <project>/chats/*.yaml and add an index entry per session.

        Storage stays YAML — this is just a discovery layer so chats are
        addressable from the unified node index alongside other kinds.
        """
        chats_dir = layer.folder / "chats"
        if not chats_dir.exists():
            return
        for path in sorted(chats_dir.glob("*.yaml")):
            self._collect_chat_file(path, layer=layer, index=index)

    def _collect_chat_file(self, path: Path, *, layer: IndexLayer, index: NodeIndex) -> None:
        """Collect exactly one chat session file into `index`.

        Split out of the folder walk (#392) so the change-gate can re-derive a
        single chat's signature by reading *that* file, rather than re-parsing
        every chat session — each of which carries its whole message journal —
        to answer whether one chat's title moved.
        """
        try:
            data = self._read_yaml(path)
        except Exception as exc:
            index.errors.append(f"Failed to read chat session {path.name}: {exc}")
            index.has_unparsed_nodes = True
            # Same rule as the schema read: a chat we could not open is
            # missing from the index entirely, and its file is unchanged, so
            # a snapshot would keep it missing across every later open.
            index.degraded = index.degraded or isinstance(exc, OSError)
            return
        if not isinstance(data, dict):
            return
        raw_id = data.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            return
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
            return
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
            # The file is here; its identity is not. See `has_unparsed_nodes`.
            index.has_unparsed_nodes = True
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
        for path in sorted((layer.folder / family.folder_name).glob("*.md")):
            self._collect_entry_file(
                path,
                layer=layer,
                family=family,
                index=index,
                duplicate_relative_to=duplicate_relative_to,
                schema=schema,
            )

    def _collect_entry_file(
        self,
        path: Path,
        *,
        layer: IndexLayer,
        family: NodeFamily,
        index: NodeIndex,
        duplicate_relative_to: Path,
        schema: MetadataSchema | None = None,
    ) -> None:
        """Collect exactly one node file into `index`.

        Split out of the folder glob so #307 can re-parse **the file that
        changed** rather than its whole folder — the difference between ~4x and
        ~30x on a folder holding a few hundred entries. The loop above is now
        this called per path, so there is one definition of what collecting a
        node file means and no chance of the incremental path drifting from the
        cold one.
        """
        folder = layer.folder
        try:
            front_matter = self._read_front_matter_only(path, strict=True)
        except ProjectServiceError as exc:
            index.errors.append(exc.message)
            # A file on disk whose id we could not read — so `by_id` stops
            # being a complete answer to "does this id exist" (#379).
            index.has_unparsed_nodes = True
            return

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
            return
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
