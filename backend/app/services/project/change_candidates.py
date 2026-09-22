"""ADR-0090 §2: the candidate set for a settled change to one lore entry.

Composed onto `ProjectService`; resolves `_build_node_index` (references.py),
`read_snapshot` / `node_snapshot_kind` / `newest_snapshot_with_origin`
(scene_snapshots.py), `read_lore_entry` (lore.py), `build_mutations_index`
(lore_mutations.py) and `_search_corpus` (search_corpus_build.py) via MRO.

Four named routes, each a reason a node might depend on the source: a field
reference in either direction, a mid-scene mutation marker, or a textual
mention in the ADR-0085 search corpus. A node reachable by more than one
route appears once, carrying every route that found it; the set is a list of
`(node, reasons)` and nothing else — no score, no threshold, no cut.
"""

from __future__ import annotations

import re
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
from app.services.project.snapshot_witness import unwitnessed_field_ids

# The fields whose story-time records rename the source (ADR-0008): a marker
# on one of these gives the source another name the prose may use.
_NAME_FIELDS = ("title", "aliases")

# A corpus label is the field id, dotted for a group member, `[n]`-suffixed
# for a list item (`_iter_metadata_search_values`, search.py).
_LIST_ITEM_SUFFIX = re.compile(r"\[\d+\]$")

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


# The one place the scene entry type is spelled for ADR-0090: the candidate
# filter here and the confirm step's scope choice (change_propagation.py)
# must agree, or a scene candidate silently becomes a node-scoped item.
SCENE_ENTRY_TYPE = "manuscript:scene"


def _is_candidate_node(entry: NodeIndexEntry) -> bool:
    """ADR-0090 §2's node filter: lore entries at any layer, plus the open
    book's own scenes (book-scoped, never inherited). Never tags, chats,
    prompts, plots, research, or the source itself — the caller excludes
    the source by id."""
    return entry.kind == "lore" or entry.entry_type == SCENE_ENTRY_TYPE


