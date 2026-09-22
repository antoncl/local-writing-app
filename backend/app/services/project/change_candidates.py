"""ADR-0090 §2: the candidate set for a settled change to one lore entry.

Composed onto `ProjectService`; resolves `_build_node_index` (references.py),
`read_snapshot` / `node_snapshot_kind` (scene_snapshots.py), `read_lore_entry`
(lore.py), `build_mutations_index` (lore_mutations.py) and `_search_corpus`
(search_corpus_build.py) via MRO.

Four named routes, each a reason a node might depend on the source: a field
reference in either direction, a mid-scene mutation marker, or a textual
mention in the ADR-0085 search corpus. A node reachable by more than one
route appears once, carrying every route that found it; the set is a list of
`(node, reasons)` and nothing else — no score, no threshold, no cut.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import (
    ChangeCandidate,
    ChangeCandidateReason,
    ChangeCandidateSet,
    LoreEntry,
)
from app.services.ai.name_matcher import compile_name_matcher, scan_name_matcher
from app.services.project.errors import ProjectServiceError
from app.services.project.field_values import same_rendered_value
from app.services.project.node_index import NodeIndex, NodeIndexEntry
from app.services.project.snapshot_diff import NON_FIELD_KEYS

# Tiers, in display order (declared outranks a marker on an untouched field,
# which outranks the noisy textual-mention route).
_TIER_ORDER = {"declared": 0, "marker_untouched": 1, "mention": 2}

# The route a reason arrived by, in display order within one candidate.
_ROUTE_ORDER = {
    "references_source": 0,
    "referenced_by_source": 1,
    "mutates_source": 2,
    "mentions_source": 3,
}


def _is_candidate_node(entry: NodeIndexEntry) -> bool:
    """ADR-0090 §2's node filter: lore entries at any layer, plus the open
    book's own scenes (book-scoped, never inherited). Never tags, chats,
    prompts, plots, research, or the source itself — the caller excludes
    the source by id."""
    return entry.kind == "lore" or entry.entry_type == "manuscript:scene"


def _tier_for(reasons: list[ChangeCandidateReason]) -> str:
    """A marker on a field the diff changed ranks with the declared routes
    (references in either direction); a marker on an untouched field ranks
    below them but above a mere textual mention."""
    if any(r.route in ("references_source", "referenced_by_source") for r in reasons):
        return "declared"
    if any(r.route == "mutates_source" and r.field_changed for r in reasons):
        return "declared"
    if any(r.route == "mutates_source" for r in reasons):
        return "marker_untouched"
    return "mention"


@dataclass
class _RawReason:
    """One reason before ordering. `seq` is this call's own emission order —
    `by_entity` is already position-sorted, so for `mutates_source` reasons
    tied on "changed", it doubles as marker position; for every other route
    it just keeps first-found stable."""

    reason: ChangeCandidateReason
    seq: int

    def sort_key(self) -> tuple[int, int, int]:
        changed_rank = 0
        if self.reason.route == "mutates_source":
            changed_rank = 0 if self.reason.field_changed else 1
        return (_ROUTE_ORDER[self.reason.route], changed_rank, self.seq)


class ChangeCandidatesMixin:
    """Composed onto `ProjectService`. `change_candidates` is the read-only S1
    slice of ADR-0090 — it writes nothing and opens no files beyond what the
    node index, the mutations index and the search corpus already maintain."""

    def change_candidates(
        self, source_id: str, baseline_snapshot_id: str | None = None
    ) -> ChangeCandidateSet:
        index = self._build_node_index()
        source = index.canonical_id(source_id)
        source_entry = index.by_id.get(source)
        if source_entry is None or source_entry.kind != "lore":
            raise ProjectServiceError("Unknown lore entry.", 404)
        source_lore_entry = self.read_lore_entry(source)

        changed_fields, body_changed, whole_entry = self._change_candidate_diff(
            source, baseline_snapshot_id, source_lore_entry
        )

        reasons_by_id: dict[str, list[_RawReason]] = {}
        seq = 0

        def add_reason(node_id: str, reason: ChangeCandidateReason) -> None:
            nonlocal seq
            if node_id == source:
                return
            entry = index.by_id.get(node_id)
            if entry is None or not _is_candidate_node(entry):
                return
            existing = reasons_by_id.setdefault(node_id, [])
            # Two markers on the same field in one scene are two reasons: the
            # marker id is part of the identity, the field alone is not.
            dedupe_key = (reason.route, reason.field_id, reason.marker_id)
            if any(
                (r.reason.route, r.reason.field_id, r.reason.marker_id) == dedupe_key
                for r in existing
            ):
                return
            existing.append(_RawReason(reason=reason, seq=seq))
            seq += 1

        for edge in index.edges_by_dst.get(source, []):
            add_reason(
                edge.src, ChangeCandidateReason(route="references_source", field_id=edge.field_id)
            )

        for edge in index.edges_by_src.get(source, []):
            add_reason(
                index.canonical_id(edge.dst),
                ChangeCandidateReason(route="referenced_by_source", field_id=edge.field_id),
            )

        mindex = self.build_mutations_index()
        for marker in mindex.by_entity.get(source, []):
            field_changed = whole_entry or marker.field in changed_fields
            add_reason(
                marker.scene_id,
                ChangeCandidateReason(
                    route="mutates_source",
                    field_id=marker.field,
                    marker_id=marker.marker_id,
                    field_changed=field_changed,
                ),
            )

        self._add_mention_reasons(index, source, source_lore_entry, add_reason)

        items = [
            self._change_candidate_item(index, node_id, raw_reasons)
            for node_id, raw_reasons in reasons_by_id.items()
        ]
        items.sort(key=lambda item: (_TIER_ORDER[item.tier], item.title.casefold(), item.id))

        return ChangeCandidateSet(
            source_id=source,
            baseline_snapshot_id=baseline_snapshot_id or "",
            changed_fields=changed_fields,
            body_changed=body_changed,
            whole_entry=whole_entry,
            items=items,
        )

    def _change_candidate_diff(
        self, source_id: str, baseline_snapshot_id: str | None, entry: LoreEntry
    ) -> tuple[list[str], bool, bool]:
        """`(changed_fields, body_changed, whole_entry)` for `source_id`
        against `baseline_snapshot_id` — or the "everything counts" answer
        when no baseline was given. A baseline id that does not exist lets
        `read_snapshot`'s 404 propagate."""
        if not baseline_snapshot_id:
            return [], True, True
        kind = self.node_snapshot_kind(source_id)
        detail = self.read_snapshot(source_id, baseline_snapshot_id, kind=kind)
        keys = (set(detail.metadata) | set(entry.metadata)) - NON_FIELD_KEYS
        changed_fields = sorted(
            key
            for key in keys
            if not same_rendered_value(detail.metadata.get(key), entry.metadata.get(key))
        )
        was_body = detail.body.replace("\r\n", "\n")
        now_body = entry.body.replace("\r\n", "\n")
        return changed_fields, was_body != now_body, False

    def _add_mention_reasons(
        self, index: NodeIndex, source: str, entry: LoreEntry, add_reason
    ) -> None:
        """Route 4 (`mentions_source`): a scan of the ADR-0085 search corpus
        for the source's title/aliases, over both scene and lore bodies plus
        their metadata values — scanned separately, never concatenated, so a
        multi-word name cannot match across a value boundary.

        **Echo rule:** a metadata value that, stripped and case-folded,
        exactly equals one of the names is a reference field's own resolved
        title echoing the source, not a mention — skipped."""
        title = entry.title or ""
        names = [title] if title else []
        aliases = entry.metadata.get("aliases")
        if isinstance(aliases, list):
            names.extend(str(alias) for alias in aliases if alias)
        if not names:
            return
        norm_names = {name.strip().casefold() for name in names if name.strip()}
        matcher = compile_name_matcher([(source, names)])
        for node_id, corpus_entry in self._search_corpus().items():
            if node_id == source:
                continue
            candidate_entry = index.by_id.get(node_id)
            if candidate_entry is None or not _is_candidate_node(candidate_entry):
                continue
            if scan_name_matcher(matcher, corpus_entry.body):
                add_reason(node_id, ChangeCandidateReason(route="mentions_source"))
                continue
            for _label, value in corpus_entry.metadata_values:
                if value.strip().casefold() in norm_names:
                    continue
                if scan_name_matcher(matcher, value):
                    add_reason(node_id, ChangeCandidateReason(route="mentions_source"))
                    break

    def _change_candidate_item(
        self, index: NodeIndex, node_id: str, raw_reasons: list[_RawReason]
    ) -> ChangeCandidate:
        entry = index.by_id[node_id]
        ordered = sorted(raw_reasons, key=lambda raw: raw.sort_key())
        reasons = [raw.reason for raw in ordered]
        return ChangeCandidate(
            id=node_id,
            kind=entry.kind,
            entry_type=entry.entry_type,
            title=entry.title or entry.id,
            tier=_tier_for(reasons),
            reasons=reasons,
        )
