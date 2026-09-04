"""Per-layer node-file collection (#1806, split out of `references.py`).

The collectors the index walk (`_NodeIndexBuilder`, `references.py`) and the
incremental patch (`node_index_patch.py`) both call per file/folder: parse one
node file's front matter into a `NodeIndexEntry` plus its reference edges
(`_collect_entry_file`), glob a family's folder into that per-file call
(`_collect_layer_entries`), the layer-root `project.md` (#334,
`_collect_project_node_entry`), and the machine layer on its own for the
no-project-open case (`_collect_machine_layer_assistants`). `_forked_from_layer_id`
/ `_merged_into` resolve two front-matter values these collectors stamp onto an
entry. `_families_for_layer` is a one-line delegate to the free function of the
same name in `node_families.py`, kept here so `layers.py` and
`node_index_patch.py`'s `self._families_for_layer(...)` call sites are
unchanged.

`ProjectService` composes this mixin. Shared helpers these methods reach on the
composed class (`self._read_front_matter_only`, `self._require_node_id`,
`self._front_matter_id`, `self._safe_relative`, `self._reference_edges_for_entry`
— the node-identity and edge-extraction helpers, still in `references.py`;
`self._metadata_schema_base_folder`, `self._metadata_schema_layer_id`,
`self.machine_layer` — the layer walk, in `layers.py`; `self.root_path`) live
elsewhere on the composed class and resolve through the MRO at call time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models import PROJECT_NODE_FILENAME, MetadataSchema
from app.services.project.errors import ProjectServiceError
from app.services.project.node_families import families_for_layer
from app.services.project.node_index import (
    IndexLayer,
    NodeFamily,
    NodeIndex,
    NodeIndexEntry,
)


class IndexCollectMixin:
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
        return families_for_layer(layer)

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
            merged_into=self._merged_into(family.kind, front_matter),
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

    def _merged_into(self, kind: str, front_matter: dict[str, Any]) -> str | None:
        """A tag's `metadata.merged_into`, read straight off the parsed front
        matter (ADR-0082 §5) — not through `_reference_edges_for_entry`, which
        needs a loaded schema and runs later. Reading it here at collection
        time means `NodeIndex.resolve()` can fold every reference-lifecycle
        pass onto the survivor even when the schema failed to load. `None` for
        every non-`tag` kind and for an ordinary (unmerged) tag."""
        if kind != "tag":
            return None
        metadata = front_matter.get("metadata")
        if not isinstance(metadata, dict):
            return None
        raw = metadata.get("merged_into")
        return raw.strip() if isinstance(raw, str) and raw.strip() else None
