"""ADR-0090 §2 / ADR-0091 §2: the candidate set for a settled change to one
lore entry.

Composed onto `ProjectService`; resolves `_build_node_index` (references.py),
`read_snapshot` / `node_snapshot_kind` / `newest_snapshot_with_origin` /
`newest_snapshot_at_or_before` (scene_snapshots.py), `read_lore_entry` /
`list_lore_entries` (lore.py), `build_mutations_index` (lore_mutations.py)
and `_search_corpus` (search_corpus_build.py) via MRO.

Five named routes, each a reason a node might depend on the source: a field
reference in either direction, a mid-scene mutation marker, or a textual
mention in the ADR-0085 search corpus in either direction — the candidate's
prose naming the source (`mentions_source`) or the source's own prose naming
the candidate (`mentioned_by_source`, ADR-0091 S1). A node reachable by more
than one route appears once, carrying every route that found it; the set is
a list of `(node, reasons)` and nothing else — no score, no threshold, no
cut.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.models import (
    ChangeCandidate,
    ChangeCandidateLayer,
    ChangeCandidateReason,
    ChangeCandidateSet,
    LoreEntry,
    MutationSetRow,
    Snapshot,
)
from app.services.ai.name_matcher import (
    CompiledNameMatcher,
    compile_name_matcher,
    normalise_name,
    scan_name_matcher,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.field_values import same_rendered_value
from app.services.project.node_index import IndexLayer, NodeIndex, NodeIndexEntry
from app.services.project.search_corpus import CorpusEntry
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

# The route a reason arrived by, in display order within one candidate:
# declared, marker, mention in, mention out. `TodoSource.reason` records the
# first reason on a candidate (§3), so this order is load-bearing — never
# reorder the existing entries, only ever append.
_ROUTE_ORDER = {
    "references_source": 0,
    "referenced_by_source": 1,
    "mutates_source": 2,
    "mentions_source": 3,
    "mentioned_by_source": 4,
}


# The one place the scene entry type is spelled for ADR-0090: the candidate
# filter here and the confirm step's scope choice (change_propagation.py)
# must agree, or a scene candidate silently becomes a node-scoped item.
SCENE_ENTRY_TYPE = "manuscript:scene"

# Amendment 4 §7: a `title` or `body` row never appears in `changed_fields` —
# title because the owning lane already excludes it (`NON_FIELD_KEYS`,
# snapshot_diff.py) and a lane must not add a signal the owning lane lacks;
# body because a changed body row is folded into `body_changed` instead,
# exactly as the owning file's body is.
_NON_FIELD_ROW_KEYS = frozenset({"title", "body"})


def _is_candidate_node(entry: NodeIndexEntry) -> bool:
    """ADR-0090 §2's node filter: lore entries at any layer, plus the open
    book's own scenes (book-scoped, never inherited). Never tags, chats,
    prompts, plots, research, or the source itself — the caller excludes
    the source by id."""
    return entry.kind == "lore" or entry.entry_type == SCENE_ENTRY_TYPE


def _corpus_entry_mention_ids(
    matcher: CompiledNameMatcher, corpus_entry: CorpusEntry, prose_fields: frozenset[str]
) -> set[str]:
    """The matcher's hit ids over one corpus entry's body and prose fields —
    the echo rule shared by BOTH mention directions (ADR-0091 §2): only
    prose is scanned, so a reference value the corpus carries as a resolved
    title (Marek's `posting` reading "Watch Barracks") is never a textual
    mention. Each text is scanned on its own, never concatenated. A list
    item's joined member text (`label[n]`) is skipped: its key is a
    reference already, and that is the declared routes' business.

    `scan_name_matcher` itself masks emphasis underscores (#2142) before
    scanning, so `_Marek Vell_` (markdown italics) is found here too, without
    this function doing anything extra."""
    ids: set[str] = set()
    for hit in scan_name_matcher(matcher, corpus_entry.body):
        ids.add(hit.entry_id)
    for label, value in corpus_entry.metadata_values:
        if _LIST_ITEM_SUFFIX.search(label):
            continue
        if label.rsplit(".", 1)[-1] not in prose_fields:
            continue
        for hit in scan_name_matcher(matcher, value):
            ids.add(hit.entry_id)
    return ids


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


@dataclass(frozen=True)
class ComposingFile:
    """One file that composes the source at the open layer (ADR-0090
    Amendment 3): the owning layer's file, or an override delta strictly
    below it and at or above the open layer. `_composing_files` returns the
    owning file first, then deltas in ascending rank."""

    layer_id: str
    layer_label: str
    layer_rank: int
    is_override: bool
    path: Path


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
        changed_fields, body_changed, whole_entry, layers = self._change_candidate_diff(
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

        # Computed once and shared by both mention directions (ADR-0091 S1):
        # the prose-field id set and the search corpus itself. Inbound first,
        # outbound second, so `seq` — and so the first-reason order
        # `TodoSource.reason` records — keeps the shipped declared / marker /
        # mention-in / mention-out sequence.
        prose_fields = unwitnessed_field_ids(self.read_metadata_schema())
        corpus = self._search_corpus()
        self._add_mention_reasons(
            index, source, source_lore_entry, story_names, prose_fields, corpus, add_reason
        )
        self._add_outbound_mention_reasons(index, source, prose_fields, corpus, add_reason)

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
            layers=layers,
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

    def _composing_layer_bounds(self, source: str) -> tuple[int, int, dict[str, IndexLayer]]:
        """`(owner rank, open-layer rank, every layer by id)` for `source` —
        the range an override delta must fall in to compose the source at the
        open layer (`owner < rank <= open`).

        `overrides_by_target`'s `layer_rank` is stamped from the FULL cold
        walk (`_resolve_index_cold`: `include_machine=True,
        include_library=True`) — `layer_by_id`'s default walk omits both,
        which renumbers every rank and breaks the comparison. Ranks are
        therefore looked up from the same full walk."""
        index = self._build_node_index()
        owner = index.by_id[source]
        root = self._require_project()
        full_layers = {
            layer.id: layer
            for layer in self.collect_layers(root, include_machine=True, include_library=True)
        }
        owner_layer = full_layers.get(owner.source_layer_id)
        owner_rank = owner_layer.rank if owner_layer is not None else 0
        open_layer = full_layers.get(self._metadata_schema_layer_id(root))
        open_rank = open_layer.rank if open_layer is not None else owner_rank
        return owner_rank, open_rank, full_layers

    def _removed_delta_layers(
        self, source_id: str, kind: str, composing: list[ComposingFile], since: Snapshot
    ) -> tuple[list[ChangeCandidateLayer], bool]:
        """Amendment 3 §1–2's mirror case: a delta that composed the source at
        the last propagation and has since been REMOVED is a change too — its
        fields fell back to the layer above. Such a lane has a propagation
        baseline but no delta file now, so `_composing_files` (which reads the
        index's existing deltas) cannot see it; walk the layers in range
        instead and read the baseline's rows as the fields that changed.

        `since` (ADR-0091 §1) resolves each lane's baseline as the newest
        snapshot, of any origin, captured at or before the owning baseline's
        time — never "the newest propagation snapshot regardless" (#2131).
        No baseline at or before `since` means the lane did not exist at the
        since and does not now: not a change, so it is skipped.

        Returns `(layers, body_changed)`: a removed lane whose baseline rows
        carried a `body` row falls back to the layer above losing that body
        override, so it sets `body_changed` the same as an edit would
        (Amendment 4 §7) — never as a field in `changed_fields`."""
        index = self._build_node_index()
        source = index.canonical_id(source_id)
        owner_rank, open_rank, full_layers = self._composing_layer_bounds(source)
        present = {file.layer_id for file in composing}
        removed: list[ChangeCandidateLayer] = []
        body_changed = False
        for layer in sorted(full_layers.values(), key=lambda layer: layer.rank):
            if layer.id in present or not (owner_rank < layer.rank <= open_rank):
                continue
            baseline = self.newest_snapshot_at_or_before(
                source_id, since.captured_at, kind=kind, layer_id=layer.id
            )
            if baseline is None:
                continue
            root, node_id, _ = self._resolve_snapshot_target(source_id, kind, layer_id=layer.id)
            # `_read_front_matter_only`, never `_read_markdown_with_front_matter`:
            # the latter locates the closing `---` by substring split, which
            # swallows a literal `body` row's own trailing newline when that
            # row is last (the common case) — corrupting the very value this
            # loop compares. `_read_front_matter_only` reads line-by-line up
            # to the delimiter line and never touches the content bytes.
            baseline_front_matter = self._read_front_matter_only(
                self._snapshots_dir(root, node_id) / f"{baseline.id}.md", strict=True
            )
            rows = self._parse_override_rows(baseline_front_matter.get("rows"))
            if any(row.field == "body" for row in rows):
                body_changed = True
            removed.append(
                ChangeCandidateLayer(
                    layer_id=layer.id,
                    layer_label=layer.label,
                    is_override=True,
                    baseline_snapshot_id=baseline.id,
                    changed_fields=sorted(
                        {row.field.split(".", 1)[0] for row in rows if row.field not in _NON_FIELD_ROW_KEYS}
                    ),
                    whole=False,
                )
            )
        return removed, body_changed

    def _composing_files(self, source_id: str) -> list[ComposingFile]:
        """ADR-0090 Amendment 3: every file that composes `source_id` at the
        open layer — the owning layer's file first, then each override delta
        strictly below the owner and at or above the open layer, ascending by
        rank. A layer with no delta contributes nothing (the composing set is
        never invented)."""
        index = self._build_node_index()
        source = index.canonical_id(source_id)
        owner = index.by_id[source]
        owner_rank, open_rank, _full_layers = self._composing_layer_bounds(source)
        files = [
            ComposingFile(
                layer_id=owner.source_layer_id,
                layer_label=owner.source_layer_label,
                layer_rank=owner_rank,
                is_override=False,
                path=owner.path,
            )
        ]
        records = index.overrides_by_target.get(source, [])
        for record in sorted(records, key=lambda record: record.layer_rank):
            if owner_rank < record.layer_rank <= open_rank:
                files.append(
                    ComposingFile(
                        layer_id=record.layer_id,
                        layer_label=record.layer_label,
                        layer_rank=record.layer_rank,
                        is_override=True,
                        path=record.path,
                    )
                )
        return files

    def _change_candidate_diff(
        self, source_id: str, baseline_snapshot_id: str | None
    ) -> tuple[list[str], bool, bool, list[ChangeCandidateLayer]]:
        """`(changed_fields, body_changed, whole_entry, layers)` for
        `source_id` against `baseline_snapshot_id` — or the "everything
        counts" answer when no baseline was given. A baseline id that does
        not exist lets `read_snapshot`'s 404 propagate. `changed_fields` is
        the union over every composing file (Amendment 3); `body_changed` is
        True when the owning file's body changed OR any lane's `body` row
        changed (added, removed, or a different value) — a body row is
        never reported as a field in `changed_fields` (Amendment 4 §7).

        A snapshot photographs ONE layer's file (ADR-0087), so the owning
        file's now-side is that same file read back through the same
        `_snapshot_state` normalisation — never `read_lore_entry`, whose
        folded composite would report every book override as a change the
        owning file never made. Each override delta is measured against its
        OWN baseline in its OWN lane (`_override_delta_diff`), never against
        the owning file's."""
        composing = self._composing_files(source_id)
        kind = self.node_snapshot_kind(source_id)
        if not baseline_snapshot_id:
            layers = [
                ChangeCandidateLayer(
                    layer_id=file.layer_id,
                    layer_label=file.layer_label,
                    is_override=file.is_override,
                    baseline_snapshot_id="",
                    changed_fields=[],
                    whole=True,
                )
                for file in composing
            ]
            return [], True, True, layers

        owner = composing[0]
        detail = self.read_snapshot(source_id, baseline_snapshot_id, kind=kind)
        # ADR-0091 §1's "since": whatever resolved the owning baseline sets
        # the measure for every lane — each delta lane against its own
        # newest snapshot captured at or before THIS time, never "the newest
        # propagation snapshot regardless" (#2131).
        since = detail.snapshot
        root, node_id, path = self._resolve_snapshot_target(source_id, kind)
        if path is None:
            raise ProjectServiceError("The entry has no file to compare against.", 404)
        front_matter, now_body = self._read_markdown_with_front_matter(path)
        now = self._snapshot_state(front_matter, node_id, self._snapshots_dir(root, node_id))
        now_metadata = now["metadata"]
        keys = (set(detail.metadata) | set(now_metadata)) - NON_FIELD_KEYS
        owner_changed = sorted(
            key
            for key in keys
            if not same_rendered_value(detail.metadata.get(key), now_metadata.get(key))
        )
        was_body = detail.body.replace("\r\n", "\n")
        body_changed = was_body != now_body.replace("\r\n", "\n")

        union_fields = set(owner_changed)
        layers = [
            ChangeCandidateLayer(
                layer_id=owner.layer_id,
                layer_label=owner.layer_label,
                is_override=False,
                baseline_snapshot_id=baseline_snapshot_id,
                changed_fields=owner_changed,
                whole=False,
            )
        ]
        for delta in composing[1:]:
            delta_changed, delta_baseline_id, delta_whole, delta_body_changed = self._override_delta_diff(
                source_id, kind, delta, since
            )
            union_fields.update(delta_changed)
            body_changed = body_changed or delta_body_changed
            layers.append(
                ChangeCandidateLayer(
                    layer_id=delta.layer_id,
                    layer_label=delta.layer_label,
                    is_override=True,
                    baseline_snapshot_id=delta_baseline_id,
                    changed_fields=sorted(delta_changed),
                    whole=delta_whole,
                )
            )
        removed_layers, removed_body_changed = self._removed_delta_layers(source_id, kind, composing, since)
        for removed in removed_layers:
            union_fields.update(removed.changed_fields)
            layers.append(removed)
        body_changed = body_changed or removed_body_changed
        return sorted(union_fields), body_changed, False, layers

    def _override_delta_diff(
        self, source_id: str, kind: str, delta: ComposingFile, since: Snapshot
    ) -> tuple[set[str], str, bool, bool]:
        """`(changed_fields, baseline_snapshot_id, whole, body_changed)` for
        one override delta's own lane (Amendment 3 §2): no baseline in this
        lane at or before `since` (ADR-0091 §1) yet counts every field its
        current rows touch as changed (`whole=True`, the "created after the
        since, or before this amendment" case) — including setting
        `body_changed` when a current row carries `body` (Amendment 4 §7);
        otherwise the rows differ field by field, as `(field, op, value)`
        triples, baseline against now, and `body_changed` is whether the
        lane's `body` row differs baseline-to-now."""
        baseline = self.newest_snapshot_at_or_before(
            source_id, since.captured_at, kind=kind, layer_id=delta.layer_id
        )
        current_front_matter = self._read_front_matter_only(delta.path, strict=True)
        current_rows = self._parse_override_rows(current_front_matter.get("rows"))
        if baseline is None:
            changed = {
                row.field.split(".", 1)[0] for row in current_rows if row.field not in _NON_FIELD_ROW_KEYS
            }
            body_changed = any(row.field == "body" for row in current_rows)
            return changed, "", True, body_changed
        root, node_id, _ = self._resolve_snapshot_target(source_id, kind, layer_id=delta.layer_id)
        # See the note in `_removed_delta_layers`: `_read_front_matter_only`,
        # never `_read_markdown_with_front_matter`, for a `rows:`-only read.
        baseline_front_matter = self._read_front_matter_only(
            self._snapshots_dir(root, node_id) / f"{baseline.id}.md", strict=True
        )
        baseline_rows = self._parse_override_rows(baseline_front_matter.get("rows"))
        changed = self._delta_changed_fields(baseline_rows, current_rows)
        body_changed = self._delta_body_changed(baseline_rows, current_rows)
        return changed, baseline.id, False, body_changed

    @staticmethod
    def _delta_changed_fields(
        baseline_rows: list[MutationSetRow], current_rows: list[MutationSetRow]
    ) -> set[str]:
        """The field ids whose row set — `(field, op, value)` triples grouped
        by the field id (the segment before the first dot) — differs between
        `baseline_rows` and `current_rows`, including a field present on only
        one side. `title`/`body` are never included — title because the
        owning lane never reports it either, body because a changed body row
        is reported as `body_changed` instead (Amendment 4 §7,
        `_delta_body_changed`)."""

        def by_field(rows: list[MutationSetRow]) -> dict[str, set[tuple[str, str, str]]]:
            grouped: dict[str, set[tuple[str, str, str]]] = {}
            for row in rows:
                field_id = row.field.split(".", 1)[0]
                if field_id in _NON_FIELD_ROW_KEYS:
                    continue
                grouped.setdefault(field_id, set()).add((row.field, row.op, row.value))
            return grouped

        before = by_field(baseline_rows)
        now = by_field(current_rows)
        return {field_id for field_id in set(before) | set(now) if before.get(field_id) != now.get(field_id)}

    @staticmethod
    def _delta_body_changed(
        baseline_rows: list[MutationSetRow], current_rows: list[MutationSetRow]
    ) -> bool:
        """Whether the lane's `body` row differs baseline-to-now: added,
        removed, or a changed value (Amendment 4 §7)."""

        def body_value(rows: list[MutationSetRow]) -> str | None:
            for row in rows:
                if row.field == "body":
                    return row.value
            return None

        return body_value(baseline_rows) != body_value(current_rows)

    def _add_mention_reasons(
        self,
        index: NodeIndex,
        source: str,
        entry: LoreEntry,
        story_names: list[str],
        prose_fields: frozenset[str],
        corpus: dict[str, CorpusEntry],
        add_reason,
    ) -> None:
        """Route `mentions_source`: a scan of the ADR-0085 search corpus for
        the source's names — its title and `aliases`, plus every name a
        story-time marker on those fields gave it (ADR-0008) — over scene and
        lore bodies and their `long_text` fields. Each text is scanned on its
        own, never concatenated, so a multi-word name cannot match across a
        value boundary. `prose_fields` and `corpus` are computed once by the
        caller and shared with `_add_outbound_mention_reasons`.

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
        matcher = compile_name_matcher([(source, names)])
        for node_id, corpus_entry in corpus.items():
            if node_id == source:
                continue
            candidate_entry = index.by_id.get(node_id)
            if candidate_entry is None or not _is_candidate_node(candidate_entry):
                continue
            if _corpus_entry_mention_ids(matcher, corpus_entry, prose_fields):
                add_reason(node_id, ChangeCandidateReason(route="mentions_source"))

    def _lore_name_matcher(
        self, index: NodeIndex, exclude: str
    ) -> tuple[CompiledNameMatcher, dict[str, list[str]]]:
        """The mirror matcher for `mentioned_by_source` (ADR-0091 §2): built
        from every OTHER lore entry's names — title and `aliases`, folded
        (`list_lore_entries`), so a book-layer override's aliases count —
        rather than from the source's own. No story-time marker names here:
        a note is not read as of any scene.

        `compile_name_matcher` dedups a shared name to one id, so each
        compiled entity here is a SYNTHETIC entry whose id is the normalised
        name itself (`normalise_name`, the public alias for the matcher's
        own dedup/lookup key — the two must stay the same function, not two
        that could drift). One dict, `by_name`, holds both the
        representative spelling compiled into the matcher and the real
        entry ids behind that key; the returned map is a view of the
        latter, so a name two entries share fans out to both."""
        by_name: dict[str, tuple[str, list[str]]] = {}
        for entry in self.list_lore_entries().entries:
            if entry.id == exclude:
                continue
            names = [entry.title] if entry.title else []
            aliases = entry.metadata.get("aliases")
            if isinstance(aliases, list):
                names.extend(str(alias) for alias in aliases if alias)
            for name in names:
                name = name.strip()
                if not name:
                    continue
                key = normalise_name(name)
                _representative, ids = by_name.setdefault(key, (name, []))
                if entry.id not in ids:
                    ids.append(entry.id)
        matcher = compile_name_matcher(
            [(key, [representative]) for key, (representative, _ids) in by_name.items()]
        )
        ids_by_name = {key: ids for key, (_representative, ids) in by_name.items()}
        return matcher, ids_by_name

    def _add_outbound_mention_reasons(
        self,
        index: NodeIndex,
        source: str,
        prose_fields: frozenset[str],
        corpus: dict[str, CorpusEntry],
        add_reason,
    ) -> None:
        """Route `mentioned_by_source` (ADR-0091 S1): the SOURCE's own prose
        scanned for every OTHER lore entry's name — route `mentions_source`'s
        loop run the other way, sharing the corpus read and the prose
        filter. `add_reason` already drops the source itself and
        non-candidate nodes; lore-only falls out of `_lore_name_matcher`
        having only lore names in it."""
        source_entry = corpus.get(source)
        if source_entry is None:
            return
        matcher, ids_by_name = self._lore_name_matcher(index, source)
        for key in _corpus_entry_mention_ids(matcher, source_entry, prose_fields):
            for candidate_id in ids_by_name.get(key, []):
                add_reason(candidate_id, ChangeCandidateReason(route="mentioned_by_source"))

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
