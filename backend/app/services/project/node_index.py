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


@dataclass(frozen=True)
class NodeIndexEntry:
    id: str
    kind: str
    entry_type: str
    path: Path
    title: str = ""
    source_layer_id: str = ""
    source_layer_label: str = ""


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
    """

    folder: Path
    id: str
    label: str
    rank: int
    is_root: bool = False
    is_machine: bool = False


@dataclass(frozen=True)
class NodeFamily:
    """A kind and where its files live — the (kind, folder, default entry type)
    triple `_build_node_index` iterates once per layer."""

    kind: str
    folder_name: str
    default_entry_type: str


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
    # --- derived (see `resolve`) ---
    by_id: dict[str, NodeIndexEntry] = field(default_factory=dict)
    edges_by_src: dict[str, list[ReferenceEdge]] = field(default_factory=dict)
    # Reverse adjacency — the structure backlinks are served from. Populated by
    # `rebuild_reverse_edges` once the walk is complete.
    edges_by_dst: dict[str, list[ReferenceEdge]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
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

    def collected_warnings(self) -> list[str]:
        """The warnings collection produced, without the shadow warnings
        `resolve()` derives.

        What a snapshot (#306) may persist. The shadow warnings are a function
        of the candidate lists, so serializing them would double them the moment
        the rehydrated index re-resolves — and `resolve()` is exactly what
        rebuilds the derived views on load.
        """
        return [warning for warning in self.warnings if warning not in self._shadow_warnings]

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
        self.warnings = [warning for warning in self.warnings if warning not in self._shadow_warnings]
        self._shadow_warnings = [
            f"Entry id {node_id} in {shadower.source_layer_label} shadows the entry from "
            f"{shadowed.source_layer_label}."
            for node_id, entries in self.candidates.items()
            for shadower, shadowed in zip(entries, entries[1:], strict=False)
        ]
        self.warnings.extend(self._shadow_warnings)
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
