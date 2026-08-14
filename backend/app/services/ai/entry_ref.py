"""EntryRef — the lazy, auto-resolving entry wrapper for Jinja templates.

Extracted from `helpers.py` (it crossed the 1500-line file-size cap): a single
cohesive unit — the wrapper `entry()` / `_coerce_entry_ref` hand to templates,
plus its metadata view. `helpers.py` imports `EntryRef` back; nothing else here
is part of the public surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
            if idx_entry.kind == "lore":
                self._loaded = self._project.read_lore_entry(self._id)
            elif idx_entry.kind == "scene":
                self._loaded = self._project.read_scene(self._id)
            elif idx_entry.kind == "prompt":
                self._loaded = self._project.read_prompt_entry(self._id)
            elif idx_entry.kind == "research":
                self._loaded = self._project.read_research_note(self._id)
            elif idx_entry.kind == "plot":
                # A plot node — card or plotline — is a first-class Node a prompt
                # can pull in (revise-plot-card / revise-plotline). Board and
                # template are not revisable subjects, so they stay unresolved.
                if idx_entry.entry_type == "plot:plotline":
                    self._loaded = self._project.read_plotline(self._id)
                elif idx_entry.entry_type == "plot:card":
                    self._loaded = self._project.read_card(self._id)
                else:
                    self._loaded = _MISSING
            else:
                self._loaded = _MISSING
        except Exception:
            self._loaded = _MISSING
        return None if self._loaded is _MISSING else self._loaded

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
        return self.metadata.get(name)

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
        if field_type == "entity_ref" and isinstance(value, str) and value:
            return EntryRef(self._project, self._schema, value, depth=self._depth)
        if field_type == "entity_ref_list" and isinstance(value, list):
            return [
                EntryRef(self._project, self._schema, v, depth=self._depth)
                for v in value
                if isinstance(v, str) and v
            ]
        return value

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
