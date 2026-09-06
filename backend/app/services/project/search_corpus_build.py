"""ADR-0085 §1: builds and maintains the search corpus behind `search.py`.

`SearchMixin` (search.py) is the corpus's only reader. This mixin owns the
cold build (`_search_corpus`, from `NodeIndex.by_id` — never a second file
enumeration) and the incremental patch (`_patch_search_corpus`, called from
`_apply_index_write`). `ProjectService` composes it alongside `SearchMixin`.
Shared helpers it calls (`self._require_project`, `self._build_node_index`,
`self.read_metadata_schema`, `self._metadata_schema_layer_id`,
`self._read_markdown_with_front_matter`, `self._normalise_metadata`,
`self._resolve_reference_titles`, `self._iter_metadata_search_values`,
`self._composite_revision`, `self._override_paths_for_target`, `self._revision`)
resolve through the MRO at call time.
"""

from __future__ import annotations

from pathlib import Path

from app.models import MetadataSchema
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index import NodeIndex, NodeIndexEntry
from app.services.project.node_index_gate import node_index_gate
from app.services.project.overrides import OVERRIDES_FOLDER
from app.services.project.search_corpus import CorpusEntry, search_corpus


class SearchCorpusMixin:
    def _search_corpus(self) -> dict[str, CorpusEntry]:
        """The held corpus for the open project, built cold on the first call
        after it is empty. Built from the resolved node index's winners view
        (`NodeIndex.by_id`) — never a second `rglob` of the project files.

        The build itself (the loop below) runs outside the corpus lock and
        takes hundreds of ms, so a save landing mid-build must not have its
        own patch published over. Read the generation before building, then
        publish conditioned on it — a mismatch means `note_write`/a mutator
        bumped it while this build ran, so retry against a fresh read.
        Bounded at 3 attempts: a busy project must never wedge a search, so
        after three misses serve this query from the freshly built dict
        WITHOUT publishing it; the next query tries the cold build again.
        """
        root = self._require_project().resolve()
        held = search_corpus.peek(root)
        if held is not None:
            return held
        entries: list[CorpusEntry] = []
        for _attempt in range(3):
            held = search_corpus.peek(root)
            if held is not None:
                return held
            generation = search_corpus.generation()
            index = self._build_node_index(root)
            schema = self.read_metadata_schema()
            root_layer_id = self._metadata_schema_layer_id(root)
            entries = []
            for entry in index.by_id.values():
                if entry.kind == "chat":
                    # ADR-0085 §1: a chat body is a serialised transcript, not
                    # prose — a substring match would report YAML structure.
                    continue
                corpus_entry = self._corpus_entry_for(entry, index, schema, root_layer_id)
                if corpus_entry is not None:
                    entries.append(corpus_entry)
            if search_corpus.publish(root, entries, generation=generation):
                return search_corpus.peek(root)
        return {entry.id: entry for entry in entries}

    def _corpus_entry_for(
        self,
        entry: NodeIndexEntry,
        index: NodeIndex,
        schema: MetadataSchema,
        root_layer_id: str,
    ) -> CorpusEntry | None:
        """`entry` turned into a `CorpusEntry`, or None when its file is not
        front-mattered Markdown (a malformed or unexpected file the index
        still lists, e.g. a snapshot sidecar) — not an error, just not
        searchable."""
        try:
            front_matter, body = self._read_markdown_with_front_matter(entry.path, strict=True)
        except ProjectServiceError:
            return None
        if not front_matter:
            return None
        body = body.replace("\r\n", "\n")
        entry_type = str(front_matter.get("entry_type") or entry.entry_type)
        title = str(front_matter.get("title") or entry.title or entry.id)
        metadata = self._resolve_reference_titles(
            self._normalise_metadata(front_matter.get("metadata"), entry.path),
            entry_type,
            schema,
            index,
        )
        searchable: dict[str, object] = {"title": title, "entry_type": entry_type, **metadata}
        if entry.kind == "manuscript":
            # Today's scene search includes status; lore does not — keep parity.
            searchable["status"] = str(front_matter.get("status") or "draft")
        metadata_values = tuple(self._iter_metadata_search_values(searchable))
        revision = self._corpus_revision(entry, index)
        owned = entry.source_layer_id == root_layer_id
        return CorpusEntry(
            id=entry.id,
            kind=entry.kind,
            entry_type=entry_type,
            title=title,
            path=entry.path,
            layer_id=entry.source_layer_id,
            owned=owned,
            body=body,
            metadata_values=metadata_values,
            revision=revision,
        )

    def _corpus_revision(self, entry: NodeIndexEntry, index: NodeIndex) -> str:
        """The value `entry`'s own save primitive checks a `base_revision`
        against — never re-derived. A lore/prompt entry's revision folds in
        every override file in the chain (`lore.py:151` / `prompts.py:330`);
        every other kind is a plain file hash."""
        if entry.kind in ("lore", "prompt"):
            return self._composite_revision(
                [entry.path, *self._override_paths_for_target(index, entry.id)]
            )
        return self._revision(entry.path)

    def _patch_search_corpus(self, paths: tuple[Path, ...]) -> None:
        """Called from `_apply_index_write` for exactly the paths a write
        touched — re-read a written path, drop a deleted one, unconditionally
        (the node index's own change-gate may decide a prose-only save
        changes nothing it holds; the corpus always re-reads, because prose is
        precisely what it holds)."""
        root = self.root_path.resolve()
        held = search_corpus.peek(root)
        if held is None:
            # Empty — nothing to patch directly, but an in-flight cold build
            # may be mid-read right now; bump the generation so it sees this
            # write happened and rebuilds instead of publishing a stale read.
            search_corpus.note_write()
            return
        if any(path.parent.name == OVERRIDES_FOLDER for path in paths):
            # An override changes a *target's* effective content and composite
            # revision without touching the target's own file — a write to an
            # override reaches `_maintain_index_after_write`, which drops the
            # whole memo for exactly this reason; a *delete* (a full revert)
            # reaches this seam directly instead, so mirror that fan-out here.
            search_corpus.drop()
            return
        resolved = node_index_gate.peek(root)
        if resolved is None:
            # No index to derive kind/layer from — rebuild cold later.
            search_corpus.drop()
            return
        schema = resolved.schema or self.read_metadata_schema()
        root_layer_id = self._metadata_schema_layer_id(root)
        for path in paths:
            self._patch_search_corpus_path(root, path, resolved.index, schema, root_layer_id)

    def _patch_search_corpus_path(
        self,
        root: Path,
        path: Path,
        index: NodeIndex,
        schema: MetadataSchema,
        root_layer_id: str,
    ) -> None:
        """One path's worth of `_patch_search_corpus`'s loop — split out so
        the caller's own branching stays under the complexity gate."""
        if not path.exists():
            search_corpus.drop_path(path)
            return
        # A path the corpus already files resolves through its reverse
        # map; only a NEW file (create, rename target) needs the scan.
        known_id = search_corpus.id_for_path(path)
        entry = index.by_id.get(known_id) if known_id else None
        if entry is None or entry.path.resolve() != path:
            entry = next((e for e in index.by_id.values() if e.path.resolve() == path), None)
        if entry is None:
            # A file the index does not list is not searchable.
            search_corpus.drop_path(path)
            return
        if entry.kind == "chat":
            return
        corpus_entry = self._corpus_entry_for(entry, index, schema, root_layer_id)
        if corpus_entry is None:
            search_corpus.drop_path(path)
            return
        existing_id = search_corpus.id_for_path(path)
        if existing_id is not None and existing_id != corpus_entry.id:
            # Ids are stable, so this should not happen — guard anyway
            # rather than leave a stale entry under the old id.
            search_corpus.drop_path(path)
        search_corpus.upsert(root, corpus_entry)
