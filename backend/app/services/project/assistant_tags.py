"""Assistant-tag governance slice of ProjectService (#247 slice 2, PR-3).

Assistant tags are a flat, machine-global vocabulary — name + colour, no scope,
no layers (`assistant-tags.yaml`, #88). So governance here is much simpler than
`TagsMixin`: no broaden-only scope rules, no per-layer records, no ancestor-scope
guard. The one thing it shares with project-tag merge is the document rewrite —
a rename or merge must rewrite every reachable *reference* or the next save
re-registers the old name (`register_assistant_tags`).

Assistant tags are referenced from two fields on two node kinds:
  - an `assistant` node, via `metadata.tags`
  - a `prompt` node, via `metadata.assistant_tags`

**Reachability bound (ADR-0045).** A rewrite here reaches only what the open
scope owns: the machine store, the machine-roster + open-project assistant files
(`metadata.tags`), and the open project's own prompt files
(`metadata.assistant_tags`). It deliberately does NOT touch an *ancestor* layer's
files (they belong to a parent project) or an unopened project's files. A stale
reference in either survives the merge, keeps a use-count, and is re-registered
under the old name by the next save that rewrites one of those documents — the
same bound project-merge accepts (`_reject_sources_above_this_layer`). Rename is
a single-source merge, exactly as on the project side.

Shared helpers reached through the composed class's MRO: `self.root_path`,
`self._is_relative_to`, `self._build_assistant_index`,
`self._read_markdown_with_front_matter`, `self._write_markdown_with_front_matter`,
and `self._rename_tag_in_value` (TagsMixin) — the value-level rewriter is reused
rather than re-implemented so the assistant and project renames dedupe values the
same way.
"""

from __future__ import annotations

from pathlib import Path

from app.models import (
    AssistantTagList,
    AssistantTagsOverview,
    AssistantTagUsage,
    MergeAssistantTagsRequest,
)
from app.services.project.errors import ProjectServiceError

# The two (kind, field) references into the assistant-tag vocabulary. Both
# assistant nodes and prompt nodes now carry `assistant_tags` (ADR-0082 §2
# renamed the assistant's field off the retired-for-built-ins `tags`, so an
# `entity_ref_list` field id no longer has to disambiguate two vocabularies by
# convention). The two constants are equal today; kept as two names because
# this whole mixin is dead code slated for retirement in a later ADR-0082
# slice, not touched further here.
_ASSISTANT_TAG_FIELD = "assistant_tags"
_PROMPT_ASSISTANT_TAG_FIELD = "assistant_tags"


class AssistantTagsMixin:
    def _assistant_tag_documents(self) -> list[tuple[Path, str]]:
        """`(path, field_id)` for every reachable assistant-tag reference.

        Assistant files (machine roster + the open project's own) contribute
        their `tags` field; the open project's prompt files contribute
        `assistant_tags`. Ancestor-layer assistant files are excluded by the
        physical path test below — they live under a parent project's folder,
        not under the machine dir or the open root, so a merge here never
        rewrites a parent project's files.
        """
        from app.services import machine_settings as ms

        docs: list[tuple[Path, str]] = []
        machine_assistants = ms.assistants_dir()
        owned_assistants = (self.root_path / "assistants") if self.root_path is not None else None
        index = self._build_assistant_index()
        for entry in index.by_id.values():
            if entry.kind != "assistant":
                continue
            reachable = self._is_relative_to(entry.path, machine_assistants) or (
                owned_assistants is not None and self._is_relative_to(entry.path, owned_assistants)
            )
            if reachable:
                docs.append((entry.path, _ASSISTANT_TAG_FIELD))
        if self.root_path is not None:
            for path in sorted((self.root_path / "prompts").glob("*.md")):
                docs.append((path, _PROMPT_ASSISTANT_TAG_FIELD))
        return docs

    def _count_assistant_tag_documents(self) -> tuple[dict[str, int], dict[str, str]]:
        """Occurrences per lowercased assistant-tag name across the reachable
        documents, plus first-seen display casing. Shared shape with
        `_count_document_tags` so the count the author sees and the set a merge
        rewrites are read the same way."""
        from app.services import machine_settings as ms

        counts: dict[str, int] = {}
        display: dict[str, str] = {}
        for path, field_id in self._assistant_tag_documents():
            try:
                front_matter, _body = self._read_markdown_with_front_matter(path, strict=False)
            except ProjectServiceError:
                continue
            metadata = front_matter.get("metadata")
            if not isinstance(metadata, dict):
                continue
            for name in ms.tag_names_from_field(metadata.get(field_id)):
                key = name.lower()
                counts[key] = counts.get(key, 0) + 1
                display.setdefault(key, name)
        return counts, display

    def read_assistant_tags_overview(self) -> AssistantTagsOverview:
        """The assistant mirror of `read_tags_overview`, joined against the flat
        machine store (#247). A registered-but-unused tag still shows (count 0);
        a tag on a document but not yet in the store shows with its document
        casing — the same union the project overview does."""
        from app.services import machine_settings as ms

        counts, display = self._count_assistant_tag_documents()
        store = {tag.name.lower(): tag for tag in ms.load_assistant_tags()}
        usages: list[AssistantTagUsage] = []
        for key in set(counts) | set(store):
            record = store.get(key)
            usages.append(
                AssistantTagUsage(
                    name=record.name if record else display.get(key, key),
                    count=counts.get(key, 0),
                    color=record.color if record else None,
                )
            )
        usages.sort(key=lambda usage: usage.name.lower())
        return AssistantTagsOverview(tags=usages)

    def _rename_assistant_tag_in_documents(self, source_lowers: set[str], target: str) -> None:
        """Replace every occurrence of `source_lowers` with `target` in the
        assistant-tag field of each reachable document, de-duplicating via the
        shared `_rename_tag_in_value`."""
        for path, field_id in self._assistant_tag_documents():
            try:
                front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            except ProjectServiceError:
                continue
            metadata = front_matter.get("metadata")
            if not isinstance(metadata, dict):
                continue
            value = metadata.get(field_id)
            if not isinstance(value, list):
                continue
            next_values = self._rename_tag_in_value(value, source_lowers, target)
            if next_values != value:
                metadata[field_id] = next_values
                front_matter["metadata"] = metadata
                self._write_markdown_with_front_matter(path, front_matter, body)

    def merge_assistant_tags(self, request: MergeAssistantTagsRequest) -> AssistantTagList:
        """Fold `sources` into `target`, rewriting reachable references then the
        store (#247). Rename is a single-source merge. The survivor keeps its own
        colour; merged-away sources drop theirs (handled in the store fold)."""
        from app.services import machine_settings as ms

        target = request.target.strip()
        if not target:
            raise ProjectServiceError("A name for the merged tag is required.", 422)
        sources = [source.strip() for source in request.sources if source.strip()]
        if not sources:
            raise ProjectServiceError("Pick at least one tag to merge.", 422)
        source_lowers = {source.lower() for source in sources if source.lower() != target.lower()}

        # 1. Rewrite references across the reachable documents (skip the no-op
        #    self-merge where every source is the target).
        if source_lowers:
            self._rename_assistant_tag_in_documents(source_lowers, target)
        # 2. Fold the flat machine store last (survivor keeps its colour).
        return AssistantTagList(tags=ms.merge_assistant_tags(sources, target))
