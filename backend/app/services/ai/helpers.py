"""Template helpers — functions registered into the Jinja2 sandbox.

Two kinds of helpers:

- **Pure helpers** (`last_words`) need no project state and are always available.
- **Project-bound helpers** (`pov`, `scenes_before`, `relevant_lore`) need to
  look up nodes, walk the reference graph, or read prior scenes. They are
  registered by `register_helpers(env, project_service)` against a specific
  project.

Helpers return either strings (which render directly via `{{ helper(...) }}`)
or dicts (which support both attribute-style and key-style access in Jinja).
Pydantic node objects are never returned directly — templates should not
depend on the Pydantic API surface.

Sandbox notes:
- Sandboxed attribute access already blocks dunders. Returning dicts means
  templates can safely use `{{ pov(scene).title }}` or `{{ pov(scene)['title'] }}`.
"""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING
from xml.sax.saxutils import escape as xml_escape, quoteattr

from jinja2.sandbox import SandboxedEnvironment

from app.services.ai.sessions import AISession

if TYPE_CHECKING:
    from app.services.project_service import ProjectService

VALID_PARTITIONS = {"all", "stable", "volatile"}

# Word splitter — same shape as project_service.WORD_PATTERN. Splitting on
# whitespace is a fine approximation for `last_words`.
_WS = re.compile(r"\s+")


# ----- Pure helpers --------------------------------------------------------


def last_words(text: Any, n: Any) -> str:
    """Return the trailing `n` words of `text`.

    - Empty / None text → "".
    - `n <= 0` → "".
    - If text has ≤ n words, the whole text is returned with its original
      whitespace preserved.
    """
    if text is None:
        return ""
    text_str = str(text)
    try:
        n_int = int(n)
    except (TypeError, ValueError):
        return ""
    if n_int <= 0 or not text_str.strip():
        return ""
    words = _WS.split(text_str.strip())
    if len(words) <= n_int:
        return text_str
    return " ".join(words[-n_int:])


# ----- EntryRef: lazy auto-resolving entry wrapper ------------------------

# Defensive depth limit. Real-world chains are bounded by the ancestor folder
# walk and the field graph; this just prevents pathological link cycles from
# blowing the context.
_ENTRY_REF_MAX_DEPTH = 6
_MISSING = object()


class EntryRef:
    """Lazy wrapper around a lore / scene / prompt entry inside Jinja templates.

    `.id` and `.raw_id` return the underlying string without resolving.
    Any other attribute (e.g. `.title`, `.entry_type`, `.body_markdown`,
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
        project: "ProjectService",
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
    def body_markdown(self) -> str:
        entry = self._load()
        if entry is None:
            return ""
        return str(getattr(entry, "body_markdown", "") or "")

    @property
    def metadata(self) -> "_EntryMetadataView":
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
        project: "ProjectService",
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


def _coerce_entry_ref(
    project: "ProjectService", schema: Any, value: Any
) -> EntryRef | None:
    """Helper backing the `entry()` Jinja global.

    Accepts a string id, an EntryRef (returns it unchanged), or an object with
    an `.id` attribute. Returns None for anything else.
    """
    if value is None or value == "":
        return None
    if isinstance(value, EntryRef):
        return value
    if isinstance(value, str):
        return EntryRef(project, schema, value)
    inner = getattr(value, "id", None)
    if isinstance(inner, str) and inner:
        return EntryRef(project, schema, inner)
    return None


# ----- Project-bound helpers ----------------------------------------------


def register_helpers(
    env: SandboxedEnvironment,
    project: "ProjectService",
    session: AISession | None = None,
    journal: list[Any] | None = None,
) -> None:
    """Bind project-aware helpers to the given env. Idempotent.

    If `session` is provided, `relevant_lore(..., partition="stable"|"volatile")`
    becomes meaningful — entries' revisions are snapshotted into the session
    and partitioned against its baseline.

    If `journal` is provided (a list of ChatSessionJournalEntry), the
    implicit mode of `relevant_lore` treats the journal as the source of
    truth for textual detection: it skips its own alias scan and depth-1
    textual expansion. The send-time pipeline is the single producer of
    detected context for chat sessions; the helper becomes a read of what
    that pipeline already deposited. Structural entity_ref expansion from
    the scene's own metadata still runs — those are template-author
    explicit picks the send pipeline doesn't see.
    """
    try:
        schema = project.read_metadata_schema()
    except Exception:
        schema = None

    env.globals["last_words"] = last_words
    env.globals["pov"] = lambda scene: _pov(project, schema, scene)
    env.globals["scenes_before"] = lambda scene: _scenes_before(project, scene)
    env.globals["relevant_lore"] = (
        lambda scene, mode="implicit", partition="all": _relevant_lore(
            project, scene, mode, partition, session, journal
        )
    )
    env.globals["entry"] = lambda value: _coerce_entry_ref(project, schema, value)
    env.globals["full_outline"] = lambda: _full_outline(project)
    env.globals["full_text"] = lambda: _full_text(project)


def create_environment_for_project(
    project: "ProjectService",
    session: AISession | None = None,
    journal: list[Any] | None = None,
) -> SandboxedEnvironment:
    """Convenience: env with extensions and project helpers registered."""
    from app.services.ai.templates import create_environment

    env = create_environment()
    register_helpers(env, project, session, journal)
    return env


# ----- Internal: data access -----------------------------------------------


def _get_field(node: Any, key: str) -> Any:
    """Read `key` from a node's metadata, or from the node itself as fallback."""
    if node is None:
        return None
    metadata = _attr_or_item(node, "metadata")
    if isinstance(metadata, dict) and key in metadata:
        return metadata[key]
    return _attr_or_item(node, key)


