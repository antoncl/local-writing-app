"""The ADR-0057 one gated lore selector and the ADR-0075 implicit-detection
surface: scene-relevant lore id selection (`_relevant_lore_ids`/
`_relevant_lore`), alias/textual matching (`_alias_match`, `_scene_prose_ids`,
`_textual_one_hop`), context-policy gating (`_always_included_lore_ids`/
`_never_lore_ids`/`_manual_only_lore_ids`), and per-turn stable/volatile
tiering (`_tier_lore_ids`). Extracted from `helpers.py` for size (#1497);
sibling to `name_matcher.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.ai.helpers import (
    _attr_or_item,
    _collect_lore_refs_from_metadata,
    _entry_context_policy,
    _get_field,
    _safe_read_node,
    _scene_id_of,
)
from app.services.ai.name_matcher import (
    CompiledNameMatcher,
    compile_name_matcher,
    scan_name_matcher,
)
from app.services.ai.sessions import AISession

if TYPE_CHECKING:
    from app.services.project_service import ProjectService


# ----- `relevant_lore(scene, mode)` ---------------------------------------


def _relevant_lore_ids(
    project: ProjectService,
    scene: Any = None,
    mode: str = "implicit",
    journal: list[Any] | None = None,
    used_ids: list[str] | None = None,
) -> list[str]:
    """The one lore selector (ADR-0057 §3 / ADR-0060 §2): the deduped, sorted,
    `never`-filtered id set relevant to `scene`. Formatting and per-turn tiering
    are the caller's next step.

    Modes:
    - `"implicit"` (default): union of (a) lore directly referenced by the
      scene's entity_ref / entity_ref_list metadata, (b) lore whose title or
      any alias appears in the scene's own prose surface — its body plus
      every `long_text` field (`summary`, `description`, ... — ADR-0075 §2/
      slice 3, via `_scene_prose_ids`), and (c) one-hop expansion through the
      entries collected in (a)+(b).
    - `"explicit"`: only the lore directly referenced via entity_ref fields.
    - `"pinned_only"`: empty for now (pin UI ships in a later milestone).

    `use()` selections (`used_ids`) are EXACT — deduped by id and subject to the
    one `never` chokepoint, but never fan-out seeds (the scene's own refs are the
    only expansion roots) and never a second matcher (ADR-0057 anti-goal). The
    1-hop graph fan-out stays the implicit `use_lore()` path's job (#1230).
    """
    if mode == "pinned_only":
        return []
    scene_metadata = _attr_or_item(scene, "metadata")
    scene_refs = _collect_lore_refs_from_metadata(scene_metadata)
    used = set(used_ids or [])
    if mode == "explicit":
        ids = sorted(scene_refs | used)
    else:
        # `use()`'d ids are EXACT: they join the final set but are NOT fan-out
        # seeds. Only the scene's own structural/textual refs expand one hop —
        # that stays the implicit `use_lore()` path's job. An author who wants a
        # use()'d node's neighbours loops its refs and use()s them in the template.
        ids = sorted(_implicit_lore_ids(project, scene, scene_refs, journal) | used)
    # Chokepoint filter: drop any "never"-policy entries that may have arrived via
    # explicit refs or structural expansion. `never` is excluded from EVERY route —
    # even an explicit scene ref or use(). `manual_only` is NOT filtered here: it
    # stays reachable via the scene's own refs and use() (the explicit picker), and
    # is instead kept out of the AUTOMATIC one-hop fan-out in `_implicit_lore_ids`
    # (#1024). Single source of authority for the `never` rule.
    never_ids = _never_lore_ids(project)
    if never_ids:
        ids = [eid for eid in ids if eid not in never_ids]
    return ids


def _relevant_lore(
    project: ProjectService,
    scene: Any = None,
    mode: str = "implicit",
    session: AISession | None = None,
    journal: list[Any] | None = None,
    index: Any = None,
    used_ids: list[str] | None = None,
) -> str:
    """A markdown block of ALL lore entries relevant to `scene`, in one block —
    the untiered form for one-shot / preview callers. A bound `session` only
    snapshots touched revisions for the upcoming commit; the send path's per-turn
    stable/volatile split lives in `_tier_lore_ids` (ADR-0060 §5 retired the
    `partition=` two-call form)."""
    # Function-level import: `lore_block` imports leaf accessors from `helpers`,
    # so keeping this out of the module header avoids a load-order tangle
    # between `helpers`, `lore_selection`, and `lore_block`.
    from app.services.ai.lore_block import _format_lore_block

    ids = _relevant_lore_ids(project, scene, mode, journal, used_ids)
    if session is not None:
        _snapshot_revisions(project, ids, session)
    return _format_lore_block(project, ids, scene=scene, index=index)


def _implicit_lore_ids(
    project: ProjectService, scene: Any, direct: set[str], journal: list[Any] | None
) -> set[str]:
    """The implicit-mode id set: always-included + direct refs + textual alias
    scan (or the chat journal's pre-detected ids) + one structural hop through
    each collected entry's own refs (+ a textual hop when there's no journal).
    """
    # Always-included entries (context_policy = "always") feed every implicit
    # render regardless of mention.
    found = set(direct) | _always_included_lore_ids(project)
    matcher: CompiledNameMatcher | None = None
    if journal is None:
        # No chat-session journal — helper is the producer of detected context
        # (one-shot generates, preview, tests). Built once here and threaded
        # through both the prose scan and the textual one-hop below — the
        # lore set is fixed for this one detection pass, so there's no need
        # to recompile the matcher per surface. Run the textual scan on the
        # scene's own prose surface: body + every long_text field (ADR-0075
        # slice 3) — a superset of the old summary-only scan.
        matcher = _build_scene_matcher(project, scene)
        found |= _scene_prose_ids(project, scene, matcher=matcher)
    else:
        # Chat-session use: the send-time context expander has already populated
        # the journal with textual detections (incl. depth-1). Trust it.
        for entry in journal:
            jid = _attr_or_item(entry, "entry_id")
            if isinstance(jid, str) and jid:
                found.add(jid)

    # One structural hop through each found entry's own entity_ref metadata. Like
    # the alias/textual scans (which run through `_alias_match`), this AUTOMATIC
    # route honors `manual_only` ("explicit picker only"): a transitive ref to such
    # an entry is NOT fanned in — it stays reachable via the scene's own refs
    # (already in `found`) or use() (#1024). `never` needs no filter here: the
    # chokepoint in `_relevant_lore_ids` is its single enforcement point and drops
    # it from the final set regardless of route. One lore scan, computed once.
    manual_only_ids = _manual_only_lore_ids(project)
    expanded = set(found)
    for entry_id in list(found):
        entry = _safe_read_node(project, entry_id)
        if entry is None:
            continue
        hop_refs = _collect_lore_refs_from_metadata(_attr_or_item(entry, "metadata"))
        expanded |= hop_refs - manual_only_ids
    # Textual depth-1 only runs when the journal is absent; otherwise the
    # journal already carries those expansions.
    if journal is None:
        expanded |= _textual_one_hop(project, found, scene=scene, matcher=matcher)
    return expanded


def _tier_lore_ids(
    project: ProjectService,
    ids: list[str],
    session: AISession,
    hints: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Split the one deduped lore set into `(stable_ids, volatile_ids)` for
    per-tier placement (ADR-0060 §5), snapshotting each entry for the upcoming
    commit. The base tier is per-revision vs the session baseline — unchanged →
    stable, new-or-changed → volatile. The optional `use(node, hint)` prior biases
    it, revision-bounded so it never rides stale bytes:

    - `"volatile"`: always volatile (pin to the 5m tier).
    - `"stable"`: start/stay stable UNLESS the entry actually changed since it was
      last sent — a changed entry re-writes that turn, then re-settles.
    - no hint: the base per-revision tier.

    Order within each tier follows `ids` (already sorted), so a settled block is
    byte-identical turn-to-turn.
    """
    hints = hints or {}
    stable_ids: list[str] = []
    volatile_ids: list[str] = []
    for entry_id in ids:
        entry = _safe_read_node(project, entry_id)
        if entry is None:
            continue
        revision = _attr_or_item(entry, "revision") or ""
        # `changed` (seen before, different revision) vs `new` (never seen) — both
        # are `not is_stable`, but the "stable" prior treats them differently.
        changed = session.seen(entry_id) and not session.is_stable(entry_id, revision)
        session.snapshot(entry_id, revision)
        hint = hints.get(entry_id)
        if hint == "volatile":
            volatile_ids.append(entry_id)
        elif hint == "stable":
            (volatile_ids if changed else stable_ids).append(entry_id)
        elif session.is_stable(entry_id, revision):
            stable_ids.append(entry_id)
        else:
            volatile_ids.append(entry_id)
    return stable_ids, volatile_ids


