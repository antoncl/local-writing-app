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
from pathlib import Path
from typing import Protocol

from app.services.project.node_index import IndexLayer

# The metadata-schema file each project layer may carry. Not applicable to the
# machine layer, which is out-of-tree and contributes assistants only.
SCHEMA_FILENAME = "metadata.schema.yaml"


class LayerVisitor(Protocol):
    """Visits each layer in walk order. Implementations carry whatever per-layer
    logic used to live inside a bespoke traversal."""

    def visit_layer(self, layer: IndexLayer) -> None: ...


class LayerWalkMixin:
    def project_layers(self, root: Path, *, include_machine: bool = False) -> list[IndexLayer]:
        """The layer chain, outermost first, root last.

        `include_machine` prepends the machine config dir as an ordinary
        out-of-tree layer (`is_machine=True`) when it actually holds an
        `assistants/` folder — the condition the old
        `_collect_machine_layer_assistants` early-returned on. Schema layering
        must not include it, so it is opt-in rather than default.
        """
        layers: list[IndexLayer] = []
        if include_machine:
            machine_folder = self._machine_layer_folder()
            if machine_folder is not None:
                layers.append(
                    IndexLayer(
                        folder=machine_folder,
                        id=self._metadata_schema_layer_id(machine_folder),
                        label="Machine",
                        rank=len(layers),
                        is_machine=True,
                    )
                )
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

    def visit_layers(
        self,
        visitor: LayerVisitor,
        root: Path,
        *,
        include_machine: bool = False,
    ) -> None:
        """Drive `visitor` over the walk, in order."""
        for layer in self.project_layers(root, include_machine=include_machine):
            visitor.visit_layer(layer)

    def layer_by_id(self, root: Path, layer_id: str, *, include_machine: bool = False) -> IndexLayer | None:
        """Reverse a `source_layer_id` back to its layer, or None when unknown.

        The id is a hash of the folder path, so this is a linear scan of the
        walk rather than a registry lookup.
        """
        for layer in self.project_layers(root, include_machine=include_machine):
            if layer.id == layer_id:
                return layer
        return None

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
        return hashlib.sha256(str(folder.resolve()).encode("utf-8")).hexdigest()[:16]

    def _layer_label_for_folder(self, root: Path, folder: Path, layer_index: int) -> str:
        if folder == root:
            return self.title or root.name
        if layer_index == 0:
            return "Base Folder"
        return folder.name

    def _metadata_schema_layer_paths(self, root: Path) -> list[Path]:
        return [layer.folder / SCHEMA_FILENAME for layer in self.project_layers(root)]
