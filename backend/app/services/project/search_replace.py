"""`POST /api/search/replace` (ADR-0085 §4): search-and-replace as a
conflict-checked write through each node's own save, never a body-only write
of its own.

Three rules, applied per node (every hit on one node shares its node-level
outcomes; only a metadata hit is refused individually):

1. **Refuse what is not ours.** A hit whose node the corpus does not carry, is
   not owned here (inherited from the built-in Library or an ancestor
   project), targets `field: "metadata"`, or whose kind has no entry in
   `_replace_dispatch_for` below is `not_replaceable`. Inherited lore already
   has its own override/fork paths (`lore.py`); this endpoint must not become
   a third way to write an ancestor's file.
2. **Refuse what moved.** The node's current save revision (read through the
   kind's own read primitive — the exact value its own save checks) must equal
   every body hit's `revision`, and the live body's `[start:end]` must equal
   the text the query matched. Either mismatch marks every body hit on that
   node `stale` and writes nothing.
3. **Write once, through the kind's own save.** All of a node's body hits are
   applied highest-offset-first, then the whole node (read, body substituted)
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

Known edge, not fixed here: `read_prompt_entry`'s revision is the composite
over the owning file plus every override in the chain (`prompts.py:329`),
while `_save_owned_prompt_entry`'s conflict check is the plain `_revision` of
the owning file alone (`prompts.py:530`). They coincide unless a leftover
per-field override targets a prompt this project has since come to own
outright — an unusual, transient state — in which case the save 409s and the
outcome here is `stale`: honest (the file DID move relative to what the
override implies), if not maximally specific.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.models import (
    CardEntry,
    CharacterArcEntry,
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

if TYPE_CHECKING:
    from pathlib import Path

    from app.services.project.node_index import NodeIndex
    from app.services.project.search_corpus import CorpusEntry


@dataclass(frozen=True)
class _ReplaceDispatch:
    """One replaceable kind's `(read, save, to_request)` triple. `read`/`save`
    are the kind's own read/save primitives (bound methods, resolved fresh per
    call so they close over the live `self`); `to_request` maps the read model
    plus the new body to that kind's save-request shape."""

    read: Callable[[str], Any]
    save: Callable[[str, Any], Any]
    to_request: Callable[[Any, str], BaseModel]


def _scene_to_request(read: Scene, new_body: str) -> SaveSceneRequest:
    # Dropped: computed_metadata, source_layer_id, source_layer_label — all
    # read-only/derived, recomputed on read; nothing authored is lost.
    return SaveSceneRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        status=read.status,
        entry_type=read.entry_type,
        metadata=read.metadata,
        dynamic_context=None,
    )


def _lore_to_request(read: LoreEntry, new_body: str) -> SaveLoreEntryRequest:
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
        metadata=read.metadata,
    )


def _prompt_to_request(read: PromptEntry, new_body: str) -> SavePromptEntryRequest:
    # Dropped: computed_metadata, source_layer_id/label, is_library, editable,
    # overridden_fields — all read-only/derived. `inputs`/`offer_on`/
    # `context_strategy` are echoed because the save strips them when absent
    # (entries.py:901-909).
    return SavePromptEntryRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=read.metadata,
        inputs=read.inputs,
        offer_on=read.offer_on,
        context_strategy=read.context_strategy,
    )


def _research_to_request(read: ResearchNote, new_body: str) -> SaveResearchNoteRequest:
    return SaveResearchNoteRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=read.metadata,
    )


def _card_to_request(read: CardEntry, new_body: str) -> SaveCardRequest:
    # Dropped: computed_metadata, source_layer_id/label — read-only/derived.
    return SaveCardRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=read.metadata,
    )


def _plotline_to_request(read: PlotlineEntry, new_body: str) -> SavePlotlineRequest:
    # Dropped: computed_metadata, source_layer_id/label — read-only/derived.
    return SavePlotlineRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=read.metadata,
    )


def _character_arc_to_request(read: CharacterArcEntry, new_body: str) -> SaveCharacterArcRequest:
    # Dropped: computed_metadata, source_layer_id/label — read-only/derived.
    return SaveCharacterArcRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=read.metadata,
    )


