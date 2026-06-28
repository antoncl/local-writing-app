"""Scoped-tags slice of ProjectService (#14 backend split).

Known tags live in `<project>/tags.yaml` as `{name, scope}` records, where the
scope is a `NodePickerConfig` describing which node kinds/entry-types the tag
applies to. This mixin owns the tags store (read/overview/update-scope/merge)
plus the scope helpers; `ProjectService` composes it.

Method bodies moved verbatim. Shared helpers they call (`self._require_project`,
`self._read_yaml`, `self._write_yaml`, `self.read_metadata_schema`,
`self._entry_markdown_paths`, `self._read_markdown_with_front_matter`,
`self._write_markdown_with_front_matter`) live elsewhere on the composed class
and resolve through the MRO at call time. The scope helpers
(`_tag_scope_for_node`, `_union_node_picker_scope`, `_write_scoped_tags`) and
`read_known_tags` are also consumed by the core `_canonicalise_metadata_tags`
save path — same MRO resolution. `_entry_markdown_paths` stays in core: it is a
generic node-file lister shared with the schema slice.
"""

from __future__ import annotations

from typing import Any

from app.models import (
    KnownTags,
    MergeTagsRequest,
    NodePickerConfig,
    ScopedTag,
    TagsOverview,
    TagUsage,
    UpdateTagScopeRequest,
)
from app.services.project.errors import ProjectServiceError


