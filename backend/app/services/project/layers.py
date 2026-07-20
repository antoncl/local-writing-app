"""The one layer walk (#329 / ADR-0039 Amendment 2).

Every consumer that needs "the folders this project inherits from, outermost
first" visits **this** traversal. Before #329 there were six derivations of the
same chain — the walk, the thing deciding where it stops, the schema-path map,
the node-index build (constructing `IndexLayer` inline with rank implied by
`enumerate`), the assistant roster (layer folder from an entry's path, rank from
index insertion order) and the machine layer special-cased at two more sites.
A change to *how far* the walk goes was therefore six edits, and they drifted:
`assistants.py` inferred rank from dict insertion order, so an incremental index
patch (#307) would silently reorder the roster.

The walk yields `IndexLayer` objects stamped with everything a consumer used to
re-derive: `folder`, `id`, `label`, an **explicit `rank`**, and the `is_root` /
`is_machine` flags. Per-layer logic lives in the visitor, not in a private copy
of the traversal.

**Behaviour is preserved exactly**, including the base-folder widening in
`_metadata_schema_base_folder` (see its docstring). #329 is a refactor: the
scattered walks collapse into one, and what each did per layer becomes a
visitor. ADR-0039 Amendment 2 also stipulates the root rather than inferring it
from a stray `metadata.schema.yaml` — that is a **behaviour** change and lands
separately (#337), which is now a one-line edit in one place because of this.

Ordering contract, relied on by consumers:

* The machine layer, when present, comes **first** (rank 0). The assistant
  roster's layer-grouped sort depends on it (ADR-0037 §7 / #224).
* Project layers follow, **outermost ancestor → open project**, so a descendant
  entry overwrites an ancestor's on an id collision.
* `rank` is dense over the yielded sequence and only ever compared, never used
  as an index into anything.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.services.project.node_index import IndexLayer

# The metadata-schema file each project layer may carry. Not applicable to the
# machine layer, which is out-of-tree and contributes assistants only.
SCHEMA_FILENAME = "metadata.schema.yaml"


@lru_cache(maxsize=1024)
def _layer_id_for_folder(folder: Path) -> str:
    """A layer's stable id: sha256 of its resolved path, first 16 hex chars.

    Memoised because `Path.resolve()` is a filesystem syscall (~0.16 ms on
    Windows) and this is called once per layer per walk, on paths that barely
    change within a session. Caching here rather than letting hot callers skip
    the walk keeps the optimisation *inside* the abstraction, so every consumer
    gets it. Keyed on the argument, so a rename produces a new key rather than
    a stale hit.

    ⚠ **The cache is safe only because layer ids are never persisted.** They are
    derived, compared against ids from this same function within one process,
    and reversed to a folder via the *walk* (`layer_by_id`), never via the id
    itself — so even a stale entry stays self-consistent. Nothing writes a layer
    id to disk today (`.order.yaml` holds entry ids). **#334 is where that could
    change** — it owns layer-qualified identity and explicit rank, the shape
    #306's snapshot serializes. If a layer id ever lands on disk, revisit this:
    a path-hash id survives neither a moved project folder nor a re-resolved
    symlink, cache or no cache.
    """
    return hashlib.sha256(str(folder.resolve()).encode("utf-8")).hexdigest()[:16]


class LayerVisitor(Protocol):
    """Visits each layer in walk order. Implementations carry whatever per-layer
    logic used to live inside a bespoke traversal.

    **Every consumer of the chain is a visitor** — including the ones whose body
    would reduce to a one-line comprehension. Uniformity is the point: the walk's
    definition changes mid-development (#309 declares inheritance, #318's wizard
    authors it, #337 stipulates the root), and a consumer that iterates the
    sequence itself is a second place to find when it does. The number of sites
    needing a walk only grows, so non-uniformity compounds while the few
    microseconds saved never do.
    """

    def visit_layer(self, layer: IndexLayer) -> None: ...


# Concrete visitors subclass the Protocol explicitly. It buys no static check —
# there is no mypy in the gates, and `from __future__ import annotations` makes
# the annotation a string that is never evaluated — but it makes every visitor
# greppable from one name, which is the point of insisting they all be visitors.


class LayerCollector(LayerVisitor):
    """The visitor that accumulates the sequence, in order.

    A consumer with no real per-layer logic does not need a bespoke visitor and
    does not need to iterate the walk itself: it visits with this and iterates
    the result. That is still one traversal, still visitor-mediated, and reads
    like the comprehension it replaces. The extra pass is a constant factor over
    a sequence bounded by chain depth — O(2N) is O(N), and the per-layer work is
    memoised anyway.

    So there are two legitimate shapes, and neither is a compromise:
    bespoke visitor when there is per-layer work (`_NodeIndexBuilder`),
    `collect_layers` + a comprehension when there is not.
    """

    def __init__(self) -> None:
        self.layers: list[IndexLayer] = []

    def visit_layer(self, layer: IndexLayer) -> None:
        self.layers.append(layer)


class LayerWalkMixin:
    def visit_layers(
        self,
        visitor: LayerVisitor,
        root: Path,
        *,
        include_machine: bool = False,
    ) -> None:
        """Drive `visitor` over the layer chain, outermost first, root last.

        **The** entry point. `include_machine` prepends the machine config dir
        as an ordinary out-of-tree layer (`is_machine=True`) when it actually
        holds an `assistants/` folder — the condition the old
        `_collect_machine_layer_assistants` early-returned on. Schema layering
        must not see it, so it is opt-in rather than default.
        """
        for layer in self._layer_sequence(root, include_machine=include_machine):
            visitor.visit_layer(layer)

    def _layer_sequence(self, root: Path, *, include_machine: bool) -> list[IndexLayer]:
        """Build the chain. Private: consumers visit, they do not iterate."""
        layers: list[IndexLayer] = []
        if include_machine:
            machine_layer = self.machine_layer(rank=len(layers))
            if machine_layer is not None:
                layers.append(machine_layer)
        # `chain_index` is the position within the *project* chain, which is what
        # the label rule keys on ("Base Folder" is the outermost project layer).
        # It is deliberately not the same number as `rank`, which spans the whole
        # yielded sequence including the machine layer.
        for chain_index, folder in enumerate(self._project_layer_folders(root)):
            layers.append(
                IndexLayer(
                    folder=folder,
                    id=self._metadata_schema_layer_id(folder),
                    label=self._layer_label_for_folder(root, folder, chain_index),
                    rank=len(layers),
                    is_root=folder == root,
                )
            )
        return layers

    def collect_layers(self, root: Path, *, include_machine: bool = False) -> list[IndexLayer]:
        """The whole sequence, via `LayerCollector`. For callers that really do
        want every layer at once."""
        collector = LayerCollector()
        self.visit_layers(collector, root, include_machine=include_machine)
        return collector.layers

    def layer_by_id(self, root: Path, layer_id: str, *, include_machine: bool = False) -> IndexLayer | None:
        """Reverse a `source_layer_id` back to its layer, or None when unknown."""
        return next(
            (
                layer
                for layer in self.collect_layers(root, include_machine=include_machine)
                if layer.id == layer_id
            ),
            None,
        )

    def machine_layer(self, *, rank: int = 0) -> IndexLayer | None:
        """The machine layer as an `IndexLayer`, or None when it has no
        `assistants/` folder.

        One constructor, so the walk and the two callers that need the machine
        layer *without* a project chain (the index's no-project path and the
        roster's) cannot drift apart on its id, label or flags — which is the
        exact duplication #329 exists to remove.
        """
        folder = self._machine_layer_folder()
        if folder is None:
            return None
        return IndexLayer(
            folder=folder,
            id=self._metadata_schema_layer_id(folder),
            label="Machine",
            rank=rank,
            is_machine=True,
        )

    def _machine_layer_folder(self) -> Path | None:
        """The machine config dir, when it carries an `assistants/` folder.

        Imported lazily: `machine_settings` reaches back into service-level
        config and importing it at module scope closes an import cycle.
        """
        from app.services import machine_settings as ms_service

        machine_dir = ms_service.assistants_dir().parent
        if not (machine_dir / "assistants").exists():
            return None
        return machine_dir

    def _project_layer_folders(self, root: Path) -> list[Path]:
        """Project folders from outermost ancestor to current root, inclusive."""
        base_folder = self._metadata_schema_base_folder(root)
        if base_folder is None or not self._is_relative_to(root, base_folder):
            return [root]

        folders: list[Path] = []
        current = root
        while True:
            folders.append(current)
            if current == base_folder:
                break
            current = current.parent
        return list(reversed(folders))

    def _metadata_schema_base_folder(self, root: Path) -> Path | None:
        """Where the walk stops — the outer bound of the layer chain.

        ⚠ **Known behaviour, deliberately preserved by #329 and tracked as
        #337.** When the configured `projects_base_folder` equals `root.parent`
        — which the project chooser writes on *every* create, so it is the
        normal path — this ignores the configured value and substitutes the
        **outermost** ancestor anywhere up `root.parents` that happens to
        contain a `metadata.schema.yaml`. A stray schema file in a grandparent
        therefore sets the extent of schema layering, the node index and the
        assistant roster. ADR-0039 Amendment 2 stipulates the root instead;
        removing the widening is a behaviour change and is *not* part of the
        #329 refactor. It is now a single edit, here.
        """
        manifest = self._read_yaml(root / "project.yaml")
        settings = manifest.get("settings")
        if not isinstance(settings, dict):
            return None
        base_folder = settings.get("projects_base_folder")
        if not isinstance(base_folder, str) or not base_folder.strip():
            return None
        configured_base = Path(base_folder).expanduser().resolve()
        if configured_base == root.parent:
            schema_ancestors = [
                ancestor
                for ancestor in root.parents
                if ancestor != root.parent and (ancestor / SCHEMA_FILENAME).exists()
            ]
            if schema_ancestors:
                return schema_ancestors[-1].resolve()
        return configured_base

    def _metadata_schema_layer_id(self, folder: Path) -> str:
        return _layer_id_for_folder(folder)

    def _layer_label_for_folder(self, root: Path, folder: Path, layer_index: int) -> str:
        if folder == root:
            return self.title or root.name
        if layer_index == 0:
            return "Base Folder"
        return folder.name

    def _metadata_schema_layer_paths(self, root: Path) -> list[Path]:
        """Schema-file candidates, base → root — as a visitor like everything
        else, even though the body is one line.

        This called `_project_layer_folders` directly for a while, to dodge the
        `Path.resolve()` each layer id costs (`read_metadata_schema` is hot and
        discards the ids). That was premature optimisation buying microseconds
        at the price of a second place to change the walk. The cost is now paid
        once, memoised in `_layer_id_for_folder`.
        """
        return [layer.folder / SCHEMA_FILENAME for layer in self.collect_layers(root)]
