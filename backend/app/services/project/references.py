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

# The reserved `field_id` a `{% include %}` reference edge carries (ADR-0061 §5).
# The include is a template-composition relationship, not an `entity_ref`, so the
# entity-ref surfaces exclude it — the entity-ref backlinks skip it
# (`schema.fields.get(...)` is None) and `reference_graph` filters it out; it
# reaches consumers only as its own edge kind, which the dependency alert (S3)
# queries from the reverse map. The leading `@` is load-bearing: a user field id
# is validated against `[A-Za-z][A-Za-z0-9_]*` (see `schema.py`), so this value
# can never collide with a real field — a field a user *did* name "include" would
# otherwise be silently dropped from the reference view by that same filter.
INCLUDE_FIELD_ID = "@include"

# The Node-shaped kinds the index walks, once per layer of the chain.
NODE_FAMILIES = [
    NodeFamily("manuscript", "scenes", "manuscript:scene"),
    # Research notes walk `research/notes/`. Treated like lore (cross-layer)
    # rather than scenes (book-scoped) — universe- or series-level research
    # notes are a natural use case.
    NodeFamily("research", "research/notes", "research:note"),
    NodeFamily("lore", "lore", "lore:note"),
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
    # Plot planning (ADR-0048): plotlines (and, from S4b, templates + their
    # instances) as flat Node files under `plot/`. Layered — NOT book-scoped
    # like scenes — because S4b ships the diagnostic templates through the
    # ADR-0049 Library, an ancestor layer; book-scoping would exclude them.
    # The plot *board* is a separate per-project singleton (`plot-board.md`),
    # deliberately NOT in this family so an ancestor's board never leaks into
    # the resolved set (one board per open book, ADR-0048 §3).
    NodeFamily("plot", "plot", "plot:plotline"),
    # Chats (ADR-0051 S1): body-less Node files under `chats/`, each carrying
    # the ChatSession payload (messages/journal/inputs/…) in front matter. Root-
    # scoped like scenes (see `_families_for_layer`) — a chat belongs to the open
    # project, an ancestor's chats never resolve into it. Reference-bearing from
    # here on (the `subject` entity_ref arrives in S2); today the type declares
    # only `color`, so it contributes no edges.
    NodeFamily("chat", "chats", "chat:chat_session"),
]

# The one family the out-of-tree machine layer contributes. Looked up rather
# than re-spelled as a literal — a second copy of the triple would drift.
MACHINE_LAYER_FAMILIES = [family for family in NODE_FAMILIES if family.kind == "assistant"]

# The families the built-in Library ships (ADR-0049). Prompts were the first
# tenant; plot templates are the second (ADR-0048 S4b) — proof the model is
# kind-agnostic, exactly as the design intended: a later kind joins by adding its
# family here and a folder in `builtin_library/`, no new mechanism. Deliberately
# a subset, not "everything a project layer carries": the Library is not a
# project, and scoping it to what actually ships keeps the walk from globbing
# folders that will never exist (the vertical-slice discipline in §4). The
# Library's `plot/` folder ships only `plot:template` nodes, so no plotline or
# board resolves from this layer.
LIBRARY_LAYER_FAMILIES = [family for family in NODE_FAMILIES if family.kind in ("prompt", "plot")]