def _snapshot_revisions(
    project: ProjectService, entry_ids: list[str], session: AISession
) -> None:
    for entry_id in entry_ids:
        entry = _safe_read_node(project, entry_id)
        if entry is None:
            continue
        revision = _attr_or_item(entry, "revision") or ""
        session.snapshot(entry_id, revision)


def _build_scene_matcher(project: ProjectService, scene: Any = None) -> CompiledNameMatcher:
    """Compile the `auto`-policy name matcher for `scene` — the same name-set
    `_alias_match` used to build inline on every call. The lore set is fixed
    within one detection pass, so callers that scan more than one text (a
    scene's several prose fields, the composer + rendered prompt + scene
    prose + depth-1 hop in `expand_context`) should build this ONCE and reuse
    it via `_scan_matcher_ids`, instead of recompiling per text.

    Honors `context_policy`: entries marked `manual_only` or `never` are
    skipped here — the matcher only ever pulls in `auto` (default) entries.
    `always`-policy entries are surfaced by `_always_included_lore_ids`,
    not here.

    When a `scene` (resolution scene) is given, each entry is matched under its
    **effective** name-set as of that scene (#61) — a renamed entity is detected
    under its as-of-scene name, not its base title. Without a scene, base names
    are used (the prior behavior). Resolution is scene-granular (ADR-0008)."""
    try:
        listing = project.list_lore_entries()
    except Exception:
        return compile_name_matcher([])
    effective = _effective_name_map(project, scene)
    ordered_entries: list[tuple[str, list[str]]] = []
    for summary in listing.entries:
        if _entry_context_policy(summary) != "auto":
            continue
        entry_id = _attr_or_item(summary, "id")
        if not entry_id:
            continue
        candidates = _entry_name_candidates(summary, entry_id, effective)
        ordered_entries.append((entry_id, candidates))
    return compile_name_matcher(ordered_entries)


