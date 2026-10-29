"""`POST /api/search/replace` (ADR-0085 §4): search-and-replace as a
conflict-checked write through each node's own save, never a body-only write
of its own.

A writable hit is a body hit or a **text-slot** hit — a metadata hit carrying
a `metadata_path` into stored free text (ADR-0085 Amendment 2,
`metadata_text.py`); its offsets index that string instead of the body. Three
rules, applied per node (every writable hit on one node shares its node-level
outcomes; a find-only metadata hit and a written card's body hit are refused
individually):

1. **Refuse what is not ours.** A hit whose node the corpus does not carry, is
   not owned here (inherited from the built-in Library or an ancestor
   project), is a find-only metadata hit (a title, a resolved reference, a
   vocabulary value — no `metadata_path`), or whose kind has no entry in
   `_replace_dispatch_for` below is `not_replaceable`. Inherited lore already
   has its own override/fork paths (`lore.py`); this endpoint must not become
   a third way to write an ancestor's file.
2. **Refuse what moved.** The node's current save revision (read through the
   kind's own read primitive — the exact value its own save checks) must equal
   every writable hit's `revision`, and the live string's `[start:end]` (the
   body, or the slot the read still holds at that path) must equal the text
   the query matched. Either mismatch marks every writable hit on that node
   `stale` and writes nothing.
3. **Write once, through the kind's own save.** All of a node's writable hits
   are applied highest-offset-first within their string, then the whole node
   (read, body and slots substituted)
   goes through the SAME save the editor uses, with `base_revision` set to the
   revision just verified. Revision, node index, and search-corpus maintenance
   then happen exactly as for any other save (`_atomic_write` / the write
   funnel) — nothing here writes a file directly. The save's own refusal
   (conflict or validation) becomes that node's outcome — `stale` on a 409,
   `not_replaceable/rejected` with the save's message as `detail` on anything
   else — rather than propagating out of `replace()`; nothing here lets a
   batch orphan an already-written earlier node from its response.

Rejected alternative: a body-only save endpoint. The save request models
(`SaveSceneRequest`, `SaveLoreEntryRequest`, …) all require the whole node, so
a body-only primitive would either duplicate every kind's save validation
(metadata healing, override routing, schema checks) or bypass it — either way
a second, thinner write path alongside the one every editor already uses. The
dispatch table below IS the mapping ADR-0085 §4 names: one `(read, save,
to_request)` triple per replaceable kind, mirroring `_SAVE_NODE_DISPATCH`
(`node_ops.py`) plus the plot family it does not cover.

Every kind's read and save agree on what a revision covers — for lore and
prompts that is the composite over the owning file plus every override in the
chain targeting it, on the owned path as well as the override path (#1850) —
so a hit's revision from the corpus is exactly what the save compares against.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.models import (
    CardEntry,
    CharacterArcEntry,
    DeckEntry,
    LoreEntry,
    PlotlineEntry,
    PlotTemplate,
    ProjectNode,
    PromptEntry,
    ReplaceHitRef,
    ReplaceOutcome,
    ReplaceRequest,
    ReplaceResponse,
    ResearchNote,
    SaveCardRequest,
    SaveCharacterArcRequest,
    SaveDeckRequest,
    SaveLoreEntryRequest,
    SavePlotlineRequest,
    SavePlotTemplateRequest,
    SaveProjectNodeRequest,
    SavePromptEntryRequest,
    SaveResearchNoteRequest,
    SaveSceneRequest,
    Scene,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.metadata_text import (
    MetadataPath,
    iter_text_slots,
    with_text_slots,
)

if TYPE_CHECKING:
    from pathlib import Path

    from app.services.project.node_index import NodeIndex
    from app.services.project.search_corpus import CorpusEntry


@dataclass(frozen=True)
class _ReplaceDispatch:
    """One replaceable kind's `(read, save, to_request)` triple. `read`/`save`
    are the kind's own read/save primitives (bound methods, resolved fresh per
    call so they close over the live `self`); `to_request` maps the read model
    plus the new body and metadata to that kind's save-request shape."""

    read: Callable[[str], Any]
    save: Callable[[str, Any], Any]
    to_request: Callable[[Any, str, dict[str, Any]], BaseModel]


