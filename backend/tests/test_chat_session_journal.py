"""ChatSession.journal — append-only log of auto-detected lore entries
that grows as the user types names across turns. Round-trips through
save/read, defaults to empty on old sessions, refuses non-append edits.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import (
    ChatSessionJournalEntry,
    ChatSessionMessage,
    CreateChatSessionRequest,
    SaveChatSessionRequest,
)
from app.services.project_service import ProjectService, ProjectServiceError


def _project(tmp_path: Path, monkeypatch) -> ProjectService:
    monkeypatch.setattr(
        "app.services.machine_settings.config_path",
        lambda: tmp_path / "machine_settings.yaml",
    )
    service = ProjectService()
    service.create_project(tmp_path / "project", "Demo")
    return service


def test_journal_defaults_to_empty_list(tmp_path, monkeypatch):
    service = _project(tmp_path, monkeypatch)
    session = service.create_chat_session(CreateChatSessionRequest(title="X"))
    assert session.journal == []

    fresh = service.read_chat_session(session.id)
    assert fresh.journal == []


def test_journal_round_trip_through_save(tmp_path, monkeypatch):
    service = _project(tmp_path, monkeypatch)
    session = service.create_chat_session(
        CreateChatSessionRequest(title="Brainstorm", prompt_entry_id="p")
    )
    entries = [
        ChatSessionJournalEntry(
            entry_id="lore_honor",
            title="Honor Harrington",
            entry_type="character",
            added_at_turn=0,
            source="user_message",
        ),
        ChatSessionJournalEntry(
            entry_id="lore_nimitz",
            title="Nimitz",
            entry_type="character",
            added_at_turn=0,
            source="depth1_expansion",
        ),
    ]
    saved = service.save_chat_session(
        session.id,
        SaveChatSessionRequest(
            title="Brainstorm",
            prompt_entry_id="p",
            journal=entries,
        ),
    )
    assert len(saved.journal) == 2
    assert saved.journal[0].entry_id == "lore_honor"
    assert saved.journal[1].source == "depth1_expansion"

    fresh = service.read_chat_session(session.id)
    assert fresh.journal == saved.journal


def test_journal_append_extends_existing(tmp_path, monkeypatch):
    service = _project(tmp_path, monkeypatch)
    session = service.create_chat_session(
        CreateChatSessionRequest(title="X", prompt_entry_id="p")
    )
    first = ChatSessionJournalEntry(
        entry_id="lore_honor", title="Honor", added_at_turn=0
    )
    service.save_chat_session(
        session.id,
        SaveChatSessionRequest(title="X", prompt_entry_id="p", journal=[first]),
    )

    second = ChatSessionJournalEntry(
        entry_id="lore_samantha", title="Samantha", added_at_turn=2
    )
    extended = service.save_chat_session(
        session.id,
        SaveChatSessionRequest(
            title="X", prompt_entry_id="p", journal=[first, second]
        ),
    )
    assert [e.entry_id for e in extended.journal] == ["lore_honor", "lore_samantha"]


def test_journal_refuses_drop(tmp_path, monkeypatch):
    service = _project(tmp_path, monkeypatch)
    session = service.create_chat_session(
        CreateChatSessionRequest(title="X", prompt_entry_id="p")
    )
    honor = ChatSessionJournalEntry(entry_id="lore_honor", title="Honor")
    nimitz = ChatSessionJournalEntry(entry_id="lore_nimitz", title="Nimitz")
    service.save_chat_session(
        session.id,
        SaveChatSessionRequest(
            title="X", prompt_entry_id="p", journal=[honor, nimitz]
        ),
    )

    # Dropping Honor (or Nimitz) is forbidden — append-only.
    with pytest.raises(ProjectServiceError) as exc:
        service.save_chat_session(
            session.id,
            SaveChatSessionRequest(
                title="X", prompt_entry_id="p", journal=[nimitz]
            ),
        )
    assert exc.value.status_code == 409


def test_journal_refuses_reorder(tmp_path, monkeypatch):
    service = _project(tmp_path, monkeypatch)
    session = service.create_chat_session(
        CreateChatSessionRequest(title="X", prompt_entry_id="p")
    )
    honor = ChatSessionJournalEntry(entry_id="lore_honor", title="Honor")
    nimitz = ChatSessionJournalEntry(entry_id="lore_nimitz", title="Nimitz")
    service.save_chat_session(
        session.id,
        SaveChatSessionRequest(
            title="X", prompt_entry_id="p", journal=[honor, nimitz]
        ),
    )

    # Reordering Honor and Nimitz is forbidden — the prior prefix [Honor,
    # Nimitz] no longer matches.
    with pytest.raises(ProjectServiceError) as exc:
        service.save_chat_session(
            session.id,
            SaveChatSessionRequest(
                title="X", prompt_entry_id="p", journal=[nimitz, honor]
            ),
        )
    assert exc.value.status_code == 409


def test_journal_persists_after_message_locking(tmp_path, monkeypatch):
    # The journal continues to grow once the chat is locked (messages
    # exist) — that's the whole point: new turns detect new names and
    # append them.
    service = _project(tmp_path, monkeypatch)
    session = service.create_chat_session(
        CreateChatSessionRequest(title="X", prompt_entry_id="p")
    )
    initial = [
        ChatSessionJournalEntry(entry_id="lore_honor", title="Honor", added_at_turn=0),
    ]
    locked = service.save_chat_session(
        session.id,
        SaveChatSessionRequest(
            title="X",
            prompt_entry_id="p",
            journal=initial,
            messages=[ChatSessionMessage(role="user", content="hello")],
        ),
    )
    assert len(locked.journal) == 1

    extended_journal = initial + [
        ChatSessionJournalEntry(entry_id="lore_samantha", title="Samantha", added_at_turn=1),
    ]
    later = service.save_chat_session(
        session.id,
        SaveChatSessionRequest(
            title="X",
            prompt_entry_id="p",
            journal=extended_journal,
            messages=[
                ChatSessionMessage(role="user", content="hello"),
                ChatSessionMessage(role="assistant", content="hi"),
                ChatSessionMessage(role="user", content="and samantha"),
            ],
        ),
    )
    assert [e.entry_id for e in later.journal] == ["lore_honor", "lore_samantha"]
