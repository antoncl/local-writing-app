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

from pathlib import Path
from typing import Any

from app.models import (
    KnownTags,
    MergeTagsRequest,
    NodePickerConfig,
    ScopedTag,
    TagLayerRef,
    TagsOverview,
    TagUsage,
    UpdateTagScopeRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.layers import LayerVisitor
from app.services.project.node_index import IndexLayer


class _TagRegistryMerger(LayerVisitor):
    """Folds each layer's `tags.yaml` into one merged registry (#339).

    Tags **union**, they do not shadow — the same name may be asserted at world,
    series and book with different scopes and the merged record is the union of
    all of them, stamped with every asserting layer. That is why this is a
    bespoke visitor rather than `collect_layers` + a comprehension: there is real
    per-layer work.

    `up_to_layer_id` truncates the walk at an *authoring level* L: layers **below**
    L are dropped, layers above it are not. The vocabulary visible at L is the
    full ancestor union base → L, so world tags are offered at every dropdown
    position — a series-targeted write must not be able to use vocabulary that
    exists only at the book. Truncation reaches down, never up.
    """

    def __init__(self, owner: TagsMixin, *, up_to_layer_id: str | None = None) -> None:
        self._owner = owner
        self._up_to_layer_id = up_to_layer_id
        self._stopped = False
        self.saw_target = up_to_layer_id is None
        self.by_lower: dict[str, ScopedTag] = {}

    def visit_layer(self, layer: IndexLayer) -> None:
        if self._stopped:
            return
        for tag in self._owner._read_layer_tags(layer.folder).values():
            key = tag.name.lower()
            existing = self.by_lower.get(key)
            ref = TagLayerRef(id=layer.id, label=layer.label)
            if existing is None:
                # First-seen casing wins, and the walk runs outermost → root, so
                # casing is owned by the layer that introduced the tag: it stays
                # stable as descendants are added, and a book's typo cannot
                # restyle the world's vocabulary. Deliberately the inverse of the
                # schema merge's nearer-wins — tags union rather than shadow.
                self.by_lower[key] = ScopedTag(name=tag.name, scope=tag.scope, source_layers=[ref])
            else:
                existing.scope = self._owner._union_node_picker_scope(existing.scope, tag.scope)
                existing.source_layers.append(ref)
        if self._up_to_layer_id is not None and layer.id == self._up_to_layer_id:
            self.saw_target = True
            self._stopped = True


class TagsMixin:
    def read_known_tags(self, *, up_to_layer_id: str | None = None) -> KnownTags:
        """The merged vocabulary, ancestors unioned into the open project (#339).

        `up_to_layer_id` reads as of an authoring level instead of the open
        project — see `_TagRegistryMerger`. The result carries `source_layers`
        provenance; a single layer's own records are `_read_layer_tags`.
        """
        root = self._require_project()
        merger = _TagRegistryMerger(self, up_to_layer_id=up_to_layer_id)
        self.visit_layers(merger, root)
        if not merger.saw_target:
            raise ProjectServiceError(f"Unknown layer {up_to_layer_id}.", 404)
        tags = sorted(merger.by_lower.values(), key=lambda tag: tag.name.lower())
        return KnownTags(tags=tags)

    def _read_layer_tags(self, folder: Path) -> dict[str, ScopedTag]:
        """One layer's own `tags.yaml`, keyed by lowercased name — what that
        layer asserted, never the resolved scope.

        The writers need this as well as the merged view: merged answers "is this
        tag known?", layer-owned is what may be written back. Handing a writer the
        merged map is how a layered read turns into a flattener.
        """
        data = self._read_yaml(folder / "tags.yaml")
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
        return by_lower

    def _tag_scope_for_node(self, kind: str, entry_type: str) -> NodePickerConfig:
        # A tag scope stays a degenerate type-leaf ViewSpec (ADR-0023): the
        # `.kinds` / `.entry_types` accessors read it back for auto-broadening.
        return NodePickerConfig.from_membership(
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
        return NodePickerConfig.from_membership(kinds=kinds, entry_types=entry_types)

    def _subtract_node_picker_scope(self, scope: NodePickerConfig, covered: NodePickerConfig) -> NodePickerConfig:
        """What `scope` asserts that `covered` does not — the local delta.

        The counterpart to `_union_node_picker_scope`, and the reason a writer can
        record a layer's own assertion rather than the resolved scope: a resolved
        scope written locally re-asserts the ancestor's membership here forever,
        so the ancestor could later narrow or drop the tag and this layer would
        still be claiming what the ancestor used to say.

        An empty sub-type list means "all sub-types of this kind", on either side:
        covered-by-all drops the kind; asserting-all minus a partial restriction
        is not expressible in this vocabulary, so the kind survives whole (the
        conservative direction — it over-asserts locally rather than losing
        membership the author asked for).
        """
        kinds: list[str] = []
        entry_types: dict[str, list[str]] = {}
        covered_kinds = set(covered.kinds)
        for kind in scope.kinds:
            subs = list(scope.entry_types.get(kind, []))
            covered_subs = list(covered.entry_types.get(kind, []))
            if kind in covered_kinds:
                if not covered_subs:
                    continue
                if subs:
                    subs = [sub for sub in subs if sub not in covered_subs]
                    if not subs:
                        continue
            kinds.append(kind)
            if subs:
                entry_types[kind] = subs
        return NodePickerConfig.from_membership(kinds=kinds, entry_types=entry_types)

    def _layered_entry_markdown_paths(self, root: Path) -> list[Path]:
        """Every layer's scene/lore files, outermost first — `_entry_markdown_paths`
        run over the walk instead of the open project alone."""
        return [
            path
            for layer in self.collect_layers(root)
            for path in self._entry_markdown_paths(layer.folder)
        ]

    def _scope_covers(self, outer: NodePickerConfig, inner: NodePickerConfig) -> bool:
        """Does `outer` already suggest everywhere `inner` does?

        An empty scope means "suggest everywhere", so it covers everything and is
        covered only by another empty scope.
        """
        outer_kinds, inner_kinds = set(outer.kinds), set(inner.kinds)
        if not outer_kinds:
            return True
        if not inner_kinds:
            return False
        if not inner_kinds <= outer_kinds:
            return False
        for kind in inner_kinds:
            # An empty sub-type list for a whitelisted kind means "all sub-types"
            # — on *either* side. Empty outer covers anything; empty inner is
            # covered only by an empty outer.
            outer_subs = set(outer.entry_types.get(kind, []))
            inner_subs = set(inner.entry_types.get(kind, []))
            if not outer_subs:
                continue
            if not inner_subs or not inner_subs <= outer_subs:
                return False
        return True

    def _write_scoped_tags(self, tags: list[ScopedTag], *, folder: Path | None = None) -> None:
        """Write one layer's registry. `folder` defaults to the open project.

        ⚠ `tags` must be that layer's **own** assertions, never a merged read —
        this rewrites the whole file, so handing it a merged registry flattens
        every ancestor's vocabulary into the target layer. #313 passes the layer
        the ADR-0042 dropdown selected; nothing in #339 passes anything else.
        """
        target = folder if folder is not None else self._require_project()
        ordered = sorted(tags, key=lambda tag: tag.name.lower())
        self._write_yaml(
            target / "tags.yaml",
            {"tags": [{"name": tag.name, "scope": tag.scope.model_dump(exclude_none=True)} for tag in ordered]},
        )

    def _ancestor_document_tags(self, root: Path) -> set[str]:
        """Lowercased tag names carried by documents in layers *above* the open
        project — the ones a merge or rename here cannot reach."""
        paths = [
            path
            for layer in self.collect_layers(root)
            if layer.folder != root
            for path in self._entry_markdown_paths(layer.folder)
        ]
        return set(self._count_document_tags(paths)[0])

    def _count_document_tags(self, paths: list[Path]) -> tuple[dict[str, int], dict[str, str]]:
        """Occurrences per lowercased tag name across `paths`, plus first-seen
        display casing. Shared by the overview and the merge bound so the count
        the author sees and the set the guard enforces cannot drift apart."""
        schema = self.read_metadata_schema()
        tags_fields = {fid for fid, field in schema.fields.items() if field.type == "tags"}
        counts: dict[str, int] = {}
        display: dict[str, str] = {}
        for path in paths:
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
        return counts, display

    def read_tags_overview(self) -> TagsOverview:
        root = self._require_project()
        # Counted over the same walk as the registry read (#339). Counting only
        # the open project's documents against a merged registry is a half-layered
        # read: every inherited tag would report as less used than it is, and an
        # ancestor-only tag as unused.
        counts, display = self._count_document_tags(self._layered_entry_markdown_paths(root))
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
        root = self._require_project()
        name = request.name.strip()
        if not name:
            raise ProjectServiceError("Tag name is required.", 422)
        key = name.lower()
        merged = {tag.name.lower(): tag for tag in self.read_known_tags().tags}
        local = self._read_layer_tags(root)

        # Broaden-only for inherited tags (#339). Scope composes by union, so a
        # narrower local record cannot shadow an ancestor's — the write would
        # simply have no effect on the next read. Fail loudly rather than accept
        # it; `TagManagerDialog` has no layer selector, so the author has no way
        # to see why nothing changed.
        inherited = self._inherited_tag_scope(root, key)
        if inherited is not None and not self._scope_covers(request.scope, inherited):
            raise ProjectServiceError(
                f"Tag {name} is also defined in a parent folder; its scope can be widened here, not narrowed.",
                422,
            )

        existing = merged.get(key) or local.get(key)
        if inherited is None:
            local[key] = ScopedTag(name=existing.name if existing else name, scope=request.scope)
        else:
            # The request carries the RESOLVED scope (the dialog seeds its draft
            # from the merged overview), but only the part this layer adds may be
            # recorded — otherwise every scope edit copies the ancestor's
            # assertion down, and the ancestor could later narrow or drop the tag
            # while this layer went on claiming what it used to say. The guard
            # above means the request always covers `inherited`, so the delta is
            # exactly the widening the author asked for.
            delta = self._subtract_node_picker_scope(request.scope, inherited)
            if delta.kinds:
                local[key] = ScopedTag(name=existing.name if existing else name, scope=delta)
            else:
                # Fully covered by inheritance — this layer asserts nothing.
                local.pop(key, None)
        self._write_scoped_tags(list(local.values()))
        return self.read_known_tags()

    def _inherited_tag_scope(self, root: Path, key: str) -> NodePickerConfig | None:
        """The union of every *ancestor* layer's assertion of `key`, or None when
        only the open project asserts it."""
        inherited: NodePickerConfig | None = None
        for layer in self.collect_layers(root):
            if layer.folder == root:
                continue
            tag = self._read_layer_tags(layer.folder).get(key)
            if tag is None:
                continue
            inherited = tag.scope if inherited is None else self._union_node_picker_scope(inherited, tag.scope)
        return inherited

    def _reject_sources_above_this_layer(self, root: Path, sources: list[str]) -> None:
        """A rename may only rewrite records and documents at or below the
        authoring level (#339) — reaching higher is what ADR-0042's dropdown
        forbids. L is the open project until #313 wires the dropdown.

        The bound covers documents as well as records: a source with no ancestor
        *record* may still be carried by ancestor *documents*, which this merge
        cannot rewrite. The tag would survive the rename, keep a usage count in
        the (now layered) overview, and be re-registered as new by the next save
        that touches one of those entries. This is the rule, not a stopgap.
        """
        ancestor_tags = self._ancestor_document_tags(root)
        blocked = sorted(
            source
            for source in sources
            if self._inherited_tag_scope(root, source.lower()) is not None
            or source.lower() in ancestor_tags
        )
        if blocked:
            raise ProjectServiceError(
                f"{', '.join(blocked)} is used in a parent folder and cannot be merged from here.",
                422,
            )

    def _rename_tag_in_documents(self, paths: list[Path], source_lowers: set[str], target: str) -> None:
        """Replace every occurrence of `source_lowers` with `target` in the tags
        fields of `paths`, de-duplicating the result."""
        schema = self.read_metadata_schema()
        tags_fields = {fid for fid, field in schema.fields.items() if field.type == "tags"}
        for path in paths:
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            metadata = front_matter.get("metadata")
            if not isinstance(metadata, dict):
                continue
            changed = False
            for field_id, value in list(metadata.items()):
                if field_id not in tags_fields or not isinstance(value, list):
                    continue
                next_values = self._rename_tag_in_value(value, source_lowers, target)
                if next_values != value:
                    metadata[field_id] = next_values
                    changed = True
            if changed:
                front_matter["metadata"] = metadata
                self._write_markdown_with_front_matter(path, front_matter, body)

    def _rename_tag_in_value(self, value: list[Any], source_lowers: set[str], target: str) -> list[Any]:
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
        return next_values

    def merge_tags(self, request: MergeTagsRequest) -> KnownTags:
        root = self._require_project()
        target = request.target.strip()
        if not target:
            raise ProjectServiceError("A name for the merged tag is required.", 422)
        sources = [source.strip() for source in request.sources if source.strip()]
        if not sources:
            raise ProjectServiceError("Pick at least one tag to merge.", 422)
        source_lowers = {source.lower() for source in sources if source.lower() != target.lower()}

        self._reject_sources_above_this_layer(root, sources)

        # 1. Rewrite tag values across this layer's node files on disk.
        self._rename_tag_in_documents(self._entry_markdown_paths(root), source_lowers, target)

        # 2. Union the source scopes (+ existing target) into the target; drop
        #    sources. Read merged for the scopes, write back only this layer's
        #    own records — writing the merged map here would flatten every
        #    ancestor's vocabulary into the open project's tags.yaml.
        #    The target may itself be inherited, so seed the union from this
        #    layer's own record, never the merged one: seeding from merged would
        #    make this layer assert a scope the ancestor authored. The sources are
        #    guaranteed local-only by the guard above, so their local scopes are
        #    the whole story.
        local = self._read_layer_tags(root)
        union = local[target.lower()].scope if target.lower() in local else NodePickerConfig()
        for source in sources:
            scoped = local.get(source.lower())
            if scoped:
                union = self._union_node_picker_scope(union, scoped.scope)
        for source_lower in source_lowers:
            local.pop(source_lower, None)
        local[target.lower()] = ScopedTag(name=target, scope=union)
        self._write_scoped_tags(list(local.values()))
        return self.read_known_tags()