# Every kind whose files the index extracts reference edges from: the node
# families above, plus the per-layer project node (#334), which lives at the
# layer root rather than in a kind folder and so is collected separately.
# Chats joined the families in ADR-0051 S1 — they are now ordinary Node files,
# so they are reference-bearing like every other kind (contributing no edges
# until the `subject` entity_ref lands in S2).
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
        if not layer.is_machine and not layer.is_library:
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
        if not layer.is_machine and not layer.is_library:
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
            # `durable=False`: the snapshot is rebuildable cache (#476/#480), so
            # it skips the per-write fsync every user file pays. A crash that
            # loses it costs the next open its speed and nothing else.
            self._atomic_write(
                snapshot_path(root),
                snapshot_serialize(index, root=root, layers=layers, manifest=manifest),
                durable=False,
            )
        except OSError as exc:
            log.warning("Could not write the node-index snapshot for %s: %s", root, exc)

    def _build_node_index(self, root: Path | None = None) -> NodeIndex:
        """The funnel every index consumer goes through — now memoized (#392).

        A warm hit returns the in-memory index held by `node_index_gate` for this
        resolution scope with **no disk work at all**: no manifest sweep, no
        snapshot read. A miss builds it cold (`_resolve_index_cold`, below) and
        publishes it; the gate collapses a concurrent stampede to one build. The
        memo is dropped on every project open (`/api/project/open` → `invalidate`)
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
        # place canonicalisation happens. `include_library` and the walk below
        # MUST stay in lock-step: this list feeds the manifest and snapshot, and
        # the walk builds the index — if one carries the Library layer and the
        # other does not, the manifest either misses the Library's files (stale
        # snapshot) or vouches for files the index never read.
        layers = self.collect_layers(root, include_machine=True, include_library=True)
        # Fingerprinted **before** the build, not after. A file written while
        # the build runs is then either missed by both (consistent) or indexed
        # but unrecorded — which reads as an addition next time and rebuilds.
        # Stamping afterwards inverts that: the manifest would vouch for content
        # the index never saw, and the snapshot would be silently short a node.
        manifest = self._build_index_manifest(layers)
        # A chain carrying layer overrides (#314) is always built by full cold
        # walk: the snapshot fast paths and the incremental patch model raw edges
        # per file, and an override folds *effective* edges across the chain —
        # the same class of invalidation ADR-0040 Amendment 1 (#390) exists to
        # model, deliberately not yet built incrementally. So overrides skip the
        # snapshot read/patch/write entirely and refold on every cold build. Flat
        # projects (no overrides — the common case) keep every fast path
        # unchanged. The in-memory memo (#392) still caches the result, so this is
        # one full build per project open, not per read.
        has_overrides = self._chain_has_overrides(layers)
        loaded = None if has_overrides else self._load_index_snapshot(root, layers=layers, manifest=manifest)
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
            # Chain-level, not a node file: the merged schema failed to load, so
            # this attributes the error to the open project's own schema file.
            # It never coexists with a live patch — a failed read leaves
            # `schema is None`, which skips the patch below entirely — and a
            # fixed schema moves `metadata.schema.yaml`, which fans out to a full
            # rebuild, so the diagnostic is re-derived rather than stranded.
            root_layer = next(layer for layer in layers if layer.is_root)
            index.add_diagnostic(
                layer_id=root_layer.id,
                path=root / SCHEMA_FILENAME,
                message=f"Invalid metadata schema; no reference edges were indexed: {exc}",
                is_error=True,
            )
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
        # One walk, machine and Library layers included (#329, ADR-0049). The
        # Library floor comes first (app-owned shipped nodes, read-only), then
        # the machine layer (assistants only, out-of-tree), then the project
        # layers outermost-ancestor first — so a descendant entry overwrites an
        # ancestor's, and any real layer overwrites a shipped Library node, on
        # collision.
        self.visit_layers(
            _NodeIndexBuilder(self, index=index, root=root, schema=schema),
            root,
            include_machine=True,
            include_library=True,
        )
        if has_overrides:
            # Collect the deltas (a parallel pass, not nodes), then fold effective
            # edges onto each overridden target's winner *before* `resolve()`
            # derives the winner edge views — so backlinks / References / Nest see
            # the folded graph with no scope parameter (#314 / ADR-0039).
            self._collect_all_overrides(index, layers)
            self._fold_override_edges(index, root, schema)
        # Include edges (ADR-0061 §5) are extracted here, after the whole chain
        # is collected, because resolving an `{% include %}` name → snippet id
        # needs the complete snippet set — unlike the field edges, which the
        # per-file walk extracts inline. Before `resolve()`, so it projects these
        # into the winner / reverse maps alongside the field edges.
        self._extract_include_edges(index, schema)
        # One post-walk pass: order the candidate lists innermost-first, derive
        # `by_id` / `edges_by_src` from the winners, emit the shadow warnings and
        # build the reverse edge map. Nothing before this point resolves a
        # shadow — that is what stops the walk destroying an ancestor.
        index.resolve()
        if not has_overrides:
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
        # A node write in an override-bearing chain (#314) rebuilds cold: the
        # incremental patch would recompute the written node's edges from its own
        # file, dropping the override edge-fold that only the cold path applies.
        # Overrides are sparse, so this only affects chains that actually use
        # them; flat projects never enter this branch.
        if current.index.overrides_by_target:
            return self._resolve_index_cold(current.root)
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
        if unit.family is not None and unit.family.kind == "prompt":
            # A prompt's include edges (ADR-0061 §5) are extracted by a
            # whole-index finalize, not by the per-file `_collect_entry_file` this
            # probe runs — so the disk signature would omit them and a body edit
            # that adds an `{% include %}` (with no field-edge change) would read
            # as unchanged and skip the rebuild. Force every prompt write onto the
            # patch path via the structural sentinel; `_patch_node_index` then
            # declines it to a cold rebuild that reruns the finalize.
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
        # Carried for completeness — a patch of an override-bearing chain rebuilds
        # cold (`_mutate_index_for_write`) rather than reaching here, but a clone
        # must never silently drop the fold input if that guard ever moves.
        clone.overrides_by_target = {
            target: list(records) for target, records in index.overrides_by_target.items()
        }
        # Copied like the other droppable structures: the patch gate reads the
        # clone's diagnostics before any drop, and `_drop_diagnostics_under`
        # mutates this map in place (#382). `warnings` / `errors` are derived
        # views over it, so there is nothing else to carry.
        clone.diagnostics_by_source = {
            key: list(diags) for key, diags in index.diagnostics_by_source.items()
        }
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
        # The single-file case of the batch below — one unlink, one structural
        # notify. Delegating keeps the unlink-then-notify in one place; a single
        # placeable path still applies even when the file was already gone, so
        # the "notify even when absent" behaviour is preserved.
        self._delete_node_files((path,))

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
            index.add_diagnostic(layer_id=layer.id, path=path, message=exc.message, is_error=True)
            # The file is here; its identity is not. See `has_unparsed_nodes`.
            index.has_unparsed_nodes = True
            return
        duplicate = index.entry_for_layer(node_id, layer.id)
        if duplicate is not None:
            # The same guard every other collector applies. Without it the
            # `(layer, id)` edge key stops being a key, and two files at one
            # layer fight over one edge list.
            #
            # `blocks_patch`: only the first claimant is in `candidates`, so a
            # per-file patch that dropped the winner would leave nothing to
            # promote — retracting this needs a rebuild (#382).
            index.add_diagnostic(
                layer_id=layer.id,
                path=path,
                message=(
                    f"Duplicate front matter id {node_id} in "
                    f"{self._safe_relative(duplicate.path, layer.folder)} and "
                    f"{self._safe_relative(path, layer.folder)}."
                ),
                is_error=True,
                blocks_patch=True,
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
            index.add_diagnostic(
                layer_id=layer.id,
                path=path,
                message=f"{self._safe_relative(path, layer.folder)}: {exc.message} Its references were not indexed.",
                is_error=True,
            )
            edges = []
        if edges:
            index.edges_by_layer_src[(layer.id, node_id)] = edges

    def _families_for_layer(self, layer: IndexLayer) -> list[NodeFamily]:
        """Which node families this layer contributes — the per-layer logic the
        index walk used to inline (#329).

        The machine layer is out-of-tree: assistants only. The Library is
        out-of-tree too and ships only its tenant kinds (prompts, ADR-0049).
        Scenes stay book-scoped, so they come from the open project alone.
        """
        if layer.is_machine:
            return MACHINE_LAYER_FAMILIES
        if layer.is_library:
            return LIBRARY_LAYER_FAMILIES
        return [family for family in NODE_FAMILIES if family.kind not in ("manuscript", "chat") or layer.is_root]

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
            index.add_diagnostic(layer_id=layer.id, path=path, message=exc.message, is_error=True)
            # A file on disk whose id we could not read — so `by_id` stops
            # being a complete answer to "does this id exist" (#379).
            index.has_unparsed_nodes = True
            return
        except OSError as exc:
            # We could not *read* the file at all — a cloud-sync placeholder, an
            # AV lock, a concurrent checkout — as opposed to malformed content.
            # Degrade so this build is not cached: the file is unchanged, so a
            # cached snapshot missing this node would match the manifest and be
            # served on every later open (ADR-0051 S1 generalised this from the
            # chat collector; same rule as the schema read, `_resolve_index`).
            index.add_diagnostic(
                layer_id=layer.id,
                path=path,
                message=f"Failed to read {family.kind} file {path.name}: {exc}",
                is_error=True,
            )
            index.has_unparsed_nodes = True
            index.degraded = True
            return

        node_id = self._front_matter_id(path, front_matter)
        if node_id is None:
            # The extractor collapses "no id key" and "id present but not text"
            # into one `None`; the diagnostics keep them apart — a missing id is
            # a legacy file we accept (warning), a malformed one is an error.
            node_id = path.stem
            if front_matter.get("id") is None:
                index.add_diagnostic(
                    layer_id=layer.id,
                    path=path,
                    message=(
                        f"{family.kind.title()} file {self._safe_relative(path, folder)} is missing "
                        f"front matter id; using filename stem as legacy id."
                    ),
                    is_error=False,
                )
            else:
                index.add_diagnostic(
                    layer_id=layer.id,
                    path=path,
                    message=(
                        f"{family.kind.title()} file {self._safe_relative(path, folder)} has invalid "
                        f"front matter id; it must be text."
                    ),
                    is_error=True,
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
            is_library=layer.is_library,
            forked_from_layer_id=self._forked_from_layer_id(front_matter.get("forked_from")),
        )
        duplicate = index.entry_for_layer(node_id, layer.id)
        if duplicate is not None:
            # Two files claiming one id *at the same layer* — an error, not a
            # shadow. Shadowing is a relationship between layers; within one
            # layer there is no order to resolve by.
            #
            # `blocks_patch`: this file is rejected and never enters
            # `candidates`, so a per-file patch that dropped the winner would
            # leave nothing to promote where a cold build promotes this sibling.
            # Retracting it needs a rebuild (#382).
            index.add_diagnostic(
                layer_id=layer.id,
                path=path,
                message=(
                    f"Duplicate front matter id {node_id} in "
                    f"{self._safe_relative(duplicate.path, duplicate_relative_to)} and "
                    f"{self._safe_relative(path, duplicate_relative_to)}."
                ),
                is_error=True,
                blocks_patch=True,
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
            index.add_diagnostic(
                layer_id=layer.id,
                path=path,
                message=(
                    f"{self._safe_relative(path, duplicate_relative_to)}: {exc.message} "
                    f"Its references were not indexed."
                ),
                is_error=True,
            )
            edges = []
        if edges:
            index.edges_by_layer_src[(layer.id, node_id)] = edges

    def _forked_from_layer_id(self, raw_forked_from: object) -> str:
        """Resolve a fork's `forked_from` front-matter value — a path relative to
        the base folder — to the layer id it names (#313 / ADR-0039).

        Stored on disk as a relative path rather than a layer id because layer
        ids are `sha256(resolved absolute path)`, so machine- and location-
        dependent (`_layer_id_for_folder`); a relative path survives a moved or
        renamed shelf. It is reversed to an id here, at collection, so
        `NodeIndex.resolve()` can compare plain ids and never touch the
        filesystem. "" for anything that did not fork.
        """
        if not isinstance(raw_forked_from, str) or not raw_forked_from.strip():
            return ""
        base = self._metadata_schema_base_folder(self.root_path)
        if base is None:
            return ""
        return self._metadata_schema_layer_id(base / raw_forked_from.strip())

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
            "manuscript": "scenes",
            "lore": "lore",
            "prompt": "prompts",
            "research": "research/notes",
            "mutation_set": "mutation-sets",
            "view": "views",
            "plot": "plot",
            "chat": "chats",
        }
        label_by_kind = {
            "manuscript": "Scene",
            "lore": "Lore Entry",
            "prompt": "Prompt",
            "research": "Research Note",
            "mutation_set": "Mutation set",
            "view": "View",
            "plot": "Plotline",
            "chat": "Chat",
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

    def _extract_include_edges(self, index: NodeIndex, schema: MetadataSchema | None) -> None:
        """Record each prompt's literal `{% include %}` tags as reference edges
        (ADR-0061 §5), so *"what includes this snippet?"* is a reverse-index
        lookup the dependency alert rides on.

        A **whole-index finalize**, not a per-file extraction like the
        `entity_ref` edges above: an include names a snippet by id-or-title, and
        resolving that name needs the *complete* snippet set — which the per-file
        walk does not have (a prompt may include a snippet the walk has not
        reached yet). So this runs once, after the walk, before `resolve()`,
        over the winner of each id — the same set the render loader and the S1
        resolver match against (`match_snippet_name`), so an edge targets the
        snippet that actually renders and gather/render/dependency cannot drift.

        The resolved edges are appended to `edges_by_layer_src` like any other,
        so `resolve()` projects them into the forward/reverse maps and the
        snapshot serializes them with no include-specific persistence code. A
        prompt edit declines the incremental patch (`_patch_node_index`) and
        rebuilds, so this reruns whenever an include could have changed.

        Skipped when the schema failed to load: without it a snippet's
        `entry_type` cannot be recognised, matching the "no edges" degradation
        the cold build already applies to an unreadable schema.
        """
        if schema is None:
            return
        from app.services.ai.effective_inputs import literal_include_names
        from app.services.ai.snippet_loader import match_snippet_name
        from app.services.ai.templates import create_environment

        # Winners only, computed the way `resolve()` will: `candidates` is
        # innermost-first after the walk (`NodeIndex.add` front-inserts in walk
        # order), so the first entry is the winner. `resolve()` has not run yet.
        prompts = [entries[0] for entries in index.candidates.values() if entries[0].kind == "prompt"]
        if not prompts:
            return
        snippets = [
            entry
            for entry in prompts
            if "prompt:snippet" in self.entry_type_ancestry(entry.entry_type, schema=schema)
        ]
        if not snippets:
            return  # nothing an include could resolve to
        env = create_environment()
        for prompt in prompts:
            try:
                _, body = self._read_markdown_with_front_matter(prompt.path)
            except (OSError, ProjectServiceError):
                # An unreadable body contributes no include edges — the render
                # path surfaces the real failure; the graph degrades quietly.
                continue
            targets: list[str] = []
            for name in literal_include_names(body, env):
                matched = match_snippet_name(
                    name, snippets, id_of=lambda entry: entry.id, title_of=lambda entry: entry.title
                )
                if matched is not None:
                    targets.append(matched.id)
            if not targets:
                continue
            # Dedup within the prompt — a snippet included twice is one edge —
            # matching `_edges_from_field`, and append so a prompt's own
            # `entity_ref` edges (if any) are kept alongside its include edges.
            index.edges_by_layer_src.setdefault((prompt.source_layer_id, prompt.id), []).extend(
                ReferenceEdge(src=prompt.id, dst=dst, field_id=INCLUDE_FIELD_ID)
                for dst in dict.fromkeys(targets)
            )

    def reference_graph(self) -> ReferenceGraphResponse:
        """Forward reference adjacency for the whole project (#184 Phase 2).

        A projection of the edges the index already carries — the ids each node
        references through any `entity_ref` / `entity_ref_list` field, flattened
        across fields and deduped in field-declaration order. The frontend
        inverts this into a reverse index the view evaluator's `references`
        computed field projects over. Only nodes that reference something appear
        as keys.

        `{% include %}` edges (ADR-0061 §5) are excluded: this is the entity-ref
        reference view, and an include is a template-composition edge with its own
        dependency surface (S3), not an `entity_ref` — the same reason the
        entity-ref backlinks skip it. A node whose *only* edges are includes is
        therefore absent, so the dict comprehension guards each key on a non-empty
        list rather than trusting `edges_by_src` to hold none."""
        node_index = self._build_node_index()
        refs = {
            src: deduped
            for src, edges in node_index.edges_by_src.items()
            if (deduped := list(dict.fromkeys(
                edge.dst for edge in edges if edge.field_id != INCLUDE_FIELD_ID
            )))
        }
        return ReferenceGraphResponse(refs=refs)

    def prompts_including_snippet(self, snippet_id: str) -> set[str]:
        """The ids of every prompt that transitively `{% include %}`s
        `snippet_id` (ADR-0061 §5) — the "N prompts" half of the dependency alert.

        A reverse-**transitive** closure over the `@include` edges the index
        already carries (S2b): a prompt that includes a snippet that includes
        `snippet_id` is affected too, because it renders `snippet_id`'s text and
        so depends on its fields. `snippet_id` itself is never in the result
        (a self- or cyclic include cannot make a node its own dependent); the
        `seen` guard also terminates any include cycle."""
        index = self._build_node_index()
        including: set[str] = set()
        frontier = [snippet_id]
        while frontier:
            current = frontier.pop()
            for edge in index.edges_by_dst.get(current, []):
                if edge.field_id != INCLUDE_FIELD_ID or edge.src in including:
                    continue
                including.add(edge.src)
                # Its own includers depend on `snippet_id` transitively too.
                frontier.append(edge.src)
        including.discard(snippet_id)
        return including

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