def _scan_matcher_ids(matcher: CompiledNameMatcher, text: str) -> set[str]:
    """Scan `text` against a pre-built `matcher`, returning the matched entry
    ids. The per-text half of the compile-once/scan-many split — pair with
    `_build_scene_matcher`."""
    if not isinstance(text, str) or not text:
        return set()
    return {hit.entry_id for hit in scan_name_matcher(matcher, text)}


def _alias_match(project: ProjectService, text: str, scene: Any = None) -> set[str]:
    """Return lore IDs whose title or aliases appear in `text`, via the pure
    positional matcher (`compile_name_matcher` / `scan_name_matcher`) — the
    §3 regex-OR that mirrors `implicitContextMatcher.ts`.

    Thin wrapper over `_build_scene_matcher` + `_scan_matcher_ids` for
    standalone/single-text callers and tests. Callers scanning more than one
    text against the same scene's lore set should build the matcher once and
    call `_scan_matcher_ids` directly instead."""
    return _scan_matcher_ids(_build_scene_matcher(project, scene), text)


def _effective_name_map(project: ProjectService, scene: Any) -> dict[str, list[str]]:
    """The `{entity_id: [effective names]}` map as of `scene`, or `{}` when no
    scene is given / the read fails (matcher then falls back to base names)."""
    if scene is None:
        return {}
    scene_id = _scene_id_of(scene)
    if not scene_id:
        return {}
    try:
        return project.effective_names(scene_id)
    except Exception:
        return {}


def _entry_name_candidates(
    summary: Any, entry_id: str | None, effective: dict[str, list[str]]
) -> list[str]:
    """Names to match one entry by: its effective name-set when the resolution
    scene supplied one, else its base title + aliases."""
    if entry_id and entry_id in effective:
        return list(effective[entry_id])
    candidates: list[str] = []
    title = _attr_or_item(summary, "title")
    if isinstance(title, str):
        candidates.append(title)
    aliases = _get_field(summary, "aliases") or []
    if isinstance(aliases, list):
        candidates.extend(str(a) for a in aliases if a)
    return candidates


def _always_included_lore_ids(project: ProjectService) -> set[str]:
    """Return lore IDs whose context_policy is `always`. Used by
    `_relevant_lore` in implicit mode to union in entries the author has
    pinned as project-wide context (world rules, magic system primer, etc.)."""
    return _lore_ids_with_policy(project, "always")


