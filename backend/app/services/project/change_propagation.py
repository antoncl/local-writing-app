"""ADR-0090 §1/§3/§5: the confirm half of Propagate.

Composed onto `ProjectService`; resolves `change_candidates`
(change_candidates.py), `_create_todo_items` / `read_todos` (todos.py),
`capture_snapshot` / `node_snapshot_kind` (scene_snapshots.py) and
`_build_node_index` (references.py) via MRO.

Confirming a propagation writes exactly two things: one review item per kept
candidate, in candidate order, and a single new baseline snapshot of the
SOURCE. Nothing else — no dependent's file is touched, not a lore entry, not
a scene, not even an anchor comment, and no mutation marker is created,
changed or closed. The candidate set is read-only (change_candidates.py); this
module is the one place that writes.
"""

from __future__ import annotations

from typing import Any

from app.models import (
    ChangeCandidate,
    ChangeCandidateSet,
    ChangeMessage,
    CreateTodoRequest,
    PropagateRequest,
    PropagateResponse,
    Snapshot,
    TodoSource,
)
from app.services.ai.lore_block import _render_lore_entries, _render_node_xml
from app.services.ai.lore_budget import BeforeElement, snapshot_pick_key
from app.services.project.change_candidates import SCENE_ENTRY_TYPE
from app.services.project.errors import ProjectServiceError
from app.services.project.overrides import LayerOverride