def _corpus_entry_mentions(matcher, corpus_entry, prose_fields: frozenset[str]) -> bool:
    """Whether one corpus entry names the source in its body or in a prose
    field. Each text is scanned on its own, never concatenated. A list item's
    joined member text (`label[n]`) is skipped: its key is a reference already,
    and that is the declared routes' business."""
    if scan_name_matcher(matcher, corpus_entry.body):
        return True
    for label, value in corpus_entry.metadata_values:
        if _LIST_ITEM_SUFFIX.search(label):
            continue
        if label.rsplit(".", 1)[-1] not in prose_fields:
            continue
        if scan_name_matcher(matcher, value):
            return True
    return False


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
        """`baseline_snapshot_id` semantics (ADR-0090 §1): `None` (no query
        param at all) defaults to the newest snapshot a previous propagation
        left on the source, or the whole entry when there is none; `""` (a
        query param given empty, e.g. `?baseline=`) means the whole entry
        explicitly, bypassing the default; any other value is used as given."""
        index = self._build_node_index()
        source = index.canonical_id(source_id)
        source_entry = index.by_id.get(source)
        if source_entry is None or source_entry.kind != "lore":
            raise ProjectServiceError("Unknown lore entry.", 404)
        source_lore_entry = self.read_lore_entry(source)

        resolved_baseline = self._resolve_change_candidate_baseline(source, baseline_snapshot_id)
        changed_fields, body_changed, whole_entry = self._change_candidate_diff(
            source, resolved_baseline
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
        story_names: list[str] = []
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
            if marker.field in _NAME_FIELDS:
                story_names.extend(part.strip() for part in marker.value.split(",") if part.strip())

        self._add_mention_reasons(index, source, source_lore_entry, story_names, add_reason)

        items = [
            self._change_candidate_item(index, node_id, raw_reasons)
            for node_id, raw_reasons in reasons_by_id.items()
        ]
        items.sort(key=lambda item: (_TIER_ORDER[item.tier], item.title.casefold(), item.id))

        return ChangeCandidateSet(
            source_id=source,
            baseline_snapshot_id=resolved_baseline,
            changed_fields=changed_fields,
            body_changed=body_changed,
            whole_entry=whole_entry,
            items=items,
        )

    def _resolve_change_candidate_baseline(
        self, source: str, baseline_snapshot_id: str | None
    ) -> str:
        """`None` defaults to the newest propagation baseline on `source`, or
        `""` (the whole entry) when there is none; any other value — including
        an explicit `""` — is returned unchanged (ADR-0090 §1)."""
        if baseline_snapshot_id is not None:
            return baseline_snapshot_id
        newest = self.newest_snapshot_with_origin(
            source, "propagation", kind=self.node_snapshot_kind(source)
        )
        return newest.id if newest is not None else ""

    def _change_candidate_diff(
        self, source_id: str, baseline_snapshot_id: str | None
    ) -> tuple[list[str], bool, bool]:
        """`(changed_fields, body_changed, whole_entry)` for `source_id`
        against `baseline_snapshot_id` — or the "everything counts" answer
        when no baseline was given. A baseline id that does not exist lets
        `read_snapshot`'s 404 propagate.

        A snapshot photographs ONE layer's file (ADR-0087), so the now-side is
        that same file read back through the same `_snapshot_state`
        normalisation — never `read_lore_entry`, whose folded composite would
        report every book override as a change the owning file never made."""
        if not baseline_snapshot_id:
            return [], True, True
        kind = self.node_snapshot_kind(source_id)
        detail = self.read_snapshot(source_id, baseline_snapshot_id, kind=kind)
        root, node_id, path = self._resolve_snapshot_target(source_id, kind)
        if path is None:
            raise ProjectServiceError("The entry has no file to compare against.", 404)
        front_matter, now_body = self._read_markdown_with_front_matter(path)
        now = self._snapshot_state(front_matter, node_id, self._snapshots_dir(root, node_id))
        now_metadata = now["metadata"]
        keys = (set(detail.metadata) | set(now_metadata)) - NON_FIELD_KEYS
        changed_fields = sorted(
            key
            for key in keys
            if not same_rendered_value(detail.metadata.get(key), now_metadata.get(key))
        )
        was_body = detail.body.replace("\r\n", "\n")
        return changed_fields, was_body != now_body.replace("\r\n", "\n"), False

    def _add_mention_reasons(
        self,
        index: NodeIndex,
        source: str,
        entry: LoreEntry,
        story_names: list[str],
        add_reason,
    ) -> None:
        """Route 4 (`mentions_source`): a scan of the ADR-0085 search corpus
        for the source's names — its title and `aliases`, plus every name a
        story-time marker on those fields gave it (ADR-0008) — over scene and
        lore bodies and their `long_text` fields. Each text is scanned on its
        own, never concatenated, so a multi-word name cannot match across a
        value boundary.

        Only the corpus values whose label is a prose field are scanned
        (`unwitnessed_field_ids`: `long_text`, and lists with a `long_text`
        member); every other value is a scalar or a reference's resolved
        title, which is the declared routes' business. A list item's joined
        member text is skipped too: its key is a reference already."""
        title = entry.title or ""
        names = [title] if title else []
        aliases = entry.metadata.get("aliases")
        if isinstance(aliases, list):
            names.extend(str(alias) for alias in aliases if alias)
        names.extend(story_names)
        names = [name for name in names if name.strip()]
        if not names:
            return
        prose_fields = unwitnessed_field_ids(self.read_metadata_schema())
        matcher = compile_name_matcher([(source, names)])
        for node_id, corpus_entry in self._search_corpus().items():
            if node_id == source:
                continue
            candidate_entry = index.by_id.get(node_id)
            if candidate_entry is None or not _is_candidate_node(candidate_entry):
                continue
            if _corpus_entry_mentions(matcher, corpus_entry, prose_fields):
                add_reason(node_id, ChangeCandidateReason(route="mentions_source"))

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
