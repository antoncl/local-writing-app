"""Send-time implicit-context expander.

Scans user-authored text for lore names, applies depth-1 expansion
through matched entries' bodies, and returns the entries that are NEW
to the chat session — i.e. not already pinned via explicit context picks
and not already in the session's journal from prior turns.

The expander does NOT mutate state. It returns a list of
ChatSessionJournalEntry that the caller should append to
ChatSession.journal and persist via save_chat_session. Splitting it this
way keeps the expander stateless and trivially testable; the chat-send
endpoint is the only place that knows how to persist.

Scope notes:
- We scan ONLY user-authored text (chat composer, scene summaries,
  rendered prompt output on first send). Assistant replies do not feed
  the journal — that would risk prompt-injection via tool output and
  makes context mutation across turns hard to reason about.
- Depth limit is strictly 1. Bodies of newly-discovered entries are
  NOT rescanned. See decisions_implicit_context.md for rationale.
- Structural ref-following (entity_ref metadata fields) is template-
  author territory via Jinja helpers, not auto-injection territory.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Literal

from app.models import ChatSessionContextItem, ChatSessionJournalEntry
from app.services.ai.helpers import (
    _alias_match,
    _attr_or_item,
    _safe_read_node,
    _scene_prose_ids,
    _textual_one_hop,
)

if TYPE_CHECKING:
    from app.services.project_service import ProjectService


JournalSource = Literal[
    "user_message", "rendered_prompt", "depth1_expansion", "scene_prose"
]


def expand_context(
    project: ProjectService,
    text: str,
    existing_journal: Iterable[ChatSessionJournalEntry] = (),
    explicit_picks: Iterable[ChatSessionContextItem] = (),
    *,
    source: JournalSource = "user_message",
    turn: int = 0,
    scene: Any = None,
) -> list[ChatSessionJournalEntry]:
    """Scan `text` AND the resolution scene's own prose, expand depth-1,
    return NEW journal entries.

    `source` labels how the composer-text direct matches were discovered
    (the user's typed message vs the rendered prompt output). Direct matches
    from the scene's own body/long_text fields (ADR-0075 slice 3) always get
    source="scene_prose"; depth-1 expansions always get
    source="depth1_expansion" — regardless of `source`.

    `scene` is the chat's resolution scene — a plain id string, a loaded
    scene node (EntryRef), or None for a scene-less chat. Passed through to
    `_alias_match`/`_scene_prose_ids` for effective-name resolution; only
    `_scene_prose_ids` needs the loaded node (an id string yields no prose
    surface — see there).

    `turn` is the message index at which the detection fires (the new
    user message's index). Recorded on each entry for the audit UI.

    Returns an empty list when nothing new was detected. Caller is
    responsible for appending the returned entries to the session
    journal and saving — the expander is pure.
    """
    composer_text = text if isinstance(text, str) else ""

    # Direct textual matches against title + aliases, resolved under each
    # entity's effective name-set as of the chat's resolution scene (#61).
    direct_ids = _alias_match(project, composer_text, scene=scene) if composer_text.strip() else set()
    # The scene's own detection surface — body + every long_text field,
    # scanned field-by-field so a name can't false-match across a field
    # boundary (ADR-0075 §2/slice 3). Excludes anything the composer already
    # matched so an id isn't double-labeled across two sources in one turn.
    prose_ids = _scene_prose_ids(project, scene) - direct_ids
    if not direct_ids and not prose_ids:
        return []

    # Depth-1 expansion: scan bodies of ALL direct matches (composer + scene
    # prose) for further hits. Note: this also re-finds names already in
    # `combined_direct` if they happen to appear in any direct match's body,
    # so we subtract combined_direct below.
    combined_direct = direct_ids | prose_ids
    depth1_ids = _textual_one_hop(project, combined_direct, scene=scene)

    # What's already pinned via explicit picks or earlier journal turns?
    in_scope: set[str] = set()
    for entry in existing_journal:
        in_scope.add(entry.entry_id)
    for pick in explicit_picks:
        # Only "lore" picks dedup against our matcher — scene/snippet/preset
        # picks have different identity spaces.
        if pick.kind == "lore" and pick.id:
            in_scope.add(pick.id)

    # Sorted so the persisted journal's entry order is deterministic run-to-run
    # (these are sets; the final lore set is order-independent, but a stable
    # journal keeps the chat node's front-matter free of spurious byte diffs).
    new_direct = sorted(direct_ids - in_scope)
    new_prose = sorted(prose_ids - in_scope)
    new_depth1 = sorted(depth1_ids - combined_direct - in_scope)

    entries: list[ChatSessionJournalEntry] = []
    entries.extend(_make_entries(project, new_direct, source=source, turn=turn))
    entries.extend(_make_entries(project, new_prose, source="scene_prose", turn=turn))
    entries.extend(_make_entries(project, new_depth1, source="depth1_expansion", turn=turn))
    return entries


def _make_entries(
    project: ProjectService,
    entry_ids: set[str],
    *,
    source: JournalSource,
    turn: int,
) -> list[ChatSessionJournalEntry]:
    """Build journal entries with title/entry_type snapshots from each
    entry's current state. Order is stable (sorted by id) so test
    assertions are deterministic; chat order across turns is preserved
    by the caller's append.
    """
    out: list[ChatSessionJournalEntry] = []
    for entry_id in sorted(entry_ids):
        entry = _safe_read_node(project, entry_id)
        if entry is None:
            continue
        title = _attr_or_item(entry, "title") or ""
        entry_type = _attr_or_item(entry, "entry_type") or ""
        out.append(
            ChatSessionJournalEntry(
                entry_id=entry_id,
                title=str(title),
                entry_type=str(entry_type),
                added_at_turn=turn,
                source=source,
            )
        )
    return out
