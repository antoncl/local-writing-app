"""A card and its scene: attach, detach, and the displayed text (ADR-0097 §3, §4).

Composed onto `ProjectService` beside `PlotMixin`. A card's `scene` is owned by
these endpoints (and realize / seed): `save_card` keeps the on-disk value. While
a card is written its own title and body are frozen and it shows its scene's
title and summary (`card_text.py`); this module is where text moves between the
two — on attach, on detach, and when the board edits a written card's text.
"""

from __future__ import annotations

from typing import Any

from app.models import (
    AttachCardRequest,
    CardEntry,
    CardTextRequest,
    DetachCardRequest,
    SaveCardRequest,
    SaveSceneRequest,
)
from app.services.project.decks import without_planned
from app.services.project.errors import ProjectServiceError

_SCENE_FIELD = "scene"
_SUMMARY_FIELD = "summary"
_PAGE_STATUS_FIELD = "page_status"


def _text_choice_required(scene_summary: str, card_synopsis: str) -> ProjectServiceError:
    return ProjectServiceError(
        "The scene's summary and the card's synopsis differ; choose which to keep.",
        409,
        {"code": "text_choice_required", "scene_summary": scene_summary, "card_synopsis": card_synopsis},
    )


def _without_scene(metadata: dict[str, Any]) -> dict[str, Any]:
    """`metadata` with no `scene`, and no stored `on_page` — that status is derived
    from the scene, so with none it would read stale."""
    kept = {key: value for key, value in metadata.items() if key != _SCENE_FIELD}
    if kept.get(_PAGE_STATUS_FIELD) == "on_page":
        del kept[_PAGE_STATUS_FIELD]
    return kept


class CardSceneMixin:
    def _write_card_fields(
        self,
        card: CardEntry,
        *,
        title: str | None = None,
        body: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CardEntry:
        """The internal card write that may set `scene` (realize, attach, detach)
        or change a written card's frozen text — straight to the one write path,
        past `save_card`'s pin. Fields left None keep the card's own."""
        return self._write_card(
            card.id,
            SaveCardRequest(
                title=card.title if title is None else title,
                body=card.body if body is None else body,
                entry_type=card.entry_type,
                metadata=card.metadata if metadata is None else metadata,
                base_revision=card.revision,
            ),
        )

    def _set_scene_summary(self, scene_id: str, text: str) -> None:
        """Write a scene's `summary` through its own save, so validation and the
        session-boundary capture apply. The one place a card's synopsis reaches a
        scene."""
        scene = self.read_scene(scene_id)
        if str(scene.metadata.get(_SUMMARY_FIELD) or "") == text:
            return
        self.save_scene(
            scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=None,
                status=scene.status,
                entry_type=scene.entry_type,
                metadata={**scene.metadata, _SUMMARY_FIELD: text},
            ),
        )

    def attach_card(self, entry_id: str, request: AttachCardRequest) -> CardEntry:
        """Bind a card to an existing scene (ADR-0097 §1, §3, §4). The card then
        shows the scene's title and summary; an empty summary is seeded from the
        card's synopsis, and two different non-empty texts make the writer choose
        (`request.text`)."""
        root = self._require_project()
        card = self.read_card(entry_id)
        if card.metadata.get(_SCENE_FIELD):
            raise ProjectServiceError("This card already has a scene; detach it first.", 409)
        self._reject_inherited_book_local(
            entry_id, self._build_node_index().by_id.get(entry_id), root, noun="card"
        )
        if request.scene_id not in {scene_id for scene_id, _title in self._manuscript_scene_nodes()}:
            raise ProjectServiceError(f"{request.scene_id} is not a scene of this manuscript.", 422)
        self._require_scene_unheld(request.scene_id, entry_id)
        summary = str(self.read_scene(request.scene_id).metadata.get(_SUMMARY_FIELD) or "")
        synopsis = card.body.strip()
        if not summary.strip():
            if synopsis:
                self._set_scene_summary(request.scene_id, synopsis)
        elif synopsis and synopsis != summary.strip():
            if request.text is None:
                raise _text_choice_required(summary, synopsis)
            if request.text == "card":
                self._set_scene_summary(request.scene_id, synopsis)
        return self._write_card_fields(
            card, metadata={**without_planned(card.metadata), _SCENE_FIELD: request.scene_id}
        )

    def detach_card(self, entry_id: str, request: DetachCardRequest) -> CardEntry:
        """Unbind a card from its scene (ADR-0097 §3, §4). The card takes the
        scene's title; its body becomes the summary unless it holds a different
        synopsis of its own, in which case the writer chooses (`request.text`).
        The scene file is untouched."""
        root = self._require_project()
        card = self.read_card(entry_id)
        scene_id = card.metadata.get(_SCENE_FIELD)
        if not scene_id:
            raise ProjectServiceError("This card has no scene.", 409)
        self._reject_inherited_book_local(
            entry_id, self._build_node_index().by_id.get(entry_id), root, noun="card"
        )
        scene = self.read_scene(str(scene_id))
        summary = str(scene.metadata.get(_SUMMARY_FIELD) or "")
        body = card.body
        if not body.strip() or body.strip() == summary.strip():
            body = summary
        elif summary.strip():
            if request.text is None:
                raise _text_choice_required(summary, body.strip())
            if request.text == "scene":
                body = summary
        return self._write_card_fields(
            card, title=scene.title, body=body, metadata=_without_scene(card.metadata)
        )

    def set_card_text(self, entry_id: str, request: CardTextRequest) -> CardEntry:
        """Edit the title and/or synopsis a card DISPLAYS (ADR-0097 §3): the scene's
        while the card is written, the card's own otherwise."""
        if request.title is not None and not request.title.strip():
            raise ProjectServiceError("Title cannot be empty.", 422)
        root = self._require_project()
        card = self.read_card(entry_id)
        # An inherited card is ancestor canon either way: its own file, or a scene
        # in the ancestor's manuscript.
        self._reject_inherited_book_local(
            entry_id, self._build_node_index().by_id.get(entry_id), root, noun="card"
        )
        scene_id = card.metadata.get(_SCENE_FIELD)
        if not scene_id:
            self._write_card_fields(card, title=request.title, body=request.synopsis)
            return self.read_card(entry_id)
        scene_id = str(scene_id)
        if request.title is not None and request.title != self.read_scene(scene_id).title:
            self.rename_structure_node(scene_id, request.title)
        if request.synopsis is not None:
            self._set_scene_summary(scene_id, request.synopsis)
        return self.read_card(entry_id)
