"""Mutation-set anchor scan (ADR-0095 §2): every scene's
`<!-- mutate:set=...;id=... -->` comment, grouped by the set id it names — the
input the set service reads to compute a set's `state`/`anchors` (§2) without
a stored flag.

Scanned over EVERY manuscript-kind scene of the OPEN project, in the tree or
not (§2: a set anchored in a scene out of the tree is still active). Tree
order is used only to order the anchors for display; a scene with no
manuscript position sorts after every placed one, stable by scene id.
"""

from __future__ import annotations

from pathlib import Path

from app.models import MutationSetAnchor
from app.services.project.mutation_anchors import MUTATION_ANCHOR_PATTERN


class MutationSetAnchorsMixin:
    def anchors_by_set(self) -> dict[str, list[MutationSetAnchor]]:
        """Every anchor in the open project, by the set id it names.

        Per-scene scans are cached on this service instance by (path,
        revision) — `_revision` — so listing every set doesn't re-read every
        scene body more than once per call; a scene whose revision changed
        since the last scan is always re-read (correctness first, #3)."""
        index = self._build_node_index()
        order = self._scene_order()
        scenes = sorted(
            (entry for entry in index.by_id.values() if entry.kind == "manuscript"),
            key=lambda entry: (order.get(entry.id, len(order)), entry.id),
        )
        by_set: dict[str, list[MutationSetAnchor]] = {}
        for entry in scenes:
            for anchor_id, set_id in self._scene_anchor_scan(entry.path):
                by_set.setdefault(set_id, []).append(
                    MutationSetAnchor(anchor_id=anchor_id, scene_id=entry.id, scene_title=entry.title)
                )
        return by_set

    def _scene_anchor_scan(self, path: Path) -> list[tuple[str, str]]:
        """`[(anchor_id, set_id), ...]` found in one scene body, cached by
        `(path, revision)` on this service instance."""
        cache: dict[Path, tuple[str, list[tuple[str, str]]]] = getattr(
            self, "_mutation_anchor_scan_cache", None
        ) or {}
        self._mutation_anchor_scan_cache = cache
        revision = self._revision(path)
        cached = cache.get(path)
        if cached is not None and cached[0] == revision:
            return cached[1]
        try:
            _, body = self._read_markdown_with_front_matter(path)
        except OSError:
            found: list[tuple[str, str]] = []
        else:
            found = [(m.group("id"), m.group("set_id")) for m in MUTATION_ANCHOR_PATTERN.finditer(body)]
        cache[path] = (revision, found)
        return found
