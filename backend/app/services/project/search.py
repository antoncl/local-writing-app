"""Full-text / metadata search slice of ProjectService (#14 backend split;
ADR-0085 §§2-3 for slice 1).

`search` reads the search corpus (`search_corpus.py` / `SearchCorpusMixin`,
`search_corpus_build.py`) instead of scanning files — the corpus is built
once from the resolved node index's winners view and kept current by the
write funnel (`_apply_index_write`), so this module never globs a folder
itself (a guard test bans `rglob` from this file the way
`test_node_index_memo.py:554` bans `.unlink(`). This mixin owns the query
path plus its search-only helpers; `ProjectService` composes it.

Shared helpers it calls (`self._require_project`, `self._search_corpus`
[`SearchCorpusMixin`], `self.read_todos`, `self._scan_embedded_todos_in_body`
[`EmbeddedTodosMixin`], `self.read_structure`) resolve through the MRO at
call time.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from typing import Any

from app.models import (
    MetadataSchema,
    SearchHit,
    SearchRequest,
    SearchResponse,
    StructureNode,
)
from app.services.project.metadata_refs import (
    UNCHANGED,
    RefOccurrence,
    rewrite_ref_occurrences,
)
from app.services.project.node_index import NodeIndex
from app.services.project.search_corpus import CorpusEntry
from app.services.tree_structure import StructureVisitor, TreeStructureService


def _compile_query(query: str, *, match_case: bool, whole_word: bool) -> re.Pattern[str]:
    """A query stays a literal substring, never a regex (ADR-0085 anti-goal).
    `whole_word` brackets the escaped literal in lookarounds rather than `\\b`
    so a query starting or ending in punctuation still bounds correctly."""
    escaped = re.escape(query)
    if whole_word:
        escaped = rf"(?<!\w){escaped}(?!\w)"
    flags = 0 if match_case else re.IGNORECASE
    return re.compile(escaped, flags)


# The excerpt is a display field (ADR-0085 §2) — a window around the match,
# not the whole line. A hit is emitted per occurrence, so a long paragraph with
# fifty matches used to ship fifty copies of itself (#1868: 24k hits, 14 MB,
# a frozen tab). The window keeps the payload linear in hits. Lines at or
# under `EXCERPT_MAX_LINE` are still sent whole, so a short line reads as it
# always did; a clipped edge snaps outward to a word boundary. The match itself
# is never clipped, however long. The ellipsis is NOT baked into the string:
# the pane re-matches the query over the excerpt to place its highlight, so a
# literal "…" here would be marked by a query of "…". The two flags let the
# pane draw the ellipses outside the highlighted text.
EXCERPT_MAX_LINE = 160
EXCERPT_BEFORE = 60
EXCERPT_AFTER = 100


@dataclass(frozen=True)
class ExcerptWindow:
    text: str
    clipped_before: bool
    clipped_after: bool


def excerpt_window(line: str, start: int, end: int) -> ExcerptWindow:
    """`line[start:end]` is the match; returns the display excerpt for it."""
    if len(line) <= EXCERPT_MAX_LINE:
        return ExcerptWindow(line.strip(), False, False)
    left = max(0, start - EXCERPT_BEFORE)
    right = min(len(line), end + EXCERPT_AFTER)
    if left > 0:
        # Start on a word: skip forward to just past the next space, if one
        # lies before the match.
        space = line.find(" ", left, start)
        if space != -1:
            left = space + 1
    if right < len(line):
        # End on a word: pull back to the last space after the match.
        space = line.rfind(" ", end, right)
        if space != -1:
            right = space
    return ExcerptWindow(line[left:right].strip(), left > 0, right < len(line))


class _SceneDisplayPaths(StructureVisitor):
    """`scene_id → "Act / Chapter / Scene"` title breadcrumb (root title
    omitted) for every node carrying a scene_id."""

    def __init__(self) -> None:
        self.paths: dict[str, str] = {}

    def visit_node(
        self, node: StructureNode, ancestors: tuple[StructureNode, ...]
    ) -> None:
        if not node.scene_id:
            return
        titles = [a.title for a in ancestors if a.type != "root"]
        if node.type != "root":
            titles.append(node.title)
        self.paths[node.scene_id] = " / ".join(titles)


class SearchMixin:
    def search(self, request: SearchRequest) -> SearchResponse:
        self._require_project()
        hits: list[SearchHit] = []
        query = request.query.strip()

        if not query and not request.include_open_todos:
            return SearchResponse(query=query, hits=[])

        scene_paths = self._scene_display_paths()
        pattern = (
            _compile_query(query, match_case=request.match_case, whole_word=request.whole_word)
            if query
            else None
        )
        if request.include_open_todos:
            hits.extend(self._search_open_todos(pattern, scene_paths))

        if pattern is not None:
            entries = self._search_corpus()
            hits.extend(self._search_corpus_entries(entries, pattern, request, scene_paths))
        return SearchResponse(query=request.query, hits=hits)

    def _search_open_todos(
        self, pattern: re.Pattern[str] | None, scene_paths: dict[str, str]
    ) -> list[SearchHit]:
        """Open TODOs matching `pattern` (or all open ones when `pattern` is
        None) — both the todo.yaml list and the in-scene embedded-todo
        comments, the latter scanned from the corpus's manuscript bodies
        rather than a second `rglob` of the scenes."""
        hits: list[SearchHit] = []
        for item in self.read_todos().items:
            if item.status != "open":
                continue
            if pattern is None or pattern.search(item.text):
                hits.append(
                    SearchHit(
                        kind="manuscript" if item.scene_id else "project",
                        file_id=item.scene_id or "project",
                        path=f"{scene_paths.get(item.scene_id, 'Project')} TODO" if item.scene_id else "Project TODO",
                        line=1,
                        excerpt=item.text,
                        todo_id=item.id,
                    )
                )

        for entry in self._search_corpus().values():
            if entry.kind != "manuscript":
                continue
            scene_path = scene_paths.get(entry.id, entry.path.name)
            for todo in self._scan_embedded_todos_in_body(entry.id, entry.body, scene_path):
                if todo.status != "open":
                    continue
                excerpt = todo.note or todo.text
                if pattern is None or pattern.search(f"{todo.note} {todo.text}"):
                    hits.append(
                        SearchHit(
                            kind="manuscript",
                            file_id=todo.scene_id,
                            path=todo.scene_path,
                            line=todo.line,
                            excerpt=excerpt,
                            todo_id=todo.todo_id,
                            field="body",
                            start=0,
                            end=0,
                            revision=entry.revision,
                            owned=entry.owned,
                        )
                    )
        return hits

    def _search_corpus_entries(
        self,
        entries: dict[str, CorpusEntry],
        pattern: re.Pattern[str],
        request: SearchRequest,
        scene_paths: dict[str, str],
    ) -> list[SearchHit]:
        """Metadata hits then body hits for every corpus entry `request.kinds`
        selects (None = every kind), ordered manuscript first (in
        `scene_paths` order where known), then lore, then every other kind by
        kind then title — today's grouping, generalised to every corpus
        kind."""
        scene_order = {scene_id: index for index, scene_id in enumerate(scene_paths)}

        def _sort_key(entry: CorpusEntry) -> tuple[int, int, str]:
            if entry.kind == "manuscript":
                return (0, scene_order.get(entry.id, len(scene_order)), entry.title)
            if entry.kind == "lore":
                return (1, 0, entry.title)
            return (2, 0, f"{entry.kind}:{entry.title}")

        selected = [
            entry for entry in entries.values() if request.kinds is None or entry.kind in request.kinds
        ]

        hits: list[SearchHit] = []
        for entry in sorted(selected, key=_sort_key):
            display = self._corpus_display_path(entry, scene_paths)
            for label, value in entry.metadata_values:
                match = pattern.search(value)
                if match:
                    window = excerpt_window(value, match.start(), match.end())
                    hits.append(
                        SearchHit(
                            kind=entry.kind,
                            entry_type=entry.entry_type,
                            file_id=entry.id,
                            path=f"{display} metadata",
                            line=1,
                            excerpt=f"{label}: {window.text}",
                            clipped_before=window.clipped_before,
                            clipped_after=window.clipped_after,
                            field="metadata",
                            start=0,
                            end=0,
                            revision=entry.revision,
                            owned=entry.owned,
                        )
                    )
            hits.extend(self._corpus_body_hits(entry, pattern, display))
        return hits

    def _corpus_body_hits(
        self, entry: CorpusEntry, pattern: re.Pattern[str], display: str
    ) -> list[SearchHit]:
        """One hit per occurrence in `entry.body` (ADR-0085 §2 — a replace
        needs each match, not each matching line). Line starts are computed
        once per entry so a many-match body stays linear rather than
        re-scanning from the top for every match; the excerpt is a window
        around the match (`excerpt_window`) so the payload is too."""
        body = entry.body
        line_starts = [0] + [index + 1 for index, char in enumerate(body) if char == "\n"]
        hits: list[SearchHit] = []
        for match in pattern.finditer(body):
            line = bisect.bisect_right(line_starts, match.start())
            line_start = line_starts[line - 1]
            line_end = body.find("\n", line_start)
            if line_end == -1:
                line_end = len(body)
            window = excerpt_window(
                body[line_start:line_end], match.start() - line_start, match.end() - line_start
            )
            hits.append(
                SearchHit(
                    kind=entry.kind,
                    entry_type=entry.entry_type,
                    file_id=entry.id,
                    path=display,
                    line=line,
                    excerpt=window.text,
                    clipped_before=window.clipped_before,
                    clipped_after=window.clipped_after,
                    field="body",
                    start=match.start(),
                    end=match.end(),
                    revision=entry.revision,
                    owned=entry.owned,
                    text=match.group(),
                )
            )
        return hits

    def _corpus_display_path(self, entry: CorpusEntry, scene_paths: dict[str, str]) -> str:
        if entry.kind == "manuscript":
            return scene_paths.get(entry.id, entry.path.name)
        if entry.kind == "lore":
            return f"Lore / {entry.title}"
        return f"{entry.kind.capitalize()} / {entry.title}"

    def _iter_metadata_search_values(self, metadata: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
        values: list[tuple[str, str]] = []
        for key, raw_value in metadata.items():
            label = f"{prefix}.{key}" if prefix else key
            if raw_value is None:
                continue
            if isinstance(raw_value, dict):
                values.extend(self._iter_metadata_search_values(raw_value, label))
            elif isinstance(raw_value, list):
                # A list may hold record items (#698): one searchable pair
                # per record item (member values joined), scalars batched as
                # before — never str(dict), which buries the text in a Python
                # repr, and never one pair per member, which floods the hit
                # list from a single entry.
                scalar_text = ", ".join(
                    str(item) for item in raw_value if item is not None and not isinstance(item, dict)
                )
                if scalar_text:
                    values.append((label, scalar_text))
                for position, item in enumerate(raw_value):
                    if isinstance(item, dict):
                        item_text = " · ".join(
                            str(member) for member in item.values() if member not in (None, "")
                        )
                        if item_text:
                            values.append((f"{label}[{position}]", item_text))
            else:
                text = str(raw_value)
                if text:
                    values.append((label, text))
        return values

    def _resolve_reference_titles(
        self,
        metadata: dict[str, Any],
        entry_type: str,
        schema: MetadataSchema,
        node_index: NodeIndex,
    ) -> dict[str, Any]:
        if schema.entry_types.get(entry_type) is None:
            return metadata

        # One traversal reaches every ref — top-level or inside an item_group
        # member (ADR-0081) — so a nested ref shows its target's title, not a
        # raw id. Display-only: this returns a copy for search/rendering.
        def _to_title(occ: RefOccurrence) -> Any:
            if occ.field.type == "entity_ref" and isinstance(occ.value, str):
                target = node_index.by_id.get(node_index.canonical_id(occ.value))
                return target.title if target and target.title else UNCHANGED
            if occ.field.type == "entity_ref_list" and isinstance(occ.value, list):
                return [self._ref_title_or_id(item, node_index) for item in occ.value]
            return UNCHANGED

        resolved, _ = rewrite_ref_occurrences(metadata, schema, _to_title)
        return resolved

    @staticmethod
    def _ref_title_or_id(item: Any, node_index: NodeIndex) -> Any:
        """A ref id swapped for its target's title, or the item unchanged when it
        does not resolve to a titled node (display-only, for entity_ref_list)."""
        target = node_index.by_id.get(node_index.canonical_id(item)) if isinstance(item, str) else None
        return target.title if target and target.title else item

    def _scene_display_paths(self) -> dict[str, str]:
        visitor = _SceneDisplayPaths()
        TreeStructureService.walk(self.read_structure().root, visitor)
        return visitor.paths