class ChangePropagationMixin:
    """The confirm endpoint. See module docstring for the invariant it holds."""

    def propagate_change(self, source_id: str, request: PropagateRequest) -> PropagateResponse:
        candidates = self.change_candidates(source_id, request.baseline_snapshot_id)
        by_id = {item.id: item for item in candidates.items}

        kept_ids = set(request.kept)
        if not kept_ids:
            raise ProjectServiceError("Nothing kept.", 422)
        for candidate_id in sorted(kept_ids):
            if candidate_id not in by_id:
                raise ProjectServiceError(f"{candidate_id} is not a candidate.", 422)

        # Every refusal happens before the first write, including the one the
        # camera would raise: a source with no file to photograph (an override
        # target with no delta) must fail here, not after the todos landed.
        kind = self.node_snapshot_kind(candidates.source_id)
        _root, _node_id, path = self._resolve_snapshot_target(candidates.source_id, kind)
        if path is None:
            raise ProjectServiceError("The source has no file to snapshot as a baseline.", 404)

        # Candidate order, not the order `kept` happened to list them in — the
        # same order the confirm surface showed them (ADR-0090 §7).
        ordered = [item for item in candidates.items if item.id in kept_ids]

        source_title = self._propagation_source_title(candidates.source_id)
        requests = [
            self._propagation_todo_request(candidate, candidates, source_title)
            for candidate in ordered
        ]
        todos, created_items = self._create_todo_items(requests)

        # The new baseline — the only write to the source, and the only other
        # write this endpoint makes (ADR-0090 §1). Amendment 3: every EXISTING
        # override delta between the owner and the open layer gets its own
        # baseline too, in its own lane; a layer with no delta gets nothing
        # invented. ADR-0091 §1: the delta lanes are captured BEFORE the
        # owner, so the owning snapshot's time is at or after every delta
        # snapshot of this confirm — "since" resolves a delta lane by
        # captured-at-or-before the owning baseline, which needs the owner's
        # time to be the latest of the two (#2131).
        layer_snapshots = [
            self.capture_snapshot(
                candidates.source_id, kind=kind, layer_id=file.layer_id, origin="propagation"
            )
            for file in self._composing_files(candidates.source_id)
            if file.is_override
        ]
        snapshot = self.capture_snapshot(candidates.source_id, kind=kind, origin="propagation")
        return PropagateResponse(
            todos=todos,
            created=[item.id for item in created_items],
            snapshot=snapshot,
            layer_snapshots=layer_snapshots,
        )

    def _propagation_source_title(self, source_id: str) -> str:
        entry = self._build_node_index().by_id.get(source_id)
        return (entry.title if entry is not None else "") or source_id

    def _propagation_todo_request(
        self,
        candidate: ChangeCandidate,
        candidates: ChangeCandidateSet,
        source_title: str,
    ) -> CreateTodoRequest:
        """One kept candidate → one `CreateTodoRequest` (ADR-0090 §3). A scene
        candidate uses the existing `scene` scope with no anchor — the app
        never writes an anchor into a dependent's body; a lore candidate uses
        the new `node` scope. `source` names the FIRST reason only."""
        first_reason = candidate.reasons[0]
        source = TodoSource(
            node_id=candidates.source_id,
            snapshot_id=candidates.baseline_snapshot_id,
            reason=first_reason.route,
            marker_id=first_reason.marker_id if first_reason.route == "mutates_source" else "",
        )
        text = f"Follow up on {source_title}'s change"
        if candidate.entry_type == SCENE_ENTRY_TYPE:
            return CreateTodoRequest(
                text=text, scope="scene", scene_id=candidate.id, source=source
            )
        return CreateTodoRequest(text=text, scope="node", node_id=candidate.id, source=source)

    def render_baseline_element(self, source_id: str, snapshot_id: str) -> BeforeElement:
        """ADR-0093 §2: the ONE reader of a snapshot pick's before element —
        extracted from what `change_message` did before this ADR. Reads the
        baseline snapshot's bytes through `read_snapshot` (raises when the
        snapshot is thinned or gone; the caller lets it propagate), folds in
        every override delta lane's OWN baseline rows resolved by the same
        "since" rule `change_candidates` uses (ADR-0091 §1 — the composite is
        never a file, so it is folded here rather than read), and renders the
        result with the same `_render_node_xml` the live render uses, so the
        before is an entry as the AI sees one, at an earlier time. It
        canonicalises the id through the index and returns the entry id, the
        snapshot id, the capture time, the title (the live roster's, falling
        back to the snapshot's) and the XML."""
        index = self._build_node_index()
        source = index.canonical_id(source_id)
        source_entry = index.by_id.get(source)
        if source_entry is None or source_entry.kind != "lore":
            raise ProjectServiceError("Unknown lore entry.", 404)
        kind = self.node_snapshot_kind(source)
        detail = self.read_snapshot(source, snapshot_id, kind=kind)
        schema = self.read_metadata_schema()
        folded_metadata = self._fold_propagation_baseline_metadata(
            source, kind, detail.metadata, schema, detail.snapshot
        )
        before_entry = {
            "title": detail.title,
            "metadata": folded_metadata,
            "body": detail.body,
            "entry_type": source_entry.entry_type,
        }
        xml = _render_node_xml(
            self,
            schema,
            before_entry,
            source,
            {},
            extra_attrs={"snapshot": snapshot_id, "captured": detail.snapshot.captured_at},
        )
        title = source_entry.title or detail.title
        return BeforeElement(
            source, snapshot_id, detail.snapshot.captured_at, title, snapshot_pick_key(source, snapshot_id), xml
        )

    def change_message(
        self, source_id: str, baseline_snapshot_id: str | None = None
    ) -> ChangeMessage:
        """ADR-0090 §4: the pre-filled first message for a review item's
        Propose conversation — resolved through the SAME index/baseline
        semantics `change_candidates` uses, so Propose measures the identical
        change the confirm surface showed. Never writes anything; only fills
        a chat composer the writer still sends.

        `now` is the source rendered exactly as the AI already sees a lore
        entry (`_render_lore_entries` — the folded, live entry); `before`
        (only when a baseline resolved) is read by the one shared reader,
        `render_baseline_element` (ADR-0093 §2), so the two sides are entries
        as the AI sees them, at two times."""
        index = self._build_node_index()
        source = index.canonical_id(source_id)
        source_entry = index.by_id.get(source)
        if source_entry is None or source_entry.kind != "lore":
            raise ProjectServiceError("Unknown lore entry.", 404)
        resolved_baseline = self._resolve_change_candidate_baseline(source, baseline_snapshot_id)
        title = source_entry.title or source

        now_pairs = _render_lore_entries(self, [source], None, None, index)
        now_xml = now_pairs[0][1] if now_pairs else ""

        if resolved_baseline:
            element = self.render_baseline_element(source, resolved_baseline)
            before_xml = element.xml
            text = (
                f"{title} changed since the last propagation.\n\n"
                f"Before:\n{before_xml}\n\n"
                f"After:\n{now_xml}\n\n"
                "What in this entry needs to follow from that change? Propose only "
                "what the change warrants; if nothing follows, say so."
            )
        else:
            text = (
                f"{title} is the source of a change; there is no earlier baseline, "
                f"so here is the entry as it stands.\n\n{now_xml}\n\n"
                "What in this entry needs to follow from it? Propose only what the "
                "entry warrants; if nothing follows, say so."
            )
        return ChangeMessage(source_id=source, baseline_snapshot_id=resolved_baseline, text=text)

    def _fold_propagation_baseline_metadata(
        self, source_id: str, kind: str, base_metadata: dict, schema: Any, since: Snapshot
    ) -> dict:
        """Amendment 3 §5: the *before* side folds the owning baseline's
        metadata with every override delta lane's OWN baseline rows — the
        same fold the live read uses (`materialize_override_metadata`),
        outermost-first as `_composing_files` already orders them. Each
        lane's baseline is resolved by ADR-0091 §1's "since" rule — the
        newest snapshot of that lane, of any origin, captured at or before
        `since` (the owning baseline's own captured time) — the same
        resolver `_change_candidate_diff` uses, so the message's *before*
        side measures the identical change the confirm surface showed. A
        lane with no baseline at or before `since` contributes nothing to
        *before*: it did not yet compose the source at that time."""
        shapes = self._override_shapes(schema)
        records: list[LayerOverride] = []
        for file in self._composing_files(source_id):
            if not file.is_override:
                continue
            baseline = self.newest_snapshot_at_or_before(
                source_id, since.captured_at, kind=kind, layer_id=file.layer_id
            )
            if baseline is None:
                continue
            root, node_id, _ = self._resolve_snapshot_target(source_id, kind, layer_id=file.layer_id)
            baseline_front_matter, _ = self._read_markdown_with_front_matter(
                self._snapshots_dir(root, node_id) / f"{baseline.id}.md"
            )
            rows = tuple(self._parse_override_rows(baseline_front_matter.get("rows")))
            records.append(
                LayerOverride(
                    target_id=source_id,
                    layer_id=file.layer_id,
                    layer_rank=file.layer_rank,
                    layer_label=file.layer_label,
                    path=file.path,
                    rows=rows,
                )
            )
        if not records:
            return dict(base_metadata)
        folded, _touched = self.materialize_override_metadata(dict(base_metadata), records, shapes)
        return folded
