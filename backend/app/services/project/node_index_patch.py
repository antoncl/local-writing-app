"""Incremental node-index maintenance (#307 / ADR-0040).

#306 made the manifest diff available; it had one consumer and one verdict —
anything changed, rebuild everything. This turns the diff into a **work list**.
Stale almost always means "re-parse six files", not "re-walk three thousand".

The routing, from #307:

| diff | action |
|---|---|
| empty | use the snapshot as-is |
| changed / added node files | re-parse only those, patch in place |
| deleted node files | drop the entry and **re-resolve shadows** |
| a schema or manifest file | full rebuild — it fans out |
| anything unrecognised | full rebuild |

**Deletes are the interesting case, and the reason #334 exists.** Removing a
book's node that shadowed an ancestor's must make the ancestor visible again,
with *its* edges — and there is no changed file to re-parse. `candidates` keeps
every layer's claim on an id, so un-shadowing is `resolve()` re-deriving the
winner from a shorter list, and `edges_by_layer_src` keeps the ancestor's edges
under its own layer key so the promoted node arrives with its references intact
rather than silently stripped.

**Two things fan out and are therefore not patchable.** Edge extraction is
schema-driven, so one `metadata.schema.yaml` edit invalidates the edges of every
node of the affected entry types across the whole chain. `project.yaml` routes
the layer walk itself. Both are a full rebuild, and both are cheap to detect
because the manifest records them by name.

Ordering inside a patch is load-bearing and is exactly the order `_build_node_index`
uses: collect everything, *then* `resolve()` once. Resolving between files would
let a half-applied patch decide a winner.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.models import PROJECT_NODE_FILENAME, MetadataSchema
from app.services.project.layers import MANIFEST_FILENAME, SCHEMA_FILENAME
from app.services.project.node_index import (
    IndexLayer,
    NodeFamily,
    NodeIndex,
    NodeIndexEntry,
)

log = logging.getLogger(__name__)


class PatchNotApplicable(Exception):
    """This diff cannot be patched — the caller must rebuild.

    Raised rather than returned so a patch abandoned half-way cannot be
    mistaken for a completed one. The index being patched is mutated in place,
    so an abandoned attempt leaves a partial index; the caller must discard it,
    and an exception is what makes that unmissable.
    """


class NodeIndexPatchMixin:
    def _patch_node_index(
        self,
        index: NodeIndex,
        *,
        changed: tuple[str, ...],
        layers: list[IndexLayer],
        root: Path,
        schema: MetadataSchema | None,
    ) -> NodeIndex:
        """Apply `changed` to `index`, or raise `PatchNotApplicable`.

        `index` is mutated. On success it is `resolve()`d and equivalent to a
        cold build over the same files — that equivalence is the whole contract,
        and it is what the tests assert rather than any internal step.
        """
        if index.has_unparsed_nodes:
            # The flag means "some file's identity is unknown" (#379), and a
            # patch cannot clear it: re-parsing the files in `changed` says
            # nothing about the ones that failed and did not change. Rebuilding
            # is what lets it become false again once the user fixes the typo.
            raise PatchNotApplicable("the snapshot recorded unparsed node files")
        if index.errors or index.collected_warnings():
            # **A patch requires a clean index.** Collection diagnostics are
            # free-form strings with no record of which file produced them, so
            # dropping a file cannot retract its message: fix a malformed id and
            # the warning survives; edit the file again and it is emitted twice.
            # `validate_project` shows these verbatim, and the snapshot persists
            # them, so the wrong output would be monotonic — it never heals.
            #
            # It also covers a subtler one. A same-layer duplicate id records an
            # *error* and indexes only the first claimant, so the sibling is not
            # in `candidates`; deleting the winner would leave nothing to
            # promote and the id would vanish, while a cold build promotes the
            # sibling. Both are the same underlying gap — diagnostics carry no
            # provenance — so both wait on the same fix (#382).
            #
            # Derived shadow warnings are excluded: `resolve()` retracts and
            # re-emits those itself, and they are common enough that including
            # them would disable patching for any project with an override.
            raise PatchNotApplicable("the index carries diagnostics that a patch cannot retract")

        # One unit per changed **path** — `_collect_entry_file` collects a
        # single file, so re-parsing a folder's other few hundred entries buys
        # nothing. Deduplicated because a chat or project-node unit is
        # folder-shaped and two changed chats are one re-collect.
        units: dict[tuple[str, str], _PatchUnit] = {}
        for path_str in changed:
            unit = self._patch_unit(Path(path_str), layers)
            units.setdefault(unit.key, unit)
        # **Drop everything first, then collect.** Two phases, not one per unit,
        # because a rename is a delete plus an add of the same id at the same
        # layer and the diff is ordered by path rather than by intent. Collect
        # the new name while the old entry is still present and the same-layer
        # duplicate guard rejects it — then the old unit drops the original, and
        # the node has vanished. A cold build never sees this because it starts
        # from an empty index; two phases give the patch the same footing.
        # Above roughly half the project, patching stops being a saving: it
        # re-parses the same files a rebuild would *plus* the rehydrate, the
        # drop bookkeeping and a second snapshot write. Measured crossover is
        # ~36% of nodes, where a patch runs 2.1x slower than the rebuild it
        # replaces. Real triggers are ordinary — a `git pull`, a cloud-sync
        # re-download that moves every mtime, a restore from backup.
        if len(units) * 2 > max(len(index.candidates), 1):
            raise PatchNotApplicable(f"{len(units)} units over {len(index.candidates)} nodes; rebuilding is cheaper")
        # Built once, not re-scanned per unit. The drop used to walk every
        # candidate list for every changed path — O(changed x nodes), and 38-45%
        # of patch cost at scale.
        entries_by_path: dict[str, list[NodeIndexEntry]] = {}
        for entries in index.candidates.values():
            for entry in entries:
                entries_by_path.setdefault(str(entry.path), []).append(entry)
        for unit in units.values():
            self._drop_entries_under(index, unit, entries_by_path=entries_by_path)
        for unit in units.values():
            self._collect_patch_unit(index, unit, root=root, schema=schema)
        self._restore_candidate_order(index, layers)
        # Once, at the end — same as the cold build. Re-deriving the winners
        # per unit would let a half-applied patch pick one.
        index.resolve()
        return index

    def _restore_candidate_order(self, index: NodeIndex, layers: list[IndexLayer]) -> None:
        """Put every candidate list back in innermost-first order.

        `NodeIndex.add` front-inserts, which is correct **only** while entries
        arrive in walk order — outermost first — as its docstring states. A cold
        build satisfies that by construction; a patch collects in changed-path
        order, which has nothing to do with layer depth. So re-collecting an
        *ancestor's* file inserted it ahead of the descendant shadowing it and
        the ancestor won: wrong node content everywhere, the layer stack
        backwards, the shadow warning reversed, the edges following the wrong
        winner — and persisted, so nothing short of a full rebuild healed it.

        Sorting on the explicit `IndexLayer.rank` rather than preserving arrival
        order is what makes the patch independent of the order the diff happens
        to arrive in. #329 made rank explicit for exactly this kind of consumer.
        """
        rank_by_layer = {layer.id: layer.rank for layer in layers}
        for entries in index.candidates.values():
            if len(entries) > 1:
                # Descending: the walk runs outermost (rank 0) → open project,
                # so the innermost layer has the highest rank and wins.
                entries.sort(key=lambda entry: rank_by_layer.get(entry.source_layer_id, -1), reverse=True)

    def _patch_unit(self, path: Path, layers: list[IndexLayer]) -> _PatchUnit:
        """Which collection unit a changed path belongs to.

        Resolved against the walk's own layers and the collectors' own folder
        rules, so a path this cannot place is a path the index would not have
        collected — which means the diff describes something this module does
        not model, and the honest answer is to rebuild.
        """
        for layer in layers:
            if path.parent == layer.folder:
                # Layer-level files. `project.md` is an ordinary node; the two
                # yaml files change what every node *means*.
                if path.name == PROJECT_NODE_FILENAME:
                    return _PatchUnit(layer, kind="project_node")
                if path.name in (SCHEMA_FILENAME, MANIFEST_FILENAME):
                    raise PatchNotApplicable(f"{path.name} fans out across the chain")
                raise PatchNotApplicable(f"unrecognised layer file {path.name}")
            for family in self._families_for_layer(layer):
                if path.parent == layer.folder / family.folder_name and path.suffix == ".md":
                    return _PatchUnit(layer, kind="family", family=family, path=path)
            if layer.is_root and path.parent == layer.folder / "chats" and path.suffix == ".yaml":
                return _PatchUnit(layer, kind="chat")
        raise PatchNotApplicable(f"no layer owns {path}")

    def _collect_patch_unit(
        self,
        index: NodeIndex,
        unit: _PatchUnit,
        *,
        root: Path,
        schema: MetadataSchema | None,
    ) -> None:
        """Re-collect one unit, after every unit's drop has run.

        Collect rather than update-in-place, because a file's **id can change**:
        identity is the front-matter `id`, not the path, so an edit that renames
        the id is a delete plus an add, and an update would leave the old id
        claiming a file that no longer declares it. A deleted file simply
        contributes nothing — `resolve()` then promotes whatever ancestor was
        underneath, with its edges, because those are still keyed under that
        ancestor's own layer (#334).
        """
        if unit.kind == "project_node":
            self._collect_project_node_entry(layer=unit.layer, index=index, schema=schema)
        elif unit.kind == "chat":
            self._collect_chat_entries(layer=unit.layer, index=index)
        else:
            assert unit.family is not None and unit.path is not None
            if unit.path.exists():
                self._collect_entry_file(
                    unit.path,
                    layer=unit.layer,
                    family=unit.family,
                    index=index,
                    duplicate_relative_to=root,
                    schema=schema,
                )

    def _drop_entries_under(
        self, index: NodeIndex, unit: _PatchUnit, *, entries_by_path: dict[str, list[NodeIndexEntry]]
    ) -> None:
        """Remove this layer's claims arising from the unit's folder.

        Only this layer's, and only this folder's. The other candidates are
        other files that still exist; dropping them is exactly how un-shadowing
        would turn into data loss, because `resolve()` needs the survivors in
        order to promote one.
        """
        if unit.path is not None:
            candidates_at_path = entries_by_path.get(str(unit.path), [])
        else:
            # Folder-shaped units (chats, the project node) still scan, but over
            # the path map rather than every candidate list.
            candidates_at_path = [
                entry
                for path_str, entries in entries_by_path.items()
                if Path(path_str).parent == unit.folder
                for entry in entries
            ]
        doomed = [entry for entry in candidates_at_path if entry.source_layer_id == unit.layer.id]
        for entry in doomed:
            # Matched on **layer and path**, so a drop removes exactly what its
            # own unit contributed and nothing else. With the two-phase ordering
            # above, dropping by layer alone would pass every test here — the
            # rename case is fixed by the phasing, not by this. It stays because
            # the alternative is a drop whose scope is wider than its unit: a
            # same-layer sibling claiming the same id (a duplicate-id error
            # state) would be removed without ever being re-collected.
            remaining = [
                candidate
                for candidate in index.candidates.get(entry.id, [])
                if not (candidate.source_layer_id == entry.source_layer_id and candidate.path == entry.path)
            ]
            if remaining:
                index.candidates[entry.id] = remaining
            else:
                index.candidates.pop(entry.id, None)
            # Only when no other file at this layer still claims the id —
            # otherwise a rename would strip the surviving entry's edges.
            if not any(candidate.source_layer_id == entry.source_layer_id for candidate in remaining):
                index.edges_by_layer_src.pop((entry.source_layer_id, entry.id), None)


class _PatchUnit:
    """One unit of re-collection: a layer plus the folder a collector globs.

    `key` is what deduplicates — two changed files in the same `lore/` are one
    unit, because that is exactly how much work re-collecting either of them
    costs.
    """

    __slots__ = ("layer", "kind", "family", "path")

    def __init__(
        self,
        layer: IndexLayer,
        *,
        kind: str,
        family: NodeFamily | None = None,
        path: Path | None = None,
    ) -> None:
        self.layer = layer
        self.kind = kind
        self.family = family
        # Set for node files, which are collected one at a time. Chats and the
        # project node are collected by their whole (small, fixed) folder.
        self.path = path

    def owns(self, candidate: Path) -> bool:
        """Whether an existing entry came from this unit — so it must be dropped
        before re-collecting."""
        if self.path is not None:
            return candidate == self.path
        return candidate.parent == self.folder

    @property
    def folder(self) -> Path:
        if self.kind == "family":
            assert self.family is not None
            return self.layer.folder / self.family.folder_name
        if self.kind == "chat":
            return self.layer.folder / "chats"
        return self.layer.folder

    @property
    def key(self) -> tuple[str, str]:
        return (self.layer.id, str(self.path if self.path is not None else self.folder))