def _scene_to_request(read: Scene, new_body: str, metadata: dict[str, Any]) -> SaveSceneRequest:
    # Dropped: computed_metadata, source_layer_id, source_layer_label — all
    # read-only/derived, recomputed on read; nothing authored is lost.
    return SaveSceneRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        status=read.status,
        entry_type=read.entry_type,
        metadata=metadata,
        dynamic_context=None,
    )


def _lore_to_request(read: LoreEntry, new_body: str, metadata: dict[str, Any]) -> SaveLoreEntryRequest:
    # Dropped: computed_metadata, source_layer_id/label, forked_from,
    # overridden_fields — all read-only/derived. No `authoring_layer_id`: the
    # node already passed the owned-here check, so the save's own "owned
    # locally" branch (winner.source_layer_id == open layer) applies without it
    # (lore.py:205-214).
    return SaveLoreEntryRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=metadata,
    )


def _prompt_to_request(read: PromptEntry, new_body: str, metadata: dict[str, Any]) -> SavePromptEntryRequest:
    # Dropped: computed_metadata, source_layer_id/label, is_library, editable,
    # overridden_fields — all read-only/derived. `inputs`/`offer_on`/
    # `context_strategy` are echoed because the save strips them when absent
    # (entries.py:901-909).
    return SavePromptEntryRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=metadata,
        inputs=read.inputs,
        offer_on=read.offer_on,
        context_strategy=read.context_strategy,
    )


def _research_to_request(read: ResearchNote, new_body: str, metadata: dict[str, Any]) -> SaveResearchNoteRequest:
    return SaveResearchNoteRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=metadata,
    )


def _card_to_request(read: CardEntry, new_body: str, metadata: dict[str, Any]) -> SaveCardRequest:
    # Dropped: computed_metadata, source_layer_id/label — read-only/derived.
    return SaveCardRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=metadata,
    )


def _plotline_to_request(read: PlotlineEntry, new_body: str, metadata: dict[str, Any]) -> SavePlotlineRequest:
    # Dropped: computed_metadata, source_layer_id/label — read-only/derived.
    return SavePlotlineRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=metadata,
    )


def _character_arc_to_request(read: CharacterArcEntry, new_body: str, metadata: dict[str, Any]) -> SaveCharacterArcRequest:
    # Dropped: computed_metadata, source_layer_id/label — read-only/derived.
    return SaveCharacterArcRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=metadata,
    )


def _deck_to_request(read: DeckEntry, new_body: str, metadata: dict[str, Any]) -> SaveDeckRequest:
    # Dropped: computed_metadata, source_layer_id/label — read-only/derived.
    return SaveDeckRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=metadata,
    )


def _plot_template_to_request(read: PlotTemplate, new_body: str, metadata: dict[str, Any]) -> SavePlotTemplateRequest:
    # Dropped: computed_metadata, source_layer_id/label, is_library, editable —
    # all read-only/derived.
    return SavePlotTemplateRequest(
        title=read.title,
        body=new_body,
        template=read.template,
        metadata=metadata,
        base_revision=read.revision,
    )


def _project_to_request(read: ProjectNode, new_body: str, metadata: dict[str, Any]) -> SaveProjectNodeRequest:
    # Dropped: computed_metadata — read-only/derived. No node_id argument: the
    # project node is a path-addressed singleton, not id-addressed like every
    # other kind here (`read_project_node`/`save_project_node` take none).
    return SaveProjectNodeRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=metadata,
    )


def _not_replaceable(hit: ReplaceHitRef, reason: str, detail: str | None = None) -> ReplaceOutcome:
    return ReplaceOutcome(
        file_id=hit.file_id,
        start=hit.start,
        end=hit.end,
        metadata_path=hit.metadata_path,
        status="not_replaceable",
        reason=reason,
        detail=detail,
    )


def _stale(hit: ReplaceHitRef) -> ReplaceOutcome:
    return ReplaceOutcome(
        file_id=hit.file_id,
        start=hit.start,
        end=hit.end,
        metadata_path=hit.metadata_path,
        status="stale",
        reason="changed",
    )


def _target(hit: ReplaceHitRef) -> MetadataPath | None:
    """Which string a writable hit's offsets index: None for the body, the
    slot's path for a text-slot hit (Amendment 2)."""
    return tuple(hit.metadata_path) if hit.metadata_path else None


