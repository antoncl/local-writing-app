"""A chat turn the model actually received, for tests that drive the send path's
assembly directly (#2586): `expand_and_prepare_chat_blocks` builds the request,
and only a completed send promotes its lore to the chat's baseline
(`commit_chat_lore`, which the stream's `on_done` and an ok non-stream reply
call). A test that wants the NEXT turn to see this one as sent goes through here;
one that models a failed send calls `expand_and_prepare_chat_blocks` alone."""

from __future__ import annotations

from typing import Any

from app.services.ai.chat import (
    PreparedChatTurn,
    commit_chat_lore,
    expand_and_prepare_chat_blocks,
)


def send_turn(project: Any, chat_id: str | None, *args: Any, **kwargs: Any) -> PreparedChatTurn:
    prepared = expand_and_prepare_chat_blocks(project, chat_id, *args, **kwargs)
    commit_chat_lore(project, prepared)
    return prepared
