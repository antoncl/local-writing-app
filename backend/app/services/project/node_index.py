"""The node-index value types.

`NodeIndex` / `NodeIndexEntry` describe the result of walking a project's
layered Node files into an id→entry map, plus the `ReferenceEdge`s extracted
from the same pass (#305 / ADR-0040). They live in their own module so
the per-kind mixin slices (assistants, …) that instantiate `NodeIndex` or
annotate against these types can import them without a circular import
back into `project_service.py`. `project_service.py` re-exports both names,
so existing references keep working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.project.overrides import LayerOverride


@dataclass(frozen=True)
class NodeIndexEntry:
    id: str
    kind: str
    entry_type: str
    path: Path
    title: str = ""
    source_layer_id: str = ""
    source_layer_label: str = ""
    # Whether the entry's source layer is the app-owned built-in Library (#674 /
    # ADR-0049 §5). Stamped from `IndexLayer.is_library` at collection time so
    # clone/hide and the read model branch on *is-this-the-app-Library* rather
    # than on the layer's display label — a writer whose ancestor project is
    # titled "Library" must not be mistaken for shipped material.
    is_library: bool = False
    # The layer id this entry was fork-to-here'd from (#313 / ADR-0039), resolved
    # from the front-matter `forked_from` relative path at collection time. When
    # it equals the id of the layer this entry shadows, `resolve()` treats the
    # shadow as deliberate and stays quiet; "" (an ordinary entry) keeps the
    # warning loud for an accidental collision.
    forked_from_layer_id: str = ""


@dataclass(frozen=True)
class IndexLayer:
    """One folder in the layer chain: where to read, the identity every entry
    collected there is stamped with, and the layer's place in the walk.

    Yielded by the single traversal in `layers.py` (#329). `rank` is explicit
    rather than positional so consumers stop re-deriving it — the assistant
    roster used to infer it from index insertion order, which an incremental
    index patch (#307) would silently reorder. Compare ranks; never index with
    them.

    `is_root` marks the open project itself (scenes and chats are collected
    only there). `is_machine` marks the out-of-tree machine config dir, which
    contributes assistants only and carries no `metadata.schema.yaml`.
    `is_library` marks the app-owned built-in Library — the read-only floor of
    shipped nodes beneath every project (ADR-0049). Like the machine layer it
    is out-of-tree and carries no project node or schema; unlike it, it
    contributes ordinary node families (prompts first) and is never a write
    target — a save routed at it is refused (`save_prompt_entry`).
    """

    folder: Path
    id: str
    label: str
    rank: int
    is_root: bool = False
    is_machine: bool = False
    is_library: bool = False


@dataclass(frozen=True)
class NodeFamily:
    """A kind and where its files live — the (kind, folder, default entry type)
    triple `_build_node_index` iterates once per layer."""

    kind: str
    folder_name: str
    default_entry_type: str


@dataclass(frozen=True, slots=True)
class NodeDiagnostic:
    """One collection diagnostic, carrying the provenance entries already have
    (#382).

    Diagnostics used to be free-form strings in flat `warnings` / `errors`
    lists, so nothing recorded *which file* produced one — and unlike every
    other index structure they could not be dropped when their file was
    re-collected. Keyed by `(source layer id, path)` in
    `NodeIndex.diagnostics_by_source`, a diagnostic is retracted by the same
    per-file drop that retracts a file's entries and edges (#307).

    `is_error` splits the two derived views (`errors` vs `warnings`).

    `blocks_patch` is set only for a diagnostic about a file the collector
    *rejected* — a same-layer duplicate id, a cross-kind chat collision — where
    only the first claimant entered `candidates`. Retracting such a diagnostic
    correctly means promoting the rival, which needs re-collecting a file the
    per-file drop never touches, so `_patch_node_index` still refuses these and
    rebuilds. Every other diagnostic is about a file that *was* indexed and is
    retracted by re-collecting that same file.
    """

    message: str
    is_error: bool
    blocks_patch: bool = False


@dataclass(frozen=True, slots=True)
class ReferenceEdge:
    """One `entity_ref` / `entity_ref_list` link, qualified by the field it came
    from.

    The field is part of the edge identity, not decoration: ADR-0039's
    reference-typed overrides must know *which* field an override re-points, and
    two fields on the same node may legitimately point at the same target.

    `slots=True` because these are the most numerous objects the index holds —
    8880 at Weber scale, 20230 at huge — and a per-instance `__dict__` is ~88 B
    of pure overhead on a 3-string record. Measured over the whole edge
    structure (forward + reverse) at Weber scale: **3.9 MB → 2.4 MB**.
    """

    src: str
    dst: str
    field_id: str


@dataclass
class NodeIndex:
    """The layer-qualified node index (#334).

    **Identity is layer-qualified**: `candidates` maps an id to every entry that
    claims it, innermost layer first. Before #334 the index kept one entry per
    id, so collecting a descendant's node *destroyed* the ancestor's — and there
    is no second copy anywhere, the file was parsed once. That made two things
    impossible rather than merely unimplemented: deleting a descendant node
    could not restore the ancestor it had been shadowing (#307), and ADR-0042's
    layer picker had nothing to show at any position but the innermost.

    `by_id` and `edges_by_src` are **derived winners views**, rebuilt by
    `resolve()` after the walk. They keep the shape every existing consumer
    reads (43 call sites across 15 files), so shadow resolution moved without
    those callers changing. They are outputs, never written directly during
    collection — writing one is how the old destruction happened.
    """

    # id → every entry claiming it, **innermost layer first** after `resolve()`.
    # During collection entries are appended in walk order (outermost first) and
    # the list is reversed once, at the end.
    candidates: dict[str, list[NodeIndexEntry]] = field(default_factory=dict)
    # Forward edges keyed by **(source layer id, source node id)**, in
    # field-declaration order. Layer-qualified for the same reason entries are:
    # a shadowed ancestor keeps its edges, so un-shadowing on delete restores a
    # node *with its references*, not a stripped one.
    edges_by_layer_src: dict[tuple[str, str], list[ReferenceEdge]] = field(default_factory=dict)
    # Layer overrides (#314 / ADR-0039), keyed by **target node id**. Collected
    # in a parallel pass, not as nodes: an override is a sparse delta, filtered
    # out of `candidates` / `by_id` / pickers / views by construction. The fold
    # reads these — values on read (`read_lore_entry`), edges here at build time
    # (`_fold_override_edges` rewrites the target's `edges_by_layer_src` entry
    # before `resolve()`), so backlinks / References / Nest need no scope param.
    overrides_by_target: dict[str, list[LayerOverride]] = field(default_factory=dict)
    # --- derived (see `resolve`) ---
    by_id: dict[str, NodeIndexEntry] = field(default_factory=dict)
    edges_by_src: dict[str, list[ReferenceEdge]] = field(default_factory=dict)
    # Reverse adjacency — the structure backlinks are served from. Populated by
    # `rebuild_reverse_edges` once the walk is complete.
    edges_by_dst: dict[str, list[ReferenceEdge]] = field(default_factory=dict)
    # Collection diagnostics, keyed by **(source layer id, path)** — the same
    # provenance entries and edges carry (#382). Before this the diagnostics
    # were flat `warnings` / `errors` string lists with no record of their
    # origin, so they were the one index structure a drop could not retract: fix
    # a malformed id and the warning survived, and the snapshot persisted it, so
    # the wrong output was monotonic. `warnings` / `errors` are now **derived
    # views** over this store plus the shadow warnings `resolve()` emits.
    diagnostics_by_source: dict[tuple[str, Path], list[NodeDiagnostic]] = field(default_factory=dict)
    # Set when the build degraded for a reason that is a property of the
    # *environment* rather than of the files — an unreadable schema, a chat
    # session that would not open. Such an index is correct to serve now and
    # wrong to persist (#306): the files it failed to read are unchanged, so
    # their fingerprints match on the next open and the crippled result would be
    # vouched for as fresh until something unrelated in the chain was edited.
    #
    # Content errors are deliberately *not* degradations. Malformed front matter
    # is deterministic — the same files produce the same index — and fixing it
    # moves that file's mtime, so caching it is both correct and self-healing.
    degraded: bool = False
    # Set when a node file was found but its identity could not be read —
    # malformed front matter, an unparseable chat session. The file is on disk
    # and may well claim an id, but the index cannot know which, so **`by_id` is
    # no longer a complete answer to "does this id exist"** (#379).
    #
    # Only destructive consumers need care. Reading a stale index shows one
    # entry less; `_purge_references_to` rewriting the user's files on the same
    # assumption destroys links to a node that is merely mistyped, and fixing
    # the typo does not bring them back. Unlike `degraded`, this **is**
    # persisted: it is a property of the files, not the environment, so a warm
    # load must inherit it or the guard evaporates on the second open.
    has_unparsed_nodes: bool = False
    # The shadow warnings the last `resolve()` contributed, so a re-resolve can
    # retract them instead of duplicating them.
    _shadow_warnings: list[str] = field(default_factory=list, repr=False)

    def add(self, entry: NodeIndexEntry) -> None:
        """Record one entry. Nothing is ever replaced — a descendant claiming an
        ancestor's id joins the candidate list instead of overwriting it.

        Inserted at the front, so the list is innermost-first *as it is built*
        rather than reversed at the end: the walk runs outermost → open project,
        so each new claimant is nearer than the ones before it. That keeps
        `resolve()` a pure derivation, which #307's incremental patching needs —
        a `reverse()` in `resolve()` would invert the winner on a second call.
        The lists are bounded by chain depth, so the insert is free.
        """
        self.candidates.setdefault(entry.id, []).insert(0, entry)

    def entry_for_layer(self, node_id: str, layer_id: str) -> NodeIndexEntry | None:
        """The entry a specific layer contributes for `node_id`, if any. Also the
        same-layer duplicate check: a second file claiming an id already claimed
        *at that layer* is an error, not a shadow."""
        return next(
            (entry for entry in self.candidates.get(node_id, []) if entry.source_layer_id == layer_id),
            None,
        )

    def add_diagnostic(
        self, *, layer_id: str, path: Path, message: str, is_error: bool, blocks_patch: bool = False
    ) -> None:
        """Record one collection diagnostic against the file that produced it.

        Keyed by `(layer_id, path)` so `_drop_entries_under`'s per-file drop can
        retract it (#382). Re-collecting a file drops its old diagnostics first,
        so fixing a malformed id no longer leaves the warning behind or emits it
        twice.
        """
        self.diagnostics_by_source.setdefault((layer_id, path), []).append(
            NodeDiagnostic(message=message, is_error=is_error, blocks_patch=blocks_patch)
        )

    @property
    def errors(self) -> list[str]:
        """The error-severity collection diagnostics, as flat strings — the shape
        `validate_project` and the snapshot's readers expect. Derived from
        `diagnostics_by_source`, so a dropped file's errors vanish with it."""
        return [d.message for diags in self.diagnostics_by_source.values() for d in diags if d.is_error]

    def collected_warnings(self) -> list[str]:
        """The warning-severity collection diagnostics, without the shadow
        warnings `resolve()` derives.

        What a snapshot (#306) may persist. The shadow warnings are a function
        of the candidate lists, so serializing them would double them the moment
        the rehydrated index re-resolves — and `resolve()` is exactly what
        rebuilds the derived views on load.
        """
        return [d.message for diags in self.diagnostics_by_source.values() for d in diags if not d.is_error]

    @property
    def warnings(self) -> list[str]:
        """The collection warnings followed by the shadow warnings `resolve()`
        last derived — the flat list `validate_project` shows the user."""
        return self.collected_warnings() + self._shadow_warnings

    def has_unpatchable_diagnostic(self) -> bool:
        """Whether any diagnostic is about a rejected file a per-file patch
        cannot retract (a same-layer duplicate id, a cross-kind collision). The
        `_patch_node_index` gate rebuilds when one is present (#382)."""
        return any(d.blocks_patch for diags in self.diagnostics_by_source.values() for d in diags)

    def resolve(self) -> None:
        """Rebuild the derived views from the candidate lists.

        **Idempotent**: it reads `candidates` (already innermost-first, see
        `add`) and rewrites the derived state from scratch, so running it again
        after more entries arrive is the supported way to re-resolve — which is
        what #307's incremental patching will do. It mutates nothing it reads.
        """
        self.by_id = {node_id: entries[0] for node_id, entries in self.candidates.items()}
        self.edges_by_src = {
            node_id: edges
            for node_id, winner in self.by_id.items()
            if (edges := self.edges_by_layer_src.get((winner.source_layer_id, node_id)))
        }
        # The collection diagnostics live in `diagnostics_by_source` and are read
        # through the `warnings` / `errors` properties, so `resolve()` only has
        # to re-derive the shadow warnings — a pure function of the candidate
        # lists — that the `warnings` property appends. Rebuilding this from
        # scratch keeps `resolve()` idempotent for #307's incremental patching.
        self._shadow_warnings = [
            f"Entry id {node_id} in {shadower.source_layer_label} shadows the entry from "
            f"{shadowed.source_layer_label}."
            for node_id, entries in self.candidates.items()
            for shadower, shadowed in zip(entries, entries[1:], strict=False)
            # A fork-to-here copy declares its severance (#313 / ADR-0039): when
            # the shadower forked from exactly the layer it shadows, the shadow
            # is deliberate, not an accidental id collision, so it is silent.
            if shadower.forked_from_layer_id != shadowed.source_layer_id
        ]
        self.rebuild_reverse_edges()

    def rebuild_reverse_edges(self) -> None:
        """(Re)build `edges_by_dst` from `edges_by_src`.

        Backlinks read this map rather than scanning a flat edge list — measured
        per query at Weber/huge scale: reverse map 179 ns / 194 ns, edge-list
        scan 229 µs / 518 µs (ADR-0040). Building it costs 0.7 ms / 6.5 ms, paid
        once per index build. Must run *after* the whole walk: forward edges are
        overwritten per id as inner layers shadow outer ones.
        """
        reverse: dict[str, list[ReferenceEdge]] = {}
        for edges in self.edges_by_src.values():
            for edge in edges:
                reverse.setdefault(edge.dst, []).append(edge)
        # Sorted, so a backlink list does not depend on the order ids happen to
        # sit in `candidates`. That order is an accident of insertion — a cold
        # build gets walk order, an incremental patch (#307) re-inserts a
        # touched id at the end — and the backlinks surface reads this list
        # directly, so it would reshuffle after an edit the user did not make.
        for edges in reverse.values():
            edges.sort(key=lambda edge: (edge.src, edge.field_id))
        self.edges_by_dst = reverse
