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
    MetadataSchema,
    ReorderAssistantsRequest,
    SaveAssistantEntryRequest,
    UnlistAssistantRequest,
)
from app.services.ai.profiles import price_oracle
from app.services.ai.providers import policy_permits
from app.services.project.computed_metadata import strip_computed_fields
from app.services.project.errors import ProjectServiceError
from app.services.project.layers import LayerVisitor
from app.services.project.node_index import IndexLayer, NodeIndex, NodeIndexEntry

log = logging.getLogger(__name__)

ASSISTANT_BASE_ENTRY_TYPE = "assistant:assistant"

# The author-set price fields on an assistant (ADR-0083 Amendment 1). Cleared by
# the reset sweep once the oracle prices the model, so a value entered while a
# model was unlisted doesn't linger dormant.
_MANUAL_PRICE_KEYS = ("ai_price_in_usd_per_mtok", "ai_price_out_usd_per_mtok")


def normalize_assistant_entry_type(raw: object) -> str:
    """Heal a stored assistant `entry_type` to its FQN on read (#87).

    Machine assistant files have no import path, and the pre-1.0 "recreate the
    project" reset never reaches them — they live in `%APPDATA%`, independent of
    any project — so a value that drifted from the schema can only be healed at
    read time. The narrow rule (the one `feedback_no_pre_1_0_migrations` carves
    out, because these files *cannot* be recreated): a missing, blank, non-text,
    or **bare-kind** value (`assistant`, written before #77 keyed the type as
    `assistant:assistant`) becomes the kind's FQN default. Anything already
    FQN-shaped (contains a colon) is returned verbatim — so a genuinely unknown
    `lore:whatever` still surfaces for the editor's unresolved-type warning to
    flag, rather than being silently coerced.
    """
    if not isinstance(raw, str) or not raw.strip():
        return ASSISTANT_BASE_ENTRY_TYPE
    value = raw.strip()
    # Bare token (no `kind:` prefix) in the assistant read path means the
    # assistant partition — upgrade to its base FQN.
    return value if ":" in value else ASSISTANT_BASE_ENTRY_TYPE


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
            entry_type = normalize_assistant_entry_type(front_matter.get("entry_type"))
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
        # An excluded assistant is UNLISTED, not gone (#333). #332 filtered it out
        # of the roster entirely, which made `excluded` a visibility mechanism as
        # well as an inheritance one — and left anything so removed with no path
        # back in the UI. Its real job is narrower: countermand an ancestor's
        # listing so the thing is not Active. It still does exactly that, because
        # exclusion keeps the id out of `merged.ids` and therefore out of the
        # Active group; it simply no longer decides whether the id is *shown*.
        # Nothing the app knows about can now become unreachable, and the cost is
        # a few more rows in a group nobody reads day to day.
        positions = {entry_id: idx for idx, entry_id in enumerate(merged.ids)}

        def sort_key(entry: AssistantEntrySummary):
            if entry.id in positions:
                return (0, positions[entry.id], "")
            # Unlisted at every layer: one global alphabetical tail. Pre-#332
            # this tail was per layer, because rank led the key.
            return (1, 0, entry.title.lower())

        entries.sort(key=sort_key)
        # Stamp curation state as COMPUTED metadata, so a view groups/filters on
        # it through the ordinary field machinery (#332/#333). Position in the
        # returned list already encodes the order, but "is this in my roster?"
        # is NOT recoverable from it: the unlisted tail is contiguous with the
        # listed sequence and looks identical. `computed_metadata`, never
        # `metadata` — the latter round-trips to disk through
        # `save_assistant_entry`, and a curation state written into front matter
        # would be contradicted by the ordering files on the next read.
        for entry in entries:
            entry.computed_metadata = self._curation_metadata(entry.id, positions)
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
        # #375: this replaces the layer's `ids` WHOLESALE, and since #333 the pane
        # sends the entire merged *listed* sequence — so one drag makes this layer
        # name every assistant it currently sees, inherited ones included. Omission
        # ("no opinion") is thereby converted into a local opinion in one gesture,
        # and the layer silently stops inheriting later ancestor ordering changes.
        # Accepted + documented for pre-1.0 (single-user app, deliberate); the real
        # fix — sparse per-decision statements ("X before Y") that the fold
        # composes, so a partial opinion stays partial — is tracked in #375 for
        # post-1.0.
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
        # Unconditional, because exclusion no longer decides visibility (see
        # `list_assistant_entries`): it says "not Active here", which is exactly
        # what un-listing means whether the id was inherited or listed locally.
        # An earlier fix made this conditional on some other layer still listing
        # the id — correct in outcome, but it gave one gesture two meanings
        # depending on where the file happened to live, which the user cannot
        # see. Fixing the projection instead let the gesture stay uniform.
        order.ids = [eid for eid in order.ids if eid != request.entry_id]
        if request.entry_id not in order.excluded:
            order.excluded.append(request.entry_id)
        self._write_assistants_order(folder, order)
        return self.list_assistant_entries()

    def _curation_metadata(self, entry_id: str, positions: dict[str, int] | None = None) -> dict[str, object]:
        """The curation pair for one assistant, as computed-field values (#333).

        Shared by the roster and the single-entry read. Splitting them was the
        bug: only the roster stamped, so opening an assistant in the editor drew
        `Curation` and `Priority` as permanently blank locked rows — for a kind
        whose metadata rail *is* its editor, two thirds of the pane's new fields
        were empty. A computed field that some read paths fill and others do not
        is worse than one that does not exist.

        `positions` is passed in by the roster, which already built the index;
        a lone caller pays for one fold.
        """
        if positions is None:
            positions = {eid: idx for idx, eid in enumerate(self.merged_assistant_order().ids)}
        position = positions.get(entry_id)
        return {
            "listed": "listed" if position is not None else "unlisted",
            "position": position,
        }

    def _known_assistant_ids(self) -> set[str]:
        return {
            entry_id
            for entry_id, entry in self._build_assistant_index().by_id.items()
            if entry.kind == "assistant"
        }

    def _prepend_to_assistants_order(self, folder: Path, entry_id: str) -> None:
        """Put an assistant on top of the given layer's list.

        Callers pass the LOCAL layer (#333), which is what makes "topmost,
        therefore the default" (#332, ADR-0024) actually true. The caveat this
        docstring used to carry — that the phrasing only holds at the innermost
        layer — was a description of the bug rather than of the design: the fold
        puts every local id ahead of the inherited remainder, so prepending to
        the layer a file happened to land on left a machine-layer assistant
        below the whole local list. The id here may name an assistant living at
        any layer; that asymmetry is the point (#332's central gesture), and it
        is why nothing needs to be moved or copied to make a shared assistant
        lead one project's roster.
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
        index = self._build_assistant_index()
        index_entry = index.by_id.get(entry_id)
        if index_entry is None or index_entry.kind != "assistant":
            raise ProjectServiceError(f"Assistant {entry_id} does not exist.", 404)
        path = index_entry.path
        front_matter, _body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        entry_type = normalize_assistant_entry_type(front_matter.get("entry_type"))
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        # Read-side healing (#345), under one rule: heal only when the index
        # answering "does this id still exist" covers the same ground the
        # node's references can reach. Two ways it does not, and both end in
        # the frontend persisting the loss on the next save:
        #
        # **No project open.** `_build_assistant_index` is then machine-only,
        # so every reference into any project reads as dangling.
        #
        # **A machine-layer assistant.** It is global — one roster shared by
        # every project — so its references can point into any of them, while
        # the open project's index knows exactly one. Healing it there deletes
        # its links into every other project the user owns.
        #
        # Same rule as #379's purge guard, applied to layer scope instead of
        # parse failures: an id missing from a PARTIAL index is unknown, not
        # gone. Project-layer assistants are in the open chain, so the chain's
        # index is a complete answer for them and they heal normally.
        machine_layer = self.machine_layer()
        on_machine_layer = machine_layer is not None and index_entry.source_layer_id == machine_layer.id
        if self.root_path is not None and not on_machine_layer:
            metadata = self._strip_dangling_references(metadata, self.read_metadata_schema(), index)
        return AssistantEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            revision=self._revision(path),
            entry_type=entry_type,
            metadata=metadata,
            computed_metadata=self._curation_metadata(node_id),
            source_layer_id=index_entry.source_layer_id,
            source_layer_label=index_entry.source_layer_label,
        )

    def _assistant_write_schema(self) -> MetadataSchema:
        """The schema an assistant create/save validates against. Delegates to
        `LayerWalkMixin._machine_write_schema()` (`layers.py`) — was identical
        to `TagNodesMixin._tag_write_schema` before ADR-0082 slice 1's review
        factored the shared body out from under both."""
        return self._machine_write_schema()

    def create_assistant_entry(self, request: CreateAssistantEntryRequest) -> AssistantEntry:
        target_folder = self._assistant_layer_folder_for_id(request.layer_id)
        self._check_entry_type_kind(
            request.entry_type, "assistant", schema=self._assistant_write_schema()
        )
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
        # made, so it leads the roster rather than landing in the alphabetical
        # tail.
        #
        # The opinion goes to the LOCAL layer, not to the layer the FILE landed
        # on (#333). Those are different questions: where a node lives is about
        # ownership and sharing, while "this one comes first" is curation, and
        # #332 makes curation always the open project's opinion about what it
        # inherits. Prepending to the creation folder instead was correct only
        # while the two coincided — once the local layer holds any `ids`, the
        # fold puts every id it names ahead of the inherited remainder, so a
        # machine-layer prepend landed the new assistant BELOW the whole local
        # list and it silently stopped being the default. Writing the opinion
        # locally keeps the file exactly where the user asked for it; nothing is
        # moved or cloned to make it lead.
        self._prepend_to_assistants_order(self._assistant_layer_folder_for_id(None), entry_id)
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
        write_schema = self._assistant_write_schema()
        self._check_entry_type_kind(request.entry_type, "assistant", schema=write_schema)
        metadata = self._normalise_metadata(request.metadata, path)
        # Drop DERIVED keys before they reach disk (#333). The roster stamps
        # `listed`/`position` into `computed_metadata`; a client that spreads
        # that back into `metadata` on save would otherwise freeze a curation
        # state into front matter that the `.order.yaml` fold contradicts on the
        # very next read. Scene and lore saves are already protected — they
        # validate and 422 — but the assistant save path does not validate, so
        # the guard belongs here.
        #
        # Computed keys ONLY, never the full unknown/not-allowed strip. An
        # assistant lives at the machine layer and is shared by every project,
        # while `read_metadata_schema()` is the schema of whichever project
        # happens to be OPEN. Filtering against it would delete any field a
        # *different* project's schema layer declares — open project B, rename
        # an assistant, and a field project A relies on is gone from disk for
        # both. That is the regression this narrower form exists to avoid.
        metadata = strip_computed_fields(metadata, write_schema)
        self._write_node_entry_file(path, node_id, request.title, request.entry_type, metadata, "")
        self._maybe_rename_node_file(path, request.title)
        # ADR-0082 §2: `assistant_tags` is now an `entity_ref_list` of tag-node
        # ids, not free-text names — `register_assistant_tags` expects names, so
        # registering ids there would corrupt the legacy (dead, machine-global)
        # registry. The vocabulary is the `tag:assistant_tag` nodes themselves;
        # nothing registers them on save (`create_missing` mints on the picker's
        # own create path instead).
        return self.read_assistant_entry(node_id)

    def reset_stale_manual_prices(self) -> int:
        """Clear the author-set price fields (ADR-0083 Amendment 1) from any
        assistant whose model the price oracle now prices — a value entered while
        the model was unlisted, made redundant once OpenRouter lists it. Returns
        the count cleared.

        Fill semantics mean the cost was already correct (the oracle wins); this
        only tidies the dormant field. Call after `price_oracle.refresh()` so the
        index is current.
        """
        cleared = 0
        for summary in self.list_assistant_entries().entries:
            meta = summary.metadata or {}
            model = meta.get("ai_model")
            has_manual = any(meta.get(key) not in (None, "") for key in _MANUAL_PRICE_KEYS)
            if not (has_manual and isinstance(model, str) and model):
                continue
            if price_oracle.price_for(model) is None:
                continue  # oracle still can't price it — keep the manual fill
            entry = self.read_assistant_entry(summary.id)
            new_meta = {k: v for k, v in (entry.metadata or {}).items() if k not in _MANUAL_PRICE_KEYS}
            if new_meta == (entry.metadata or {}):
                continue
            self.save_assistant_entry(
                summary.id,
                SaveAssistantEntryRequest(
                    title=entry.title,
                    entry_type=entry.entry_type,
                    base_revision=entry.revision,
                    metadata=new_meta,
                ),
            )
            cleared += 1
        return cleared

    def delete_assistant_entry(self, entry_id: str) -> AssistantEntryList:
        index_entry = self._build_assistant_index().by_id.get(entry_id)
        if index_entry is None or index_entry.kind != "assistant":
            raise ProjectServiceError(f"Assistant {entry_id} does not exist.", 404)
        self._delete_node_file(index_entry.path)  # unlink + un-shadow the memo (#392)
        return self.list_assistant_entries()

    def _assistant_layer_folder_for_id(self, layer_id: str | None) -> Path:
        """Resolve a layer_id (from list_metadata_schema_layers, "", or None) to
        its assistants/ folder. Curation is always an opinion the current book
        holds about what it inherits, so a caller that is simply curating says
        nothing about layers at all — #318's "no layer arithmetic in the
        frontend". The layer-id arithmetic itself is `_layer_folder_for_id`
        (`layers.py`), shared with `TagNodesMixin` (ADR-0082 slice 1) — see its
        docstring for the three-case contract.
        """
        return self._layer_folder_for_id(layer_id, "assistants")

    def _build_assistant_index(self) -> NodeIndex:
        """Build a node index covering both machine-layer families — assistants
        AND tags (`MACHINE_LAYER_FAMILIES`, ADR-0082 slice 1). Works without an
        open project (machine layer only) or with one (full layered walk).
        Shared by `TagNodesMixin` (`_tag_index_entry`), which filters to
        `kind == "tag"` the same way this mixin filters to `kind == "assistant"`
        — one index build, not two byte-identical ones.
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
        # Since #333 the roster carries un-listed entries too — shown so nothing
        # the app knows about becomes unreachable — so "topmost row" stopped
        # meaning "topmost of my roster". Un-listing an assistant must never be
        # a way to make the app start *using* it.
        #
        # The first LISTED id, and nothing else — no scan of the wider roster to
        # find something usable. `create_assistant_entry` prepends every new
        # assistant to its layer's `.order.yaml`, so anything made through the
        # app is listed from birth and this is never empty in practice; an
        # unlisted roster means the author emptied it deliberately, and the right
        # answer then is no default rather than a guess.
        #
        # An earlier version fell back to the topmost row when nothing was
        # listed. That was written for an install with no `.order.yaml`, a state
        # only the hand-built test fixtures below are ever in — they write
        # assistant files directly instead of going through create. Keeping the
        # fallback would have meant reaching past the author's own list to pick
        # something they never chose.
        #
        # ADR-0073 S2: the topmost listed id is skipped when its provider isn't
        # permitted under the project's resolved policy — e.g. a cloud assistant
        # left at the top of the roster after the policy tightened to
        # local-only. With NO project open, `ai_policy()` raises (the machine-
        # only roster path) and there is no project policy to enforce, so the
        # skip does not apply and the topmost resolves exactly as it did pre-S2.
        try:
            policy = self.ai_policy()
        except ProjectServiceError:
            policy = None
        merged = self.merged_assistant_order()
        for entry_id in merged.ids:
            index_entry = index.by_id.get(entry_id)
            if index_entry is None:
                continue
            entry = self._read_assistant_from_index_entry(index_entry)
            if entry is None:
                continue
            # A listed entry with no provider configured yet (a fresh
            # `create_assistant_entry` scaffold) has nothing to judge against
            # the policy, so it is never skipped on that basis alone — only a
            # SET, forbidden provider under a real policy disqualifies a candidate.
            provider = entry.metadata.get("ai_provider")
            if (
                policy is not None
                and isinstance(provider, str)
                and provider
                and not policy_permits(policy, provider)
            ):
                continue
            return entry
        return None

    def _read_assistant_from_index_entry(
        self, entry: NodeIndexEntry
    ) -> AssistantEntry | None:
        try:
            front_matter, _body = self._read_markdown_with_front_matter(entry.path, strict=True)
        except ProjectServiceError:
            return None
        return AssistantEntry(
            id=entry.id,
            title=str(front_matter.get("title") or entry.id),
            revision=self._revision(entry.path),
            entry_type=normalize_assistant_entry_type(front_matter.get("entry_type")),
            metadata=self._normalise_metadata(front_matter.get("metadata"), entry.path),
            source_layer_id=entry.source_layer_id,
            source_layer_label=entry.source_layer_label,
        )
