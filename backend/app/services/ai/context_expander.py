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
from typing import TYPE_CHECKING, Literal

from app.models import ChatSessionContextItem, ChatSessionJournalEntry
from app.services.ai.helpers import (
    _alias_match,
    _attr_or_item,
    _safe_read_lore,
    _textual_one_hop,
)

if TYPE_CHECKING:
    from app.services.project_service import ProjectService


JournalSource = Literal["user_message", "rendered_prompt", "depth1_expansion"]


def expand_context(
    project: ProjectService,
    text: str,
    existing_journal: Iterable[ChatSessionJournalEntry] = (),
    explicit_picks: Iterable[ChatSessionContextItem] = (),
    *,
    source: JournalSource = "user_message",
    turn: int = 0,
    scene: str | None = None,
) -> list[ChatSessionJournalEntry]:
    """Scan `text`, expand depth-1, return NEW journal entries.

    `source` labels how the direct matches were discovered (the user's
    typed message vs the rendered prompt output). Depth-1 expansions
    always get source="depth1_expansion" regardless.

    `turn` is the message index at which the detection fires (the new
    user message's index). Recorded on each entry for the audit UI.

    Returns an empty list when nothing new was detected. Caller is
    responsible for appending the returned entries to the session
    journal and saving — the expander is pure.
    """
    if not isinstance(text, str) or not text.strip():
        return []

    # Direct textual matches against title + aliases, resolved under each
    # entity's effective name-set as of the chat's resolution scene (#61).
    direct_ids = _alias_match(project, text, scene=scene)
    if not direct_ids:
        return []

    # Depth-1 expansion: scan bodies of direct matches for further hits.
    # Note: this also re-finds names from `text` if they happen to appear
    # in any direct match's body, so we'll need to subtract direct_ids
    # below.
    depth1_ids = _textual_one_hop(project, direct_ids, scene=scene)

    # What's already pinned via explicit picks or earlier journal turns?
    in_scope: set[str] = set()
    for entry in existing_journal:
        in_scope.add(entry.entry_id)
    for pick in explicit_picks:
        # Only "lore" picks dedup against our matcher — scene/snippet/preset
        # picks have different identity spaces.
        if pick.kind == "lore" and pick.id:
            in_scope.add(pick.id)

    new_direct = direct_ids - in_scope
    new_depth1 = depth1_ids - direct_ids - in_scope

    entries: list[ChatSessionJournalEntry] = []
    entries.extend(_make_entries(project, new_direct, source=source, turn=turn))
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
        entry = _safe_read_lore(project, entry_id)
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