def _never_lore_ids(project: ProjectService) -> set[str]:
    """Return lore IDs whose context_policy is `never`. These are excluded
    from every assembly path — implicit matcher, explicit ref, structural
    expansion. The author has said 'don't put this in front of the model.'"""
    return _lore_ids_with_policy(project, "never")


def _manual_only_lore_ids(project: ProjectService) -> set[str]:
    """Return lore IDs whose context_policy is `manual_only` — "explicit picker
    only". Kept OUT of the automatic transitive routes: the alias/textual scans
    exclude it via `_alias_match`, and `_implicit_lore_ids` subtracts this set
    from the structural one-hop fan-out (#1024). It stays reachable via the
    scene's own entity_refs and via use() — the explicit picks."""
    return _lore_ids_with_policy(project, "manual_only")


def _lore_ids_with_policy(project: ProjectService, policy: str) -> set[str]:
    try:
        listing = project.list_lore_entries()
    except Exception:
        return set()
    ids: set[str] = set()
    for summary in listing.entries:
        if _entry_context_policy(summary) != policy:
            continue
        entry_id = _attr_or_item(summary, "id")
        if entry_id:
            ids.add(entry_id)
    return ids


def _textual_one_hop(
    project: ProjectService,
    entry_ids: set[str],
    scene: Any = None,
    matcher: CompiledNameMatcher | None = None,
) -> set[str]:
    """Scan the body of each given entry for further textual name matches.

    Used for depth-1 expansion in implicit-context detection: if Honor's
    body mentions Nimitz by name, Nimitz is pulled in even without an
    explicit entity_ref linking them. Bodies of newly-discovered entries
    are NOT rescanned — depth strictly 1 — which prevents cascade
    explosions on richly cross-referenced lore.

    `matcher` lets a caller that already built the scene's matcher (e.g.
    `expand_context`, which scans several surfaces in one detection pass)
    pass it in and skip recompiling; when omitted, one is built here.

    Returns all matches found in the scanned bodies, including the source
    entries themselves when their body mentions their own name; callers
    should dedup against the source set.
    """
    bodies: list[str] = []
    for entry_id in entry_ids:
        entry = _safe_read_node(project, entry_id)
        if entry is None:
            continue
        body = _attr_or_item(entry, "body")
        if isinstance(body, str) and body.strip():
            bodies.append(body)
    if not bodies:
        return set()
    if matcher is None:
        matcher = _build_scene_matcher(project, scene)
    return _scan_matcher_ids(matcher, "\n".join(bodies))


def _scene_prose_ids(
    project: ProjectService,
    scene: Any,
    schema: Any = None,
    matcher: CompiledNameMatcher | None = None,
) -> set[str]:
    """The lore ids textually detected in `scene`'s own prose surface — its
    **body** plus the value of every `long_text` field on its entry_type
    (`summary`, `description`, `notes`, any custom long_text). NOT single-line
    `text` fields, title/name, or `aliases` (ADR-0075 §2). The single shared
    definition of "the scene's own detection surface", used by both the
    one-shot/preview path and the chat send path so they can't drift.

    Each text is scanned SEPARATELY and the id sets are UNIONED — never
    concatenated — so a multi-word name can't false-match across a
    field/body boundary (body ending "...Bob" + a field starting "Smith..."
    must not detect "Bob Smith"). The scan honors `context_policy`
    (auto-only) and effective names as-of `scene` via `_build_scene_matcher`
    — the same matcher `_alias_match` used to build per-call.

    `matcher` lets a caller that already built the scene's matcher pass it
    in and skip recompiling; when omitted (the default), one is built here —
    once for this call, still shared across all of this scene's fields.
    """
    if scene is None:
        return set()
    schema = schema or project.read_metadata_schema()
    texts: list[str] = []
    body = _attr_or_item(scene, "body")
    if isinstance(body, str) and body.strip():
        texts.append(body)
    entry_type = _get_field(scene, "entry_type")
    definition = schema.entry_types.get(entry_type) if isinstance(entry_type, str) else None
    field_ids = list(definition.fields) if definition is not None else []
    for field_id in field_ids:
        field = schema.fields.get(field_id)
        if field is None or field.type != "long_text":
            continue
        value = _get_field(scene, field_id)
        if isinstance(value, str) and value.strip():
            texts.append(value)
    if matcher is None:
        matcher = _build_scene_matcher(project, scene)
    found: set[str] = set()
    for text in texts:
        found |= _scan_matcher_ids(matcher, text)
    return found
