"""ChatSession.inputs round-trip — drafts persist across save+read so a
half-configured chat (user typed inputs but hasn't sent yet) restores
when the user comes back later.
"""

from __future__ import annotations

from pathlib import Path

from app.models import CreateChatSessionRequest, SaveChatSessionRequest
from app.services.project_service import ProjectService


def _project(tmp_path: Path, monkeypatch) -> ProjectService:
    monkeypatch.setattr(
        "app.services.machine_settings.config_path",
        lambda: tmp_path / "machine_settings.yaml",
    )
    service = ProjectService.created_at(tmp_path / "project", "Demo")
    return service


def test_inputs_default_to_empty_dict(tmp_path, monkeypatch):
    service = _project(tmp_path, monkeypatch)
    session = service.create_chat_session(CreateChatSessionRequest(title="Test"))
    assert session.inputs == {}

    fresh = service.read_chat_session(session.id)
    assert fresh.inputs == {}


def test_inputs_round_trip_through_save(tmp_path, monkeypatch):
    service = _project(tmp_path, monkeypatch)
    session = service.create_chat_session(
        CreateChatSessionRequest(title="Brainstorm", prompt_entry_id="prompt_x")
    )
    saved = service.save_chat_session(
        session.id,
        SaveChatSessionRequest(
            title="Brainstorm",
            prompt_entry_id="prompt_x",
            inputs={
                "topic": "haunted lighthouses",
                "scenes": [
                    {"id": "scene_xyz", "kind": "scene", "title": "Opening"},
                    {"id": "preset:full_outline", "kind": "preset", "title": "Full Outline"},
                ],
            },
        ),
    )
    assert saved.inputs["topic"] == "haunted lighthouses"
    assert isinstance(saved.inputs["scenes"], list)
    assert len(saved.inputs["scenes"]) == 2

    fresh = service.read_chat_session(session.id)
    assert fresh.inputs == saved.inputs


def test_inputs_survive_message_locking(tmp_path, monkeypatch):
    # Once messages exist the prompt+assistant+brief lock, but inputs
    # are part of the locked snapshot and don't get rejected on save —
    # they're rendered into the system_prompt by that point and the
    # frontend keeps them visible read-only.
    from app.models import ChatSessionMessage

    service = _project(tmp_path, monkeypatch)
    session = service.create_chat_session(
        CreateChatSessionRequest(title="X", prompt_entry_id="p")
    )
    locked = service.save_chat_session(
        session.id,
        SaveChatSessionRequest(
            title="X",
            prompt_entry_id="p",
            inputs={"topic": "lighthouses"},
            messages=[ChatSessionMessage(role="user", content="hello")],
        ),
    )
    assert locked.inputs == {"topic": "lighthouses"}
    # Saving again with the same inputs is fine; saving with different
    # inputs is also fine (they're not part of the lock-checked fields).
    later = service.save_chat_session(
        session.id,
        SaveChatSessionRequest(
            title="X",
            prompt_entry_id="p",
            inputs={"topic": "different"},
            messages=[ChatSessionMessage(role="user", content="hello")],
        ),
    )
    assert later.inputs == {"topic": "different"}