class TagsMixin:
    def read_known_tags(self) -> KnownTags:
        root = self._require_project()
        data = self._read_yaml(root / "tags.yaml")
        raw_tags = data.get("tags", [])
        if not isinstance(raw_tags, list):
            raise ProjectServiceError("tags.yaml tags must be a list.", 422)
        by_lower: dict[str, ScopedTag] = {}
        for raw in raw_tags:
            # Defensive: accept both the legacy flat shape (bare string) and
            # the scoped shape ({name, scope}).
            if isinstance(raw, str):
                name = raw.strip()
                scope = NodePickerConfig()
            elif isinstance(raw, dict):
                name = str(raw.get("name", "")).strip()
                try:
                    scope = NodePickerConfig.model_validate(raw.get("scope") or {})
                except Exception:  # noqa: BLE001
                    scope = NodePickerConfig()
            else:
                continue
            if not name:
                continue
            key = name.lower()
            if key in by_lower:
                by_lower[key].scope = self._union_node_picker_scope(by_lower[key].scope, scope)
            else:
                by_lower[key] = ScopedTag(name=name, scope=scope)
        tags = sorted(by_lower.values(), key=lambda tag: tag.name.lower())
        return KnownTags(tags=tags)

    def _tag_scope_for_node(self, kind: str, entry_type: str) -> NodePickerConfig:
        return NodePickerConfig(
            kinds=[kind] if kind else [],
            entry_types={kind: [entry_type]} if (kind and entry_type) else {},
        )

    def _union_node_picker_scope(self, a: NodePickerConfig, b: NodePickerConfig) -> NodePickerConfig:
        kinds = list(dict.fromkeys([*a.kinds, *b.kinds]))
        entry_types: dict[str, list[str]] = {}
        for source in (a.entry_types, b.entry_types):
            for kind, subs in source.items():
                bucket = entry_types.setdefault(kind, [])
                for sub in subs:
                    if sub not in bucket:
                        bucket.append(sub)
        return NodePickerConfig(kinds=kinds, entry_types=entry_types)

    def _write_scoped_tags(self, tags: list[ScopedTag]) -> None:
        root = self._require_project()
        ordered = sorted(tags, key=lambda tag: tag.name.lower())
        self._write_yaml(
            root / "tags.yaml",
            {"tags": [{"name": tag.name, "scope": tag.scope.model_dump(exclude_none=True)} for tag in ordered]},
        )

    def read_tags_overview(self) -> TagsOverview:
        root = self._require_project()
        schema = self.read_metadata_schema()
        tags_fields = {fid for fid, field in schema.fields.items() if field.type == "tags"}
        counts: dict[str, int] = {}
        display: dict[str, str] = {}
        for path in self._entry_markdown_paths(root):
            try:
                front_matter, _ = self._read_markdown_with_front_matter(path, strict=False)
            except ProjectServiceError:
                continue
            metadata = front_matter.get("metadata")
            if not isinstance(metadata, dict):
                continue
            for field_id, value in metadata.items():
                if field_id not in tags_fields or not isinstance(value, list):
                    continue
                for raw in value:
                    if not isinstance(raw, str):
                        continue
                    tag = raw.strip()
                    if not tag:
                        continue
                    key = tag.lower()
                    counts[key] = counts.get(key, 0) + 1
                    display.setdefault(key, tag)
        known = {tag.name.lower(): tag for tag in self.read_known_tags().tags}
        usages: list[TagUsage] = []
        for key in set(counts) | set(known):
            scoped = known.get(key)
            usages.append(
                TagUsage(
                    name=scoped.name if scoped else display.get(key, key),
                    scope=scoped.scope if scoped else NodePickerConfig(),
                    count=counts.get(key, 0),
                )
            )
        usages.sort(key=lambda usage: usage.name.lower())
        return TagsOverview(tags=usages)

    def update_tag_scope(self, request: UpdateTagScopeRequest) -> KnownTags:
        self._require_project()
        name = request.name.strip()
        if not name:
            raise ProjectServiceError("Tag name is required.", 422)
        by_lower = {tag.name.lower(): tag for tag in self.read_known_tags().tags}
        existing = by_lower.get(name.lower())
        by_lower[name.lower()] = ScopedTag(name=existing.name if existing else name, scope=request.scope)
        self._write_scoped_tags(list(by_lower.values()))
        return self.read_known_tags()

    def merge_tags(self, request: MergeTagsRequest) -> KnownTags:
        root = self._require_project()
        target = request.target.strip()
        if not target:
            raise ProjectServiceError("A name for the merged tag is required.", 422)
        sources = [source.strip() for source in request.sources if source.strip()]
        if not sources:
            raise ProjectServiceError("Pick at least one tag to merge.", 422)
        source_lowers = {source.lower() for source in sources if source.lower() != target.lower()}

        # 1. Rewrite tag values across all node files on disk.
        schema = self.read_metadata_schema()
        tags_fields = {fid for fid, field in schema.fields.items() if field.type == "tags"}
        for path in self._entry_markdown_paths(root):
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            metadata = front_matter.get("metadata")
            if not isinstance(metadata, dict):
                continue
            changed = False
            for field_id, value in list(metadata.items()):
                if field_id not in tags_fields or not isinstance(value, list):
                    continue
                next_values: list[Any] = []
                seen: set[str] = set()
                for raw in value:
                    if not isinstance(raw, str):
                        next_values.append(raw)
                        continue
                    replaced = target if raw.strip().lower() in source_lowers else raw
                    key = replaced.strip().lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    next_values.append(replaced)
                if next_values != value:
                    metadata[field_id] = next_values
                    changed = True
            if changed:
                front_matter["metadata"] = metadata
                self._write_markdown_with_front_matter(path, front_matter, body)

        # 2. Union the source scopes (+ existing target) into the target; drop sources.
        by_lower = {tag.name.lower(): tag for tag in self.read_known_tags().tags}
        union = by_lower[target.lower()].scope if target.lower() in by_lower else NodePickerConfig()
        for source in sources:
            scoped = by_lower.get(source.lower())
            if scoped:
                union = self._union_node_picker_scope(union, scoped.scope)
        for source_lower in source_lowers:
            by_lower.pop(source_lower, None)
        by_lower[target.lower()] = ScopedTag(name=target, scope=union)
        self._write_scoped_tags(list(by_lower.values()))
        return self.read_known_tags()