def _attr_or_item(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, EntryRef):
        # Drill to the underlying Pydantic model so helpers see the raw
        # metadata dict and raw field values — EntryRef's attribute view
        # wraps entity_ref fields as EntryRefs, which breaks helpers like
        # pov() that need the raw lore id back. .id is preserved even when
        # the underlying load fails.
        loaded = obj._load()
        if loaded is None:
            return obj.id if key == "id" else None
        return getattr(loaded, key, None)
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _is_lore_id(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("lore_")


def _is_scene_id(value: Any) -> bool:
    return isinstance(value, str) and (
        value.startswith("scene_") or value.startswith("node_")
    )


def _collect_lore_refs_from_metadata(metadata: Any) -> set[str]:
    """Walk a metadata dict looking for lore IDs in entity_ref / list values."""
    found: set[str] = set()
    if not isinstance(metadata, dict):
        return found
    for value in metadata.values():
        if _is_lore_id(value):
            found.add(value)
        elif isinstance(value, list):
            for item in value:
                if _is_lore_id(item):
                    found.add(item)
    return found


def _safe_read_lore(project: "ProjectService", entry_id: str) -> Any:
    try:
        return project.read_lore_entry(entry_id)
    except Exception:
        return None


# ----- `pov(scene)` --------------------------------------------------------


def _pov(
    project: "ProjectService", schema: Any, scene: Any
) -> EntryRef | None:
    """Return an EntryRef for the scene's POV character, or None.

    Looks for a `pov` field on the scene's metadata. If it's an entity_ref
    (a lore id), wraps it as an EntryRef so `pov(scene).title` /
    `pov(scene).aliases` work. If the field is a free-form string (no lore
    id), returns None — templates that need to display free-form text can
    read `scene.metadata.pov` directly.
    """
    raw = _get_field(scene, "pov")
    if not raw:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
        if not raw:
            return None
    if not _is_lore_id(raw):
        return None
    return EntryRef(project, schema, raw)


# ----- `scenes_before(scene)` ---------------------------------------------


def _scenes_before(project: "ProjectService", scene: Any) -> str:
    """XML listing of summaries for all scenes before `scene` in manuscript order.

    Walks the manuscript structure depth-first, collecting scene summaries up
    to (but not including) the current scene. Wraps each as
    `<scene title="...">summary</scene>` inside a `<story_so_far>` block.
    Scope is the whole project; once nested-project support lands the scope
    will be the current book.
    """
    target_id = _attr_or_item(scene, "id")
    if not target_id:
        return ""
    try:
        structure = project.read_structure()
    except Exception:
        return ""

    chunks: list[str] = []
    _walk_collect(structure.root, target_id, project, chunks)
    if not chunks:
        return ""
    return "<story_so_far>\n" + "\n\n".join(chunks) + "\n</story_so_far>"


def _walk_collect(
    node: Any, target_id: str, project: "ProjectService", chunks: list[str]
) -> bool:
    """Append `<scene>` entries for scene nodes preceding `target_id`.

    Returns True once `target_id` has been encountered (so the caller stops
    descending into later siblings).
    """
    node_scene_id = _attr_or_item(node, "scene_id")
    if node_scene_id and node_scene_id == target_id:
        return True
    if node_scene_id:
        full = None
        try:
            full = project.read_scene(node_scene_id)
        except Exception:
            full = None
        if full is not None:
            summary = _get_field(full, "summary")
            title = _attr_or_item(full, "title") or ""
            if isinstance(summary, str) and summary.strip():
                chunks.append(
                    f"<scene title={quoteattr(str(title))}>\n"
                    f"{xml_escape(summary.strip())}\n"
                    f"</scene>"
                )
    for child in _attr_or_item(node, "children") or []:
        if _walk_collect(child, target_id, project, chunks):
            return True
    return False


# ----- `relevant_lore(scene, mode)` ---------------------------------------


def _relevant_lore(
    project: "ProjectService",
    scene: Any,
    mode: str = "implicit",
    partition: str = "all",
    session: AISession | None = None,
    journal: list[Any] | None = None,
) -> str:
    """Return a markdown block of lore entries relevant to `scene`.

    Modes:
    - `"implicit"` (default): union of (a) lore directly referenced by the
      scene's entity_ref / entity_ref_list metadata, (b) lore whose title or
      any alias appears in the scene's `summary` field, and (c) one-hop
      expansion through the entries collected in (a)+(b).
    - `"explicit"`: only the lore directly referenced via entity_ref fields.
      No alias scan, no graph walk.
    - `"pinned_only"`: returns empty for now (pin UI ships in a later milestone).

    Partition (only meaningful when a session is bound; see
    `register_helpers`):
    - `"all"` (default): every relevant entry, regardless of baseline.
    - `"stable"`: entries whose revision matches the session baseline.
    - `"volatile"`: entries new or changed since the session baseline.

    Sessions track touched entries automatically — every entry returned (in
    any partition) is recorded for the upcoming commit.
    """
    if partition not in VALID_PARTITIONS:
        partition = "all"
    if mode == "pinned_only":
        return ""

    scene_metadata = _attr_or_item(scene, "metadata")
    direct = _collect_lore_refs_from_metadata(scene_metadata)

    if mode == "explicit":
        ids = sorted(direct)
    else:
        # implicit: alias scan + one-hop expansion
        found = set(direct)
        if journal is None:
            # No chat-session journal — helper is the producer of detected
            # context (one-shot generates, preview, tests). Run the textual
            # scan on the scene summary.
            summary = _get_field(scene, "summary") or ""
            if isinstance(summary, str) and summary.strip():
                found |= _alias_match(project, summary)
        else:
            # Chat-session use: the send-time context expander has already
            # populated the journal with textual detections (incl. depth-1).
            # Trust it; don't re-derive.
            for entry in journal:
                jid = _attr_or_item(entry, "entry_id")
                if isinstance(jid, str) and jid:
                    found.add(jid)

        expanded = set(found)
        for entry_id in list(found):
            entry = _safe_read_lore(project, entry_id)
            if entry is None:
                continue
            expanded |= _collect_lore_refs_from_metadata(
                _attr_or_item(entry, "metadata")
            )
        # Textual depth-1 only runs when the journal is absent; otherwise
        # the journal already carries those expansions.
        if journal is None:
            expanded |= _textual_one_hop(project, found)
        ids = sorted(expanded)

    if session is None or partition == "all":
        if session is not None:
            _snapshot_revisions(project, ids, session)
        return _format_lore_block(project, ids)

    stable_ids: list[str] = []
    volatile_ids: list[str] = []
    for entry_id in ids:
        entry = _safe_read_lore(project, entry_id)
        if entry is None:
            continue
        revision = _attr_or_item(entry, "revision") or ""
        session.snapshot(entry_id, revision)
        if session.is_stable(entry_id, revision):
            stable_ids.append(entry_id)
        else:
            volatile_ids.append(entry_id)

    selected = stable_ids if partition == "stable" else volatile_ids
    return _format_lore_block(project, selected)


def _snapshot_revisions(
    project: "ProjectService", entry_ids: list[str], session: AISession
) -> None:
    for entry_id in entry_ids:
        entry = _safe_read_lore(project, entry_id)
        if entry is None:
            continue
        revision = _attr_or_item(entry, "revision") or ""
        session.snapshot(entry_id, revision)


def _alias_match(project: "ProjectService", text: str) -> set[str]:
    """Return lore IDs whose title or aliases appear as words in `text`."""
    try:
        listing = project.list_lore_entries()
    except Exception:
        return set()
    haystack_lower = text.lower()
    words = set(re.findall(r"[a-z0-9'-]+", haystack_lower))
    matched: set[str] = set()
    for summary in listing.entries:
        candidates: list[str] = []
        title = _attr_or_item(summary, "title")
        if isinstance(title, str):
            candidates.append(title)
        aliases = _get_field(summary, "aliases") or []
        if isinstance(aliases, list):
            candidates.extend(str(a) for a in aliases if a)
        for name in candidates:
            if _name_appears(name, words, haystack_lower):
                entry_id = _attr_or_item(summary, "id")
                if entry_id:
                    matched.add(entry_id)
                break
    return matched


def _textual_one_hop(
    project: "ProjectService", entry_ids: set[str]
) -> set[str]:
    """Scan the body of each given entry for further textual name matches.

    Used for depth-1 expansion in implicit-context detection: if Honor's
    body mentions Nimitz by name, Nimitz is pulled in even without an
    explicit entity_ref linking them. Bodies of newly-discovered entries
    are NOT rescanned — depth strictly 1 — which prevents cascade
    explosions on richly cross-referenced lore.

    Returns all matches found in the scanned bodies, including the source
    entries themselves when their body mentions their own name; callers
    should dedup against the source set.
    """
    bodies: list[str] = []
    for entry_id in entry_ids:
        entry = _safe_read_lore(project, entry_id)
        if entry is None:
            continue
        body = _attr_or_item(entry, "body_markdown")
        if isinstance(body, str) and body.strip():
            bodies.append(body)
    if not bodies:
        return set()
    return _alias_match(project, "\n".join(bodies))


def _name_appears(name: str, words: set[str], haystack_lower: str) -> bool:
    """Match a name against the haystack: single word → token check,
    multi-word → substring check on a word boundary."""
    if not name:
        return False
    name_lower = name.lower().strip()
    if " " in name_lower or "-" in name_lower:
        # Multi-word name: require whole-name substring with word boundary
        pattern = r"\b" + re.escape(name_lower) + r"\b"
        return re.search(pattern, haystack_lower) is not None
    return name_lower in words


def _format_lore_block(project: "ProjectService", entry_ids: list[str]) -> str:
    """Render lore entries as an XML block.

    Each entry becomes `<{entry_type} name="..." aliases="...">body</...>`,
    all wrapped in `<lore>...</lore>`. Anthropic specifically recommends XML
    tags for context structure; the format helps models locate entities
    unambiguously without losing the natural prose body.
    """
    if not entry_ids:
        return ""
    chunks: list[str] = []
    for entry_id in entry_ids:
        entry = _safe_read_lore(project, entry_id)
        if entry is None:
            continue
        entry_type = _attr_or_item(entry, "entry_type") or "lore_entry"
        tag = _xml_safe_tag(entry_type)
        title = str(_attr_or_item(entry, "title") or entry_id)
        aliases_raw = _get_field(entry, "aliases") or []
        if isinstance(aliases_raw, list):
            aliases = [str(a).strip() for a in aliases_raw if str(a).strip()]
        else:
            aliases = []

        body = _attr_or_item(entry, "body_markdown") or ""
        body = str(body).strip()
        if not body:
            summary = _get_field(entry, "summary")
            if isinstance(summary, str) and summary.strip():
                body = summary.strip()

        chunks.append(_render_lore_xml_entry(tag, title, aliases, body))
    if not chunks:
        return ""
    return "<lore>\n" + "\n\n".join(chunks) + "\n</lore>"


def _render_lore_xml_entry(
    tag: str, title: str, aliases: list[str], body: str
) -> str:
    attrs = [f"name={quoteattr(title)}"]
    if aliases:
        attrs.append(f"aliases={quoteattr(', '.join(aliases))}")
    attr_str = " ".join(attrs)
    if body:
        return f"<{tag} {attr_str}>\n{xml_escape(body)}\n</{tag}>"
    return f"<{tag} {attr_str} />"


_XML_TAG_FALLBACK = "lore_entry"


def _xml_safe_tag(name: Any) -> str:
    """Coerce a node entry_type into a valid XML element name."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(name).strip())
    if not cleaned or not cleaned[0].isalpha() and cleaned[0] != "_":
        return _XML_TAG_FALLBACK
    return cleaned


# ----- `full_outline()` and `full_text()` ---------------------------------


class _OutlineNode(dict):
    """Plain dict carrying outline data, but with attribute access for Jinja.

    Templates can write `{{ node.title }}` and `{% for c in node.children %}`,
    matching the look of EntryRef without dragging EntryRef's lazy load along
    for what is essentially structural data.
    """

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self.get(name)


def _full_outline(project: "ProjectService") -> list[_OutlineNode]:
    """Manuscript outline as a list of nested nodes.

    Each node carries `title`, `summary`, `entry_type`, `scene_id`, and
    `children` (recursive). Walks the manuscript structure in document
    order. Containers (acts, chapters) carry their own title; the summary
    comes from the linked scene's metadata when present.
    """
    try:
        structure = project.read_structure()
    except Exception:
        return []
    return [_build_outline_node(child, project) for child in structure.root.children]


def _build_outline_node(node: Any, project: "ProjectService") -> _OutlineNode:
    scene_id = _attr_or_item(node, "scene_id")
    title = _attr_or_item(node, "title") or ""
    summary = ""
    if scene_id:
        try:
            scene = project.read_scene(scene_id)
        except Exception:
            scene = None
        if scene is not None:
            raw_summary = _get_field(scene, "summary")
            if isinstance(raw_summary, str):
                summary = raw_summary.strip()
            if not title:
                title = _attr_or_item(scene, "title") or ""
    return _OutlineNode(
        title=str(title),
        summary=summary,
        entry_type=str(_attr_or_item(node, "type") or ""),
        scene_id=scene_id,
        children=[
            _build_outline_node(child, project)
            for child in (_attr_or_item(node, "children") or [])
        ],
    )


class _SceneText(dict):
    """Plain dict + attribute access. Same shape rationale as `_OutlineNode`."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self.get(name)


def _full_text(project: "ProjectService") -> list[_SceneText]:
    """Every scene's prose in manuscript order.

    Each item has `title`, `body`, `scene_id`, and `entry_type`. Skips
    structural containers that have no scene_id, since their body would be
    empty by design (containers carry only metadata).
    """
    try:
        structure = project.read_structure()
    except Exception:
        return []
    out: list[_SceneText] = []
    _collect_scene_text(structure.root, project, out)
    return out


def _collect_scene_text(
    node: Any, project: "ProjectService", sink: list[_SceneText]
) -> None:
    scene_id = _attr_or_item(node, "scene_id")
    if scene_id:
        try:
            scene = project.read_scene(scene_id)
        except Exception:
            scene = None
        if scene is not None:
            sink.append(
                _SceneText(
                    title=str(_attr_or_item(scene, "title") or ""),
                    body=str(_attr_or_item(scene, "body_markdown") or ""),
                    scene_id=scene_id,
                    entry_type=str(_attr_or_item(scene, "entry_type") or ""),
                )
            )
    for child in _attr_or_item(node, "children") or []:
        _collect_scene_text(child, project, sink)