def _overlaps(hits: list[ReplaceHitRef]) -> bool:
    """Whether two hits on the same string overlap — offsets only compare
    within one target."""
    by_target: dict[MetadataPath | None, list[ReplaceHitRef]] = {}
    for hit in hits:
        by_target.setdefault(_target(hit), []).append(hit)
    for group in by_target.values():
        ordered = sorted(group, key=lambda hit: hit.start, reverse=True)
        if any(nxt.end > prev.start for prev, nxt in zip(ordered, ordered[1:], strict=False)):
            return True
    return False


class SearchReplaceMixin:
    def replace(self, request: ReplaceRequest) -> ReplaceResponse:
        corpus = self._search_corpus()
        root = self._require_project().resolve()
        index = self._build_node_index(root)

        # Group by node, preserving first-seen order — a node's hits need not
        # be contiguous in the request, and outcomes come back per hit.
        by_file: dict[str, list[ReplaceHitRef]] = {}
        for hit in request.hits:
            by_file.setdefault(hit.file_id, []).append(hit)

        outcomes: list[ReplaceOutcome] = []
        replaced_nodes = 0
        for file_id, hits in by_file.items():
            node_outcomes, wrote = self._replace_node(file_id, hits, request.replacement, corpus, index, root)
            outcomes.extend(node_outcomes)
            if wrote:
                replaced_nodes += 1
        return ReplaceResponse(outcomes=outcomes, replaced_nodes=replaced_nodes)

    def _replace_node(
        self,
        file_id: str,
        hits: list[ReplaceHitRef],
        replacement: str,
        corpus: dict[str, CorpusEntry],
        index: NodeIndex,
        root: Path,
    ) -> tuple[list[ReplaceOutcome], bool]:
        """Rules 1-3 for one node's hits. Returns the outcomes for every hit
        passed in, plus whether a write actually happened (for the caller's
        `replaced_nodes` tally)."""
        entry = corpus.get(file_id)
        if entry is None:
            return [_not_replaceable(hit, "unknown") for hit in hits], False

        winner = index.by_id.get(file_id)
        if not entry.owned or winner is None or not self._node_is_owned_here(winner, root):
            return [_not_replaceable(hit, "inherited") for hit in hits], False

        # A metadata hit with no slot path matched a title, a resolved reference
        # title, or a vocabulary value — find-only (Amendment 2 keeps them so).
        find_only = [hit for hit in hits if hit.field != "body" and not hit.metadata_path]
        body_hits = [hit for hit in hits if hit.field == "body"]
        slot_hits = [hit for hit in hits if hit.field != "body" and hit.metadata_path]
        outcomes = [_not_replaceable(hit, "metadata") for hit in find_only]

        dispatch = self._replace_dispatch_for(entry.kind, entry.entry_type)
        if dispatch is None:
            return outcomes + [_not_replaceable(hit, "kind") for hit in body_hits + slot_hits], False
        # A written card's own body is frozen — the scene's summary is what it shows
        # (ADR-0097 §3) — so there is nothing there to replace. Its metadata (the
        # card's own follow-ups, say) is still the card's own.
        if body_hits and entry.entry_type == "plot:card" and self.read_card(file_id).metadata.get("scene"):
            outcomes += [_not_replaceable(hit, "written") for hit in body_hits]
            body_hits = []
        if not body_hits and not slot_hits:
            return outcomes, False

        written, wrote = self._replace_hits(file_id, body_hits + slot_hits, replacement, dispatch)
        return outcomes + written, wrote

    def _replace_hits(
        self,
        file_id: str,
        hits: list[ReplaceHitRef],
        replacement: str,
        dispatch: _ReplaceDispatch,
    ) -> tuple[list[ReplaceOutcome], bool]:
        """Rules 2-3 for one node's writable hits — body and text-slot alike —
        once rule 1 has cleared it."""
        # Rule 2: refuse what moved.
        read = dispatch.read(file_id)
        if any(hit.revision != read.revision for hit in hits):
            return [_stale(hit) for hit in hits], False
        if _overlaps(hits):
            return [_not_replaceable(hit, "overlap") for hit in hits], False

        # Read bodies equal corpus bodies character for character —
        # `_read_markdown_with_front_matter` yields text-mode `\n` line endings
        # and every writer does `rstrip() + "\n"` — and a slot is the stored
        # string itself, so both are plain slice comparisons. A slot the read
        # no longer has (an item removed) is a move like any other.
        strings: dict[MetadataPath | None, str] = {None: read.body}
        strings.update(iter_text_slots(read.metadata, self.read_metadata_schema()))
        if any(_target(hit) not in strings or strings[_target(hit)][hit.start : hit.end] != hit.text for hit in hits):
            return [_stale(hit) for hit in hits], False

        # Rule 3: write once, highest offset first within each string.
        for hit in sorted(hits, key=lambda hit: hit.start, reverse=True):
            target = _target(hit)
            strings[target] = strings[target][: hit.start] + replacement + strings[target][hit.end :]
        touched = {path for hit in hits if (path := _target(hit)) is not None}
        new_metadata = with_text_slots(read.metadata, {path: strings[path] for path in touched})

        try:
            saved = dispatch.save(file_id, dispatch.to_request(read, strings[None], new_metadata))
        except ProjectServiceError as exc:
            if exc.status_code == 409:
                # The save's own conflict check is the backstop: it compares the
                # same revision the read handed out (module docstring), so a 409
                # here is a real move on disk between the read above and the save.
                return [_stale(hit) for hit in hits], False
            # Any other refusal (e.g. a 422 from validate_scene_markdown when
            # the replacement introduces raw HTML or a broken table) is this
            # node's outcome, not an exception — a batch must never orphan an
            # already-written earlier node from its response (rule 3).
            return [_not_replaceable(hit, "rejected", detail=exc.message) for hit in hits], False

        return [
            ReplaceOutcome(
                file_id=file_id,
                start=hit.start,
                end=hit.end,
                metadata_path=hit.metadata_path,
                status="replaced",
                revision=saved.revision,
            )
            for hit in hits
        ], True

    def _replace_dispatch_for(self, kind: str, entry_type: str) -> _ReplaceDispatch | None:
        """The mapping table ADR-0085 §4 names — one triple per replaceable
        kind, mirroring `_SAVE_NODE_DISPATCH` (`node_ops.py:45`) plus the plot
        family it does not cover. `assistant`, `view`, `tag`, `chat`, and
        `mutation_set` are absent: none of them go through this endpoint
        (chats have no editable body here; tags/assistants/views are find-only
        per the ADR's table). `project` IS dispatched — its `project.md` body
        is corpus-indexed like any other prose-bodied node, and
        `read_project_node`/`save_project_node` are a real `base_revision`
        save; the wrappers below just drop the unused node-id argument since
        the project node is a path-addressed singleton, not id-addressed."""
        if kind == "plot":
            plot_table: dict[str, _ReplaceDispatch] = {
                "plot:card": _ReplaceDispatch(self.read_card, self.save_card, _card_to_request),
                "plot:plotline": _ReplaceDispatch(self.read_plotline, self.save_plotline, _plotline_to_request),
                "plot:character_arc": _ReplaceDispatch(
                    self.read_character_arc, self.save_character_arc, _character_arc_to_request
                ),
                "plot:deck": _ReplaceDispatch(self.read_deck, self.save_deck, _deck_to_request),
                "plot:template": _ReplaceDispatch(
                    self.read_plot_template, self.save_plot_template, _plot_template_to_request
                ),
            }
            return plot_table.get(entry_type)
        table: dict[str, _ReplaceDispatch] = {
            "manuscript": _ReplaceDispatch(self.read_scene, self.save_scene, _scene_to_request),
            "lore": _ReplaceDispatch(self.read_lore_entry, self.save_lore_entry, _lore_to_request),
            "prompt": _ReplaceDispatch(self.read_prompt_entry, self.save_prompt_entry, _prompt_to_request),
            "research": _ReplaceDispatch(self.read_research_note, self.save_research_note, _research_to_request),
            "project": _ReplaceDispatch(
                lambda _file_id: self.read_project_node(),
                lambda _file_id, req: self.save_project_node(req),
                _project_to_request,
            ),
        }
        return table.get(kind)
