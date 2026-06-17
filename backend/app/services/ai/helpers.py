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


# ----- Project-bound helpers ----------------------------------------------


def register_helpers(
    env: SandboxedEnvironment,
    project: "ProjectService",
    session: AISession | None = None,
) -> None:
    """Bind project-aware helpers to the given env. Idempotent.

    If `session` is provided, `relevant_lore(..., partition="stable"|"volatile")`
    becomes meaningful — entries' revisions are snapshotted into the session
    and partitioned against its baseline.
    """
    env.globals["last_words"] = last_words
    env.globals["pov"] = lambda scene: _pov(project, scene)
    env.globals["scenes_before"] = lambda scene: _scenes_before(project, scene)
    env.globals["relevant_lore"] = (
        lambda scene, mode="implicit", partition="all": _relevant_lore(
            project, scene, mode, partition, session
        )
    )


def create_environment_for_project(
    project: "ProjectService", session: AISession | None = None
) -> SandboxedEnvironment:
    """Convenience: env with extensions and project helpers registered."""
    from app.services.ai.templates import create_environment

    env = create_environment()
    register_helpers(env, project, session)
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


def _pov(project: "ProjectService", scene: Any) -> dict[str, Any] | None:
    """Return the POV character entity for a scene, or None.

    Looks for a `pov` field on the scene's metadata. If it's an entity_ref
    (a lore ID), resolves to a dict with id/title/aliases. If the field is
    set but doesn't resolve, returns a stub dict with just the raw id.
    """
    raw = _get_field(scene, "pov")
    if not raw:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
        if not raw:
            return None
    if not _is_lore_id(raw):
        return {"id": None, "title": str(raw), "aliases": []}
    entry = _safe_read_lore(project, raw)
    if entry is None:
        return {"id": raw, "title": raw, "aliases": []}
    return {
        "id": _attr_or_item(entry, "id"),
        "title": _attr_or_item(entry, "title"),
        "aliases": list(_get_field(entry, "aliases") or []),
    }


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
        summary = _get_field(scene, "summary") or ""
        if isinstance(summary, str) and summary.strip():
            found |= _alias_match(project, summary)

        expanded = set(found)
        for entry_id in list(found):
            entry = _safe_read_lore(project, entry_id)
            if entry is None:
                continue
            expanded |= _collect_lore_refs_from_metadata(
                _attr_or_item(entry, "metadata")
            )
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
