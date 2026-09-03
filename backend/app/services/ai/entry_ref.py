"""EntryRef — the lazy, auto-resolving entry wrapper for Jinja templates.

Extracted from `helpers.py` (it crossed the 1500-line file-size cap): a single
cohesive unit — the wrapper `entry()` / `_coerce_entry_ref` hand to templates,
plus its metadata view. `helpers.py` imports `EntryRef` back; nothing else here
is part of the public surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.project.metadata_refs import ref_members

if TYPE_CHECKING:
    from app.services.project_service import ProjectService


# ----- EntryRef: lazy auto-resolving entry wrapper ------------------------

# Defensive depth limit. Real-world chains are bounded by the ancestor folder
# walk and the field graph; this just prevents pathological link cycles from
# blowing the context.
_ENTRY_REF_MAX_DEPTH = 6
_MISSING = object()


class EntryRef:
    """Lazy wrapper around a lore / scene / prompt entry inside Jinja templates.

    `.id` and `.raw_id` return the underlying string without resolving.
    Any other attribute (e.g. `.title`, `.entry_type`, `.body`,
    `.metadata`) lazily loads the target entry through the project's layered
    node index. Inside `.metadata`, `entity_ref` fields auto-wrap to EntryRef
    and `entity_ref_list` fields to `list[EntryRef]`, with per-render cycle
    detection so a self-referential graph cannot loop forever.

    `str(ref)` renders as the entry's title (or the raw id if missing) so
    `{{ honor }}` works directly in templates.
    """

    __slots__ = ("_project", "_schema", "_id", "_depth", "_loaded")

    def __init__(
        self,
        project: ProjectService,
        schema: Any,
        entry_id: str,
        *,
        depth: int = 0,
        loaded: Any = None,
    ) -> None:
        self._project = project
        self._schema = schema
        self._id = str(entry_id)
        self._depth = depth
        # `loaded` lets a caller hand in the already-read entry (e.g. the
        # build_preview path already holds the target Scene). Skips a wasted
        # re-read on the first attribute access.
        self._loaded: Any = loaded

    @property
    def id(self) -> str:
        return self._id

    @property
    def raw_id(self) -> str:
        return self._id

    @property
    def found(self) -> bool:
        return self._load() is not None

    def _load(self) -> Any:
        if self._loaded is not None:
            return None if self._loaded is _MISSING else self._loaded
        # Depth limit catches unbounded recursive walkers. Authors writing
        # `a.b.c.d` chains by hand stay well below this.
        if self._depth >= _ENTRY_REF_MAX_DEPTH:
            self._loaded = _MISSING
            return None
        try:
            index = self._project._build_node_index()
        except Exception:
            self._loaded = _MISSING
            return None
        idx_entry = index.by_id.get(self._id)
        if idx_entry is None:
            self._loaded = _MISSING
            return None
        try:
            self._loaded = self._read_by_kind(idx_entry)
        except Exception:
            self._loaded = _MISSING
        return None if self._loaded is _MISSING else self._loaded

    def _read_by_kind(self, idx_entry: Any) -> Any:
        """Resolve the node behind this ref via the reader for its kind, or
        `_MISSING` for kinds/entry_types that aren't a resolvable subject.
        """
        kind = idx_entry.kind
        if kind == "lore":
            return self._project.read_lore_entry(self._id)
        if kind == "manuscript":
            return self._project.read_scene(self._id)
        if kind == "prompt":
            return self._project.read_prompt_entry(self._id)
        if kind == "research":
            return self._project.read_research_note(self._id)
        if kind == "plot":
            # A plot node — card or plotline — is a first-class Node a prompt
            # can pull in (revise-plot-card / revise-plotline). Board and
            # template are not revisable subjects, so they stay unresolved.
            if idx_entry.entry_type == "plot:plotline":
                return self._project.read_plotline(self._id)
            if idx_entry.entry_type == "plot:card":
                return self._project.read_card(self._id)
            return _MISSING
        return _MISSING

    @property
    def title(self) -> str:
        entry = self._load()
        if entry is None:
            return self._id
        return str(getattr(entry, "title", "") or self._id)

    @property
    def entry_type(self) -> str:
        entry = self._load()
        if entry is None:
            return ""
        return str(getattr(entry, "entry_type", "") or "")

    @property
    def body(self) -> str:
        entry = self._load()
        if entry is None:
            return ""
        return str(getattr(entry, "body", "") or "")

    @property
    def metadata(self) -> _EntryMetadataView:
        entry = self._load()
        data = getattr(entry, "metadata", None) if entry is not None else None
        return _EntryMetadataView(
            data if isinstance(data, dict) else {},
            project=self._project,
            schema=self._schema,
            depth=self._depth + 1,
        )

    def __getattr__(self, name: str) -> Any:
        # Final fallback: treat unknown attribute as a metadata key. Lets
        # templates write `{{ honor.home_planet.title }}` instead of
        # `{{ honor.metadata.home_planet.title }}`. `__slots__` keeps real
        # attributes out of this path.
        if name.startswith("_"):
            raise AttributeError(name)
        return self._resolve(name)

    def __getitem__(self, key: str) -> Any:
        # Subscript mirrors attribute access, so a group / field whose label is
        # not a Python identifier stays reachable: `entry["Antagonist GMO"].Goal`.
        return self._resolve(str(key))

    def _resolve(self, name: str) -> Any:
        # A set field wins (backward compatible — `e.home_planet`), then a group
        # label (`e.GMO` → a view over the fields tagged with that section label,
        # so `e.GMO.Goal` reads a member #784), then a bare metadata read (None
        # for an unset / unknown field, as before).
        md = self.metadata
        if name in md:
            return md.get(name)
        group = self._group_view(name)
        if group is not None:
            return group
        return md.get(name)

    def _group_view(self, name: str) -> Any:
        """A view over the fields whose section label is `name`, or None.

        Lets a template read a group's members as `entry.GMO.Goal` — the group by
        the label it was designed with, each member by its field name (or id).
        None when the entry's type has no field in a group of that label, so the
        caller falls through to a plain field read (#784)."""
        if self._schema is None:
            return None
        entry_type = self.entry_type
        definition = self._schema.entry_types.get(entry_type) if entry_type else None
        if definition is None:
            return None
        members = [
            (field_id, field_def)
            for field_id in definition.fields
            if (field_def := self._schema.fields.get(field_id)) is not None
            and getattr(field_def, "group", None) == name
        ]
        return _GroupView(self, members) if members else None

    def __str__(self) -> str:
        return self.title or self._id

    def __bool__(self) -> bool:
        return bool(self._id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, EntryRef):
            return self._id == other._id
        return NotImplemented

    def __hash__(self) -> int:
        return hash(("EntryRef", self._id))

    def __repr__(self) -> str:
        return f"<EntryRef {self._id!r}>"


class _GroupView:
    """A view over one node's fields that share a section label (#784).

    Returned by `EntryRef.<group label>` (or `["…"]`). A member is read by its
    field name or its id — `entry.GMO.Goal` and `entry.GMO.goal` both resolve —
    reusing the owning `EntryRef.metadata` read, so an `entity_ref` member wraps
    to an `EntryRef` like any field. An unknown member is None (subscript raises
    KeyError, the mapping convention). Iterating yields the member ids.
    """

    __slots__ = ("_ref", "_members")

    def __init__(self, ref: EntryRef, members: list[tuple[str, Any]]) -> None:
        self._ref = ref
        self._members = members

    def _value(self, name: str, default: Any = None) -> Any:
        for field_id, field_def in self._members:
            if field_id == name or getattr(field_def, "name", None) == name:
                return self._ref.metadata.get(field_id)
        return default

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._value(name)

    def __getitem__(self, key: str) -> Any:
        value = self._value(str(key), default=_MISSING)
        if value is _MISSING:
            raise KeyError(key)
        return value

    def __contains__(self, key: object) -> bool:
        return any(
            field_id == key or getattr(field_def, "name", None) == key
            for field_id, field_def in self._members
        )

    def __iter__(self):
        return (field_id for field_id, _ in self._members)

    def __len__(self) -> int:
        return len(self._members)

    def __bool__(self) -> bool:
        return bool(self._members)


class _EntryMetadataView:
    """Dict-like view over an entry's metadata.

    Returned by `EntryRef.metadata`. Iteration / `.items()` / `.keys()` /
    `.values()` work like a normal mapping; item or attribute access wraps
    `entity_ref` fields as EntryRef on demand. `entity_ref_list` fields wrap
    to `list[EntryRef]`. Other fields pass through.
    """

    __slots__ = ("_data", "_project", "_schema", "_depth")

    def __init__(
        self,
        data: dict[str, Any],
        *,
        project: ProjectService,
        schema: Any,
        depth: int,
    ) -> None:
        self._data = data
        self._project = project
        self._schema = schema
        self._depth = depth

    def _wrap(self, key: str, value: Any) -> Any:
        if value is None or self._schema is None:
            return value
        field_def = getattr(self._schema, "fields", {}).get(key)
        if field_def is None:
            return value
        field_type = getattr(field_def, "type", None)
        if field_type in ("entity_ref", "entity_ref_list"):
            return self._wrap_ref(field_type, value)
        if field_type == "list" and isinstance(value, list):
            # A group-list (ADR-0081 §4): wrap the ref members inside each item so
            # `entry.cast[0].who.name` resolves the target like a top-level ref.
            members = ref_members(field_def)
            if members:
                return [self._wrap_list_item(item, members) for item in value]
        return value

    def _wrap_ref(self, field_type: Any, value: Any) -> Any:
        """Wrap an ``entity_ref`` / ``entity_ref_list`` value into ``EntryRef``(s)
        so a template reads the target's fields; pass any other value through.
        Shared by top-level fields and item_group members."""
        if field_type == "entity_ref" and isinstance(value, str) and value:
            return EntryRef(self._project, self._schema, value, depth=self._depth)
        if field_type == "entity_ref_list" and isinstance(value, list):
            return [
                EntryRef(self._project, self._schema, v, depth=self._depth)
                for v in value
                if isinstance(v, str) and v
            ]
        return value

    def _wrap_list_item(self, item: Any, members: dict[str, Any]) -> Any:
        """A group-list item with its ref members wrapped to ``EntryRef``(s). A
        ``tags`` member (also in ``members``) passes through — tags aren't entity
        refs, same as at the top level; a non-dict item passes through untouched."""
        if not isinstance(item, dict):
            return item
        wrapped = dict(item)
        for member_key, member_field in members.items():
            if member_key in wrapped:
                wrapped[member_key] = self._wrap_ref(member_field.type, wrapped[member_key])
        return wrapped

    def __getitem__(self, key: str) -> Any:
        if key not in self._data:
            raise KeyError(key)
        return self._wrap(key, self._data[key])

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            raise AttributeError(key)
        return self._wrap(key, self._data.get(key))

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._data:
            return self._wrap(key, self._data[key])
        return default

    def keys(self):
        return self._data.keys()

    def values(self):
        return [self._wrap(k, v) for k, v in self._data.items()]

    def items(self):
        return [(k, self._wrap(k, v)) for k, v in self._data.items()]


class ProjectInfoRef:
    """Template-facing wrapper over `ProjectInfo` (ADR-0060 §3).

    Gives the project node the same `node.<field>` access `EntryRef` gives
    entries: `project.<field>` reads the project's authored metadata, `.metadata`
    stays the explicit whole-map escape, and the model's own intrinsics
    (`title`, `root_path`, …) win a name collision. `entity_ref` metadata fields
    wrap to `EntryRef` through the shared `_EntryMetadataView`, so a project-level
    reference resolves the same way an entry's does.
    """

    __slots__ = ("_info", "_project", "_schema")

    def __init__(self, info: Any, *, project: ProjectService, schema: Any) -> None:
        self._info = info
        self._project = project
        self._schema = schema

    @property
    def metadata(self) -> _EntryMetadataView:
        data = getattr(self._info, "metadata", None)
        return _EntryMetadataView(
            data if isinstance(data, dict) else {},
            project=self._project,
            schema=self._schema,
            depth=1,
        )

    def __getattr__(self, name: str) -> Any:
        # `__slots__` plus this fallback: the real slots and the `metadata`
        # property resolve through normal lookup; every other attribute lands
        # here. An intrinsic on the wrapped model wins (the node.<field> rule),
        # then the metadata fallback lets `{{ project.measurement_system }}`
        # resolve to a value an ancestor layer authored.
        if name.startswith("_"):
            raise AttributeError(name)
        info = self._info
        if info is not None and hasattr(info, name):
            return getattr(info, name)
        return self.metadata.get(name)

    def __bool__(self) -> bool:
        return self._info is not None
