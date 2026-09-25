"""Restore-time mutation-anchor conversion (ADR-0095 §11), split out of
`scene_snapshots.py` to keep that file under the size guard.

`SceneSnapshotMutationsMixin` composes onto `ProjectService` alongside
`SceneSnapshotsMixin`; `restore_snapshot` calls the two entry points here —
`convert_restored_scene_markers` (a pre-v14 snapshot's legacy markers) and
`dedupe_restored_scene_anchors` (every restore's anchor-id collision check) —
right before it writes the restored bytes. Both read/write through the same
`self` seams `scene_snapshots.py` itself uses (`self._build_node_index`,
`self.anchors_by_set`, `self._write_converted_mutation_set`,
`self._copy_mutation_set_unvalidated`, `self._new_id`), resolved via MRO.
"""

from __future__ import annotations

import re

from app.services import migrations
from app.services.project.legacy_mutation_markers import convert_restored_scene
from app.services.project.mutation_anchors import (
    MUTATION_ANCHOR_CLOSE_PATTERN,
    MUTATION_ANCHOR_PATTERN,
    render_anchor,
    render_close,
)


def split_snapshot_text(text: str) -> tuple[str, str] | None:
    """`(header including both --- delimiters and the exact separator before
    the body, body)`, or `None` when `text` has no front matter. The header is
    kept as raw text, not re-serialised, so a caller that only changes the
    body (the byte-exact restore branch, ADR-0043) can splice it back and
    leave the front matter byte-identical when nothing else changed.
    Line-based (mirrors `migrations_mutation_anchors._split_document`), so a
    stored snapshot's real `\\r\\n` line endings (Windows — `atomic_write_text`
    writes through a text-mode handle) still locate the closing delimiter."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    close = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if close is None:
        return None
    header_lines, body_lines = lines[: close + 1], lines[close + 1 :]
    while body_lines and body_lines[0].strip("\r\n") == "":
        header_lines.append(body_lines.pop(0))
    return "".join(header_lines), "".join(body_lines)


class SceneSnapshotMutationsMixin:
    def _convert_restored_scene_markers(
        self, node_id: str, migrated: migrations.MigratableDocument
    ) -> migrations.MigratableDocument:
        """ADR-0095 §11: the snapshot predates sets + anchors — convert its
        legacy markers before the body is written, recognising the ids §12's
        migration would have derived for this scene, so a marker whose set
        already exists (from the migration, or an earlier restore) resolves
        to it again instead of duplicating it. Sets are written unvalidated
        (§4: restore bypasses validation), through the same writer the
        migration itself uses — which already goes through the normal
        index-write path, so the new pills resolve at once."""
        index = self._build_node_index()

        def _entity_type(entity_id: str) -> str | None:
            entry = index.by_id.get(entity_id)
            return entry.entry_type if entry is not None and entry.kind == "lore" else None

        def _set_exists(set_id: str) -> bool:
            entry = index.by_id.get(set_id)
            return entry is not None and entry.kind == "mutation_set"

        new_body, sets_to_create = convert_restored_scene(node_id, migrated.body, _entity_type, _set_exists)
        for converted in sets_to_create:
            self._write_converted_mutation_set(converted)
        return migrations.MigratableDocument(migrated.front_matter, new_body)

    def _dedupe_restored_scene_anchors(
        self, node_id: str, migrated: migrations.MigratableDocument | None, frozen_bytes: bytes
    ) -> tuple[migrations.MigratableDocument | None, bytes]:
        """ADR-0095 §11: EVERY restore, not only a pre-v14 one — an anchor
        whose id now lives in ANOTHER scene (cut from this scene into another
        since the snapshot was taken) is re-minted with a copy of its set, so
        the two scenes never end up sharing one anchor id."""
        if migrated is not None:
            new_body = self._dedupe_restored_anchors(node_id, migrated.body)
            if new_body != migrated.body:
                migrated = migrations.MigratableDocument(migrated.front_matter, new_body)
            return migrated, frozen_bytes
        split = split_snapshot_text(frozen_bytes.decode("utf-8"))
        if split is None:
            return migrated, frozen_bytes
        header, body = split
        new_body = self._dedupe_restored_anchors(node_id, body)
        if new_body != body:
            frozen_bytes = (header + new_body).encode("utf-8")
        return migrated, frozen_bytes

    def _dedupe_restored_anchors(self, node_id: str, body: str) -> str:
        """ADR-0095 §11: a restored anchor whose id now lives in ANOTHER scene
        of the project (cut from this scene into another since the snapshot
        was taken, so the app's own paste de-duplication never saw it) is
        re-minted, with its set copied — unvalidated, every row kept
        (`_copy_mutation_set_unvalidated`; restore bypasses validation, §4) —
        so the two scenes never end up naming the same set through what would
        otherwise look like a link neither writer chose. Any close in this
        body that referenced the old anchor id is repointed at the new one. A
        no-op body when nothing in it collides with another scene."""
        anchor_scene: dict[str, str] = {}
        for anchors in self.anchors_by_set().values():
            for anchor in anchors:
                if anchor.scene_id != node_id:
                    anchor_scene.setdefault(anchor.anchor_id, anchor.scene_id)
        if not anchor_scene:
            return body
        remap: dict[str, str] = {}

        def _replace_anchor(match: re.Match[str]) -> str:
            anchor_id = match.group("id")
            if anchor_id not in anchor_scene:
                return match.group(0)
            new_set_id = self._copy_mutation_set_unvalidated(match.group("set_id"))
            new_anchor_id = self._new_id("mut")
            remap[anchor_id] = new_anchor_id
            return render_anchor(new_set_id, new_anchor_id)

        new_body = MUTATION_ANCHOR_PATTERN.sub(_replace_anchor, body)
        if not remap:
            return new_body

        def _replace_close(match: re.Match[str]) -> str:
            ref = match.group("ref")
            if ref not in remap:
                return match.group(0)
            return render_close(remap[ref], match.group("id"), row=match.group("row") or "")

        return MUTATION_ANCHOR_CLOSE_PATTERN.sub(_replace_close, new_body)
