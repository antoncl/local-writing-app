"""Assistant-entry slice of ProjectService (#14 backend split).

Assistants are file-backed, layered, machine-first Node markdown files
(the canonical roster lives under the per-user machine config dir; project
layers can add their own). This mixin owns their CRUD plus the assistant-
scoped index/resolve helpers; `ProjectService` composes it. Method bodies
moved verbatim from project_service.py — shared helpers they call
(`self._build_node_index`, `self._collect_machine_layer_assistants`,
`self._read_markdown_with_front_matter`, `self._read_front_matter_only`,
`self._normalise_metadata`, `self._revision`, `self._node_id_for_path`,
`self._write_node_entry_file`, `self._filepath_for_new_node`,
`self._new_id`, `self._check_entry_type_kind`, `self._maybe_rename_node_file`,
`self._read_yaml`, `self._write_yaml`, `self.root_path`) still live on the
core class and resolve through the MRO at call time. The layer walk
(`self.visit_layers`, `self.layer_by_id`, `self._metadata_schema_layer_id`,
`self._machine_layer_folder`) lives in `layers.py` since #329 and resolves the
same way — the roster's layer rank now comes from the walk rather than from
`index.by_id` insertion order.

`_build_assistant_index` moves here even though it instantiates `NodeIndex`
and calls `_collect_machine_layer_assistants`: `NodeIndex` is imported from
the shared node_index module, and `_collect_machine_layer_assistants` stays
in core (it's shared with `_build_node_index`) — reached via self → MRO.
`resolve_assistant` is also called by ChatSessionsMixin.save_chat_session;
that call resolves here through the composed class's MRO.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.models import (
    AssistantEntry,
    AssistantEntryList,
    AssistantEntrySummary,
    CreateAssistantEntryRequest,
    ReorderAssistantsRequest,
    SaveAssistantEntryRequest,
    UnlistAssistantRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.layers import LayerVisitor
from app.services.project.node_index import IndexLayer, NodeIndex, NodeIndexEntry

log = logging.getLogger(__name__)


@dataclass
class AssistantsOrder:
    """One layer's ordering *opinion*, as stored in its `assistants/.order.yaml`.

    Two lists, because omission cannot express un-listing (#332): dropping an id
    from a book's file only means the book has no opinion, so the id survives in
    the inherited remainder and returns from the universe. Removal needs a
    positive expression, hence `excluded`.
    """

    ids: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)


@dataclass
class MergedAssistantOrder:
    """The resolved sequence, and the removals that survived to the open layer.

    `excluded` is not derivable from `ids`: "absent from the merged list"
    conflates *no layer had an opinion* (unlisted — sorts into the alphabetical
    tail) with *a layer said no* (gone from the roster). The first version of
    this returned only `ids`, and un-listed assistants came straight back in the
    tail.
    """

    ids: list[str] = field(default_factory=list)
    excluded: set[str] = field(default_factory=set)


def _string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, str)]


class _AssistantOrderMerger(LayerVisitor):
    """Folds every layer's opinion into ONE priority sequence (#332).

    Layers arrive outermost → innermost, so at each step the accumulator is
    exactly the `inherited_merged` of the model's formula and the layer applies
    on top of it:

        merged = local.ids + (inherited_merged − local.ids) − local.excluded

    Descendant-wins falls out in both directions, which is the test that this is
    the right shape: an ancestor's exclusion is undone by a descendant naming the
    id in `ids` (it is re-added ahead of the remainder), and an ancestor's
    listing is undone by a descendant excluding it (it is filtered after
    concatenation). An id named at a nearer layer also *rises* to that layer's
    position, because it is stripped from the remainder before concatenation.

    The machine layer is visited first, so it settles at the bottom — the
    deliberate reversal of the pre-#332 machine-first roster. Most-local-wins is
    the rule the rest of the layer model already runs on.

    This is the add/remove half of `_resolve_collection`'s vocabulary
    (`lore_mutations.py`), not the whole of it: ordering has no `replace` op, so
    the replace-cut half does not apply. Same words, smaller grammar — not a
    second vocabulary invented for ordering.
    """

    def __init__(self, read_order: Callable[[Path], AssistantsOrder]) -> None:
        self._read_order = read_order
        self.merged = MergedAssistantOrder()

    def visit_layer(self, layer: IndexLayer) -> None:
        order = self._read_order(layer.folder / "assistants")
        local: list[str] = []
        seen: set[str] = set()
        for entry_id in order.ids:
            if entry_id not in seen:
                seen.add(entry_id)
                local.append(entry_id)
        # An id in both lists at one layer is malformed: `ids` wins, and we say
        # so. Files are truth, so a hand-edit must not be able to break the
        # roster — it may only be surprising.
        contradictory = sorted({eid for eid in order.excluded if eid in seen})
        if contradictory:
            log.warning(
                "assistants/.order.yaml at %s lists %s in both `ids` and `excluded`; "
                "`ids` wins.",
                layer.folder,
                ", ".join(contradictory),
            )
        excluded = {eid for eid in order.excluded if eid not in seen}
        inherited = [entry_id for entry_id in self.merged.ids if entry_id not in seen]
        self.merged = MergedAssistantOrder(
            ids=[entry_id for entry_id in local + inherited if entry_id not in excluded],
            # Listing an id locally clears an inherited exclusion of it — the
            # descendant-wins direction that lets a book bring back something a
            # series removed.
            excluded=(self.merged.excluded - seen) | excluded,
        )


class AssistantEntriesMixin:
    def list_assistant_entries(self) -> AssistantEntryList:
        index = self._build_assistant_index()
        entries: list[AssistantEntrySummary] = []
        for entry in index.by_id.values():
            if entry.kind != "assistant":
                continue
            try:
                front_matter, _body = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            raw_entry_type = front_matter.get("entry_type") or "assistant:assistant"
            entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "assistant:assistant"
            entries.append(
                AssistantEntrySummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    entry_type=entry_type,
                    metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
        # ONE merged sequence across every layer (#332), so position in it is
        # the whole ordering story. `layer_rank` used to lead this key, keeping
        # the roster layer-grouped with the machine bucket on top (#224 /
        # ADR-0037 §7). It comes off the front here: concatenation order now
        # *encodes* precedence, so a layer term would fight the user's single
        # drag-ordered list rather than refine it. The grouping that relied on
        # it moves with #333.
        merged = self.merged_assistant_order()
        entries = [entry for entry in entries if entry.id not in merged.excluded]
        positions = {entry_id: idx for idx, entry_id in enumerate(merged.ids)}

        def sort_key(entry: AssistantEntrySummary):
            if entry.id in positions:
                return (0, positions[entry.id], "")
            # Unlisted at every layer: one global alphabetical tail. Pre-#332
            # this tail was per layer, because rank led the key.
            return (1, 0, entry.title.lower())

        entries.sort(key=sort_key)
        return AssistantEntryList(entries=entries)

    def merged_assistant_order(self) -> MergedAssistantOrder:
        """The one priority sequence, merged across every layer (#332).

        Ids naming an assistant that no longer exists (deleted, or in a layer no
        longer inherited) stay in the list and are simply never matched by a
        caller — ignored, not an error.
        """
        merger = _AssistantOrderMerger(self._read_assistants_order)
        if self.root_path is not None:
            self.visit_layers(merger, self.root_path, include_machine=True)
        else:
            # No project open: the machine layer is the whole chain — the same
            # degenerate case `_build_assistant_index` handles.
            machine_layer = self.machine_layer()
            if machine_layer is not None:
                merger.visit_layer(machine_layer)
        return merger.merged

    def reorder_assistant_entries(
        self, request: ReorderAssistantsRequest
    ) -> AssistantEntryList:
        folder = self._assistant_layer_folder_for_id(request.layer_id)
        # No `folder.exists()` guard: a layer that owns no assistants of its own
        # still gets to hold an opinion about the ones it inherits, which is the
        # whole point (#332). The pre-#332 guard 404'd there because
        # `ordered_ids` could only name local files; `_write_assistants_order`
        # creates the folder. `unlist_assistant_entry` has always worked this
        # way, and the two gestures must not disagree about the same layer.
        # Validate against the WHOLE roster, not this layer's own files (#332).
        # Dragging an inherited assistant is the central gesture: it names a
        # foreign id in the *local* file and no ancestor file is touched, which
        # is what makes the drag layer-safe by construction. The pre-#332 check
        # globbed `folder/*.md` and 422'd on anything else, i.e. it rejected
        # exactly the gesture this issue exists to enable.
        unknown = [eid for eid in request.ordered_ids if eid not in self._known_assistant_ids()]
        if unknown:
            raise ProjectServiceError(
                f"Unknown assistant id(s): {', '.join(unknown)}.", 422
            )
        # Preserve only the supplied ids; unlisted entries trail alphabetically.
        dedup: list[str] = []
        seen: set[str] = set()
        for entry_id in request.ordered_ids:
            if entry_id in seen:
                continue
            seen.add(entry_id)
            dedup.append(entry_id)
        order = self._read_assistants_order(folder)
        order.ids = dedup
        # A dragged id is a positive listing, so it outranks a stale exclusion
        # at this same layer — otherwise the drop would silently do nothing.
        order.excluded = [eid for eid in order.excluded if eid not in seen]
        self._write_assistants_order(folder, order)
        return self.list_assistant_entries()

    def unlist_assistant_entry(self, request: UnlistAssistantRequest) -> AssistantEntryList:
        """Remove an assistant from the roster *at this layer and inward* (#332).

        Writes to the local layer's `excluded`, never to the file the assistant
        lives in — un-listing an inherited assistant in Book 12 must not remove
        it from the universe. A descendant can name the id in its own `ids` to
        bring it back.
        """
        if request.entry_id not in self._known_assistant_ids():
            raise ProjectServiceError(f"Unknown assistant id: {request.entry_id}.", 422)
        folder = self._assistant_layer_folder_for_id(request.layer_id)
        order = self._read_assistants_order(folder)
        order.ids = [eid for eid in order.ids if eid != request.entry_id]
        if request.entry_id not in order.excluded:
            order.excluded.append(request.entry_id)
        self._write_assistants_order(folder, order)
        return self.list_assistant_entries()

    def _known_assistant_ids(self) -> set[str]:
        return {
            entry_id
            for entry_id, entry in self._build_assistant_index().by_id.items()
            if entry.kind == "assistant"
        }

    def _prepend_to_assistants_order(self, folder: Path, entry_id: str) -> None:
        """Put a newly created assistant on top of **its own layer's** list.

        The issue phrases this as "topmost, therefore the default" (#332,
        ADR-0024). That holds only when the layer is the innermost one: the fold
        puts every descendant layer's `ids` ahead of this one, so an assistant
        created at the machine layer sits below anything a project layer has
        listed. That is most-local-wins working correctly, not a bug — but the
        shorter phrasing is wrong often enough to be worth stating.
        """
        order = self._read_assistants_order(folder)
        order.ids = [entry_id] + [eid for eid in order.ids if eid != entry_id]
        order.excluded = [eid for eid in order.excluded if eid != entry_id]
        self._write_assistants_order(folder, order)

    def _read_assistants_order(self, folder: Path) -> AssistantsOrder:
        """This layer's opinion. A missing file, an unreadable one, or one
        without `excluded` all read as empty lists — pre-1.0, no migration."""
        order_file = folder / ".order.yaml"
        if not order_file.exists():
            return AssistantsOrder()
        try:
            data = self._read_yaml(order_file)
        except ProjectServiceError:
            return AssistantsOrder()
        if not isinstance(data, dict):
            return AssistantsOrder()
        return AssistantsOrder(
            ids=_string_list(data.get("ids")),
            excluded=_string_list(data.get("excluded")),
        )

    def _write_assistants_order(self, folder: Path, order: AssistantsOrder) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self._write_yaml(
            folder / ".order.yaml",
            {"ids": list(order.ids), "excluded": list(order.excluded)},
        )

    def read_assistant_entry(self, entry_id: str) -> AssistantEntry:
        index_entry = self._build_assistant_index().by_id.get(entry_id)
        if index_entry is None or index_entry.kind != "assistant":
            raise ProjectServiceError(f"Assistant {entry_id} does not exist.", 404)
        path = index_entry.path
        front_matter, _body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        raw_entry_type = front_matter.get("entry_type") or "assistant:assistant"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(f"Assistant {node_id} has invalid entry_type; it must be text.", 422)
        return AssistantEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            revision=self._revision(path),
            entry_type=raw_entry_type,
            metadata=self._normalise_metadata(front_matter.get("metadata"), path),
            source_layer_id=index_entry.source_layer_id,
            source_layer_label=index_entry.source_layer_label,
        )

    def create_assistant_entry(self, request: CreateAssistantEntryRequest) -> AssistantEntry:
        target_folder = self._assistant_layer_folder_for_id(request.layer_id)
        self._check_entry_type_kind(request.entry_type, "assistant")
        entry_id = self._new_id("assistant")
        target_folder.mkdir(parents=True, exist_ok=True)
        path = self._filepath_for_new_node(target_folder, request.title)
        self._write_node_entry_file(
            path,
            entry_id,
            request.title,
            request.entry_type,
            {},
            "",
        )
        # Creating an assistant is a statement of intent about the one you just
        # made, so it leads its layer's list rather than landing in the
        # alphabetical tail. See `_prepend_to_assistants_order` for why that is
        # not the same as "it is now the default".
        self._prepend_to_assistants_order(target_folder, entry_id)
        return self.read_assistant_entry(entry_id)

    def save_assistant_entry(self, entry_id: str, request: SaveAssistantEntryRequest) -> AssistantEntry:
        index_entry = self._build_assistant_index().by_id.get(entry_id)
        if index_entry is None or index_entry.kind != "assistant":
            raise ProjectServiceError(f"Assistant {entry_id} does not exist.", 404)
        path = index_entry.path
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Assistant changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "assistant")
        metadata = self._normalise_metadata(request.metadata, path)
        self._write_node_entry_file(path, node_id, request.title, request.entry_type, metadata, "")
        self._maybe_rename_node_file(path, request.title)
        # Register the assistant's tags in the machine-global vocabulary so the
        # `[+]` picker + tag manager surface them (#88).
        from app.services import machine_settings as ms_service

        ms_service.register_assistant_tags(ms_service.tag_names_from_field(metadata.get("tags")))
        return self.read_assistant_entry(node_id)

    def delete_assistant_entry(self, entry_id: str) -> AssistantEntryList:
        index_entry = self._build_assistant_index().by_id.get(entry_id)
        if index_entry is None or index_entry.kind != "assistant":
            raise ProjectServiceError(f"Assistant {entry_id} does not exist.", 404)
        if index_entry.path.exists():
            index_entry.path.unlink()
        return self.list_assistant_entries()

    def _assistant_layer_folder_for_id(self, layer_id: str) -> Path:
        """Resolve a layer_id (from list_metadata_schema_layers, or "") to its
        assistants/ folder. Empty layer_id → machine config dir (the canonical
        per-user roster).

        Reverses the id over the one walk (#329) instead of re-deriving the
        chain. The machine layer stays reachable two ways — "" and its folder
        hash — which the create/reorder endpoints both rely on.
        """
        from app.services import machine_settings as ms_service

        if not layer_id:
            return ms_service.assistants_dir()
        # Deliberately not `_machine_layer_folder()`: that gates on the
        # assistants/ folder already existing, and this path is how the *first*
        # machine assistant gets created.
        machine_dir = ms_service.assistants_dir().parent
        if self._metadata_schema_layer_id(machine_dir) == layer_id:
            return machine_dir / "assistants"
        if self.root_path is not None:
            layer = self.layer_by_id(self.root_path, layer_id)
            if layer is not None:
                return layer.folder / "assistants"
        raise ProjectServiceError(f"Unknown layer id {layer_id}.", 422)

    def _build_assistant_index(self) -> NodeIndex:
        """Build a node index covering just the assistant kind. Works without
        an open project (machine layer only) or with one (full layered walk).
        """
        if self.root_path is not None:
            return self._build_node_index(self.root_path)
        index = NodeIndex()
        self._collect_machine_layer_assistants(
            index, duplicate_relative_to=Path("/")
        )
        # Collection only fills `candidates`; `by_id` is derived (#334). The
        # no-project path builds its index by hand, so it resolves by hand —
        # without this the roster is empty rather than machine-only.
        index.resolve()
        return index

    def resolve_assistant(self, assistant_id: str | None) -> AssistantEntry | None:
        """Look up an assistant by id; with no id, falls back to the **topmost**
        assistant in roster (manual) order. Returns None when nothing matches —
        callers fall back to the legacy default_provider / default_models path.

        The old ``is_default`` flag is retired (ADR-0024): manual order already
        expresses global preference, so "topmost" is the dynamic default, and it
        degrades to exactly the old behaviour when no scope is declared. Any
        prompt-scoped default (topmost *matching* a tag) is resolved on the
        frontend, which then supplies a concrete id here."""
        index = self._build_assistant_index()
        if assistant_id:
            entry = index.by_id.get(assistant_id)
            if entry is None or entry.kind != "assistant":
                return None
            return self._read_assistant_from_index_entry(entry)
        # No id supplied: the topmost assistant in the **sorted roster** — the
        # same order the UI shows (per-layer .order.yaml, then title), so the
        # backend's fallback default and the frontend's dynamic default agree.
        roster = self.list_assistant_entries().entries
        if not roster:
            return None
        entry = index.by_id.get(roster[0].id)
        return self._read_assistant_from_index_entry(entry) if entry else None

    def _read_assistant_from_index_entry(
        self, entry: NodeIndexEntry
    ) -> AssistantEntry | None:
        try:
            front_matter, _body = self._read_markdown_with_front_matter(entry.path, strict=True)
        except ProjectServiceError:
            return None
        raw_entry_type = front_matter.get("entry_type") or "assistant:assistant"
        return AssistantEntry(
            id=entry.id,
            title=str(front_matter.get("title") or entry.id),
            revision=self._revision(entry.path),
            entry_type=raw_entry_type if isinstance(raw_entry_type, str) else "assistant:assistant",
            metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
            source_layer_id=entry.source_layer_id,
            source_layer_label=entry.source_layer_label,
        )