def _plot_template_to_request(read: PlotTemplate, new_body: str) -> SavePlotTemplateRequest:
    # Dropped: computed_metadata, source_layer_id/label, is_library, editable —
    # all read-only/derived.
    return SavePlotTemplateRequest(
        title=read.title,
        body=new_body,
        template=read.template,
        metadata=read.metadata,
        base_revision=read.revision,
    )


def _project_to_request(read: ProjectNode, new_body: str) -> SaveProjectNodeRequest:
    # Dropped: computed_metadata — read-only/derived. No node_id argument: the
    # project node is a path-addressed singleton, not id-addressed like every
    # other kind here (`read_project_node`/`save_project_node` take none).
    return SaveProjectNodeRequest(
        title=read.title,
        body=new_body,
        base_revision=read.revision,
        entry_type=read.entry_type,
        metadata=read.metadata,
    )


def _not_replaceable(hit: ReplaceHitRef, reason: str, detail: str | None = None) -> ReplaceOutcome:
    return ReplaceOutcome(
        file_id=hit.file_id, start=hit.start, end=hit.end, status="not_replaceable", reason=reason, detail=detail
    )


def _stale(hit: ReplaceHitRef) -> ReplaceOutcome:
    return ReplaceOutcome(file_id=hit.file_id, start=hit.start, end=hit.end, status="stale", reason="changed")


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

        metadata_hits = [hit for hit in hits if hit.field != "body"]
        body_hits = [hit for hit in hits if hit.field == "body"]
        outcomes = [_not_replaceable(hit, "metadata") for hit in metadata_hits]

        dispatch = self._replace_dispatch_for(entry.kind, entry.entry_type)
        if dispatch is None:
            return outcomes + [_not_replaceable(hit, "kind") for hit in body_hits], False
        if not body_hits:
            return outcomes, False

        body_outcomes, wrote = self._replace_body_hits(file_id, body_hits, replacement, dispatch)
        return outcomes + body_outcomes, wrote

    def _replace_body_hits(
        self,
        file_id: str,
        body_hits: list[ReplaceHitRef],
        replacement: str,
        dispatch: _ReplaceDispatch,
    ) -> tuple[list[ReplaceOutcome], bool]:
        """Rules 2-3 for one node's body hits, once rule 1 has cleared it."""
        # Rule 2: refuse what moved.
        read = dispatch.read(file_id)
        if any(hit.revision != read.revision for hit in body_hits):
            return [_stale(hit) for hit in body_hits], False

        by_start_desc = sorted(body_hits, key=lambda hit: hit.start, reverse=True)
        for prev, nxt in zip(by_start_desc, by_start_desc[1:], strict=False):
            if nxt.end > prev.start:
                return [_not_replaceable(hit, "overlap") for hit in body_hits], False

        # Read bodies equal corpus bodies character for character —
        # `_read_markdown_with_front_matter` yields text-mode `\n` line endings
        # and every writer does `rstrip() + "\n"`, so this is a plain slice
        # comparison with no normalisation of its own.
        if any(read.body[hit.start : hit.end] != hit.text for hit in body_hits):
            return [_stale(hit) for hit in body_hits], False

        # Rule 3: write once, highest offset first.
        new_body = read.body
        for hit in by_start_desc:
            new_body = new_body[: hit.start] + replacement + new_body[hit.end :]

        try:
            saved = dispatch.save(file_id, dispatch.to_request(read, new_body))
        except ProjectServiceError as exc:
            if exc.status_code == 409:
                # The save's own conflict check is the backstop (see the
                # prompt-revision edge in the module docstring).
                return [_stale(hit) for hit in body_hits], False
            # Any other refusal (e.g. a 422 from validate_scene_markdown when
            # the replacement introduces raw HTML or a broken table) is this
            # node's outcome, not an exception — a batch must never orphan an
            # already-written earlier node from its response (rule 3).
            return [_not_replaceable(hit, "rejected", detail=exc.message) for hit in body_hits], False

        return [
            ReplaceOutcome(file_id=file_id, start=hit.start, end=hit.end, status="replaced", revision=saved.revision)
            for hit in body_hits
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
