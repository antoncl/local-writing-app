# Flags from a conversation reply (ADR-0100 §3): one extraction turn that
# continues the chat and reads the chosen assistant reply's suggestions about
# the scene as line edits and notes, like the commit's `run_entry_patch_extraction`
# (`extraction.py`) — a cached continuation under `lore_mode="used"`, one firm
# retry on an unreadable reply, exactly one trace record per call. The scene's
# CURRENT text rides in the cue, so quotes come from the page as it is now, not
# from an older version in the conversation's own system prompt.
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models import (
    AIChatRequest,
    ChatMessage,
    ChatUsage,
    ExtractFlagsRequest,
    FlagExtraction,
    FlagNote,
)
from app.models.ai import LineNote
from app.services.ai.chat import run_chat_turn
from app.services.ai.entry_patch import load_json_object
from app.services.ai.extraction import (
    RETRY_CUE,
    _coalesce_turns,
    _messages_with_cue,
    _reply_trace_fields,
    _sum_costs,
    _sum_usage,
)
from app.services.ai.follow_ups import lore_names
from app.services.ai.line_edits import LINE_EDITS_RESPONSE_SCHEMA, edit_items
from app.services.ai.line_notes import note_items
from app.services.ai.name_matcher import normalise_name
from app.services.project.errors import ProjectServiceError

if TYPE_CHECKING:
    from app.models import LineEdit
    from app.services.project_service import ProjectService

FLAGS_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "edits": LINE_EDITS_RESPONSE_SCHEMA["properties"]["edits"],
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "problem": {"type": "string"},
                    "entry": {"type": "string"},
                },
                "required": ["quote", "problem"],
            },
        },
    },
    "required": ["edits", "notes"],
}

FLAGS_UNREADABLE_ERROR = "The model's reply wasn't readable as a list of edits and notes."
FLAGS_NO_SCENE_ERROR = "The scene has no text to place flags on."

FLAGS_CUE = (
    "The author wants the suggestions in your LAST reply placed on the scene, "
    "so they can decide on each one there. Here is the scene as it is now:\n\n"
    "<scene_text>\n{scene_text}\n</scene_text>\n\n"
    "Reply with ONLY this JSON object — no preamble, no commentary, no code "
    'fences:\n{{"edits": [{{"find": "...", "replace": "...", "reason": "..."}}], '
    '"notes": [{{"quote": "...", "problem": "...", "entry": "..."}}]}}\n\n'
    "- Report only what your last reply actually said. A change it proposed is "
    'an edit; a remark about a passage is a note. Nothing else — if it '
    'suggested nothing about the text, reply {{"edits": [], "notes": []}}.\n'
    "- If your last reply offered alternatives for the same problem (two routes, "
    "options A and B, either-or), don't choose between them: make no edit for "
    "any of them, and put ONE note on the passage naming each alternative and "
    "its trade-off, so the author chooses in the conversation.\n"
    '- Copy every "find" and "quote" character for character from the scene '
    "text above and from nowhere else — not from earlier versions of the scene "
    "elsewhere in this conversation. Keep each within a single paragraph, and "
    "long enough to occur only once.\n"
    '- New text placed after a passage is an edit: "find" is the passage and '
    '"replace" is the passage followed by the new text, with a blank line '
    "between paragraphs.\n"
    '- "entry" is the name of the lore entry a note is about, or "" when it is '
    "about none."
)


def render_flags_cue(scene_text: str) -> str:
    """The extraction turn's cue, carrying the scene's current text."""
    return FLAGS_CUE.format(scene_text=scene_text)


def _read_flags(raw: str) -> tuple[list[LineEdit], list[LineNote]] | None:
    """The edits and notes in ``raw``, or ``None`` when it isn't a JSON object.
    A missing ``edits`` / ``notes`` key reads as an empty list here."""
    obj = load_json_object(raw)
    if obj is None:
        return None
    edits = obj.get("edits")
    notes = obj.get("notes")
    return (
        edit_items(edits if isinstance(edits, list) else []),
        note_items(notes if isinstance(notes, list) else [], entry_required=False),
    )


def _flag_notes(project: ProjectService, notes: list[LineNote], used_ids: list[str]) -> list[FlagNote]:
    """``notes`` with each ``entry`` resolved (ADR-0100 §3): first as an id the
    turn showed (an explicit pick), then as a lore title or alias; exactly one
    match sets ``entry_id`` / ``entry_name``, otherwise the note stays a plain
    remark."""
    ids_by_name: dict[str, set[str]] = {}
    titles: dict[str, str] = {}
    if any(n.entry for n in notes):
        ids_by_name, titles = lore_names(project)
    out: list[FlagNote] = []
    for note in notes:
        entry_id: str | None = None
        # A pick is any node the prompt used (the scene too); only a lore entry
        # can be what a note is about.
        if note.entry in used_ids and note.entry in titles:
            entry_id = note.entry
        elif note.entry.strip():
            matches = ids_by_name.get(normalise_name(note.entry), set())
            if len(matches) == 1:
                entry_id = next(iter(matches))
        out.append(
            FlagNote(
                quote=note.quote,
                problem=note.problem,
                entry_id=entry_id,
                entry_name=titles.get(entry_id, entry_id) if entry_id else None,
            )
        )
    return out


async def run_flag_extraction(project: ProjectService, request: ExtractFlagsRequest) -> FlagExtraction:
    """Run the flag extraction turn on the chat, ending at the chosen reply.

    Each provider call (the turn, and the one garbled retry) runs through
    `run_chat_turn`, which records its cost on the chat; the last call's total
    rides back as `cost_usd_total`. Exactly ONE `ai_flag_extraction` trace
    record is written per call, on every exit path."""
    trace: dict[str, Any] = {"event": "ai_flag_extraction", "chat_id": request.chat_id}

    def fail(
        error: str,
        details: dict[str, Any] | None = None,
        *,
        cost_usd: float | None = None,
        usage: ChatUsage | None = None,
        cost_usd_total: float | None = None,
    ) -> FlagExtraction:
        project.record_ai_trace(
            {**trace, "edits": 0, "notes": 0, **(details or {}), "ok": False, "error": error}
        )
        return FlagExtraction(
            ok=False, error=error, cost_usd=cost_usd, usage=usage, cost_usd_total=cost_usd_total
        )

    if not request.scene_text.strip():
        return fail(FLAGS_NO_SCENE_ERROR)
    try:
        chat = project.read_chat_session(request.chat_id)
    except ProjectServiceError as exc:
        return fail(f"Couldn't read the chat to place flags: {exc.message}")

    turn_messages = _messages_with_cue(request.messages, render_flags_cue(request.scene_text))

    async def turn(messages: list[ChatMessage]):
        return await run_chat_turn(
            project,
            AIChatRequest(
                assistant_id=request.assistant_id,
                system_prompt=chat.system_prompt,
                messages=messages,
                chat_id=request.chat_id,
            ),
            lore_mode="used",
            response_schema=FLAGS_RESPONSE_SCHEMA,
        )

    reply = await turn(turn_messages)
    if not reply.ok or not (reply.content or "").strip():
        error = reply.error or "The model returned nothing to place."
        return fail(
            error,
            _reply_trace_fields(reply),
            cost_usd=reply.cost_usd,
            usage=reply.usage,
            cost_usd_total=reply.cost_usd_total,
        )

    cost, usage, cost_usd_total = reply.cost_usd, reply.usage, reply.cost_usd_total
    # A cut-off reply is never trusted: a repaired half-list would silently drop flags.
    read = None if reply.truncated else _read_flags(reply.content)
    first_reply, final_reply, retried = reply, reply, False

    # One firm retry on an unreadable reply, as a commit's (#1036); a second is terminal.
    if read is None:
        retried = True
        retry = await turn(
            _coalesce_turns(
                [
                    *turn_messages,
                    ChatMessage(role="assistant", content=reply.content),
                    ChatMessage(role="user", content=RETRY_CUE),
                ]
            )
        )
        cost = _sum_costs(cost, retry.cost_usd)
        usage = _sum_usage(usage, retry.usage)
        if retry.ok:
            cost_usd_total = retry.cost_usd_total
            final_reply = retry
            if not retry.truncated:
                read = _read_flags(retry.content or "")

    if read is None:
        return fail(
            FLAGS_UNREADABLE_ERROR,
            {
                **_reply_trace_fields(final_reply),
                "retried": retried,
                "first_raw_reply": first_reply.content,
            },
            cost_usd=cost,
            usage=usage,
            cost_usd_total=cost_usd_total,
        )

    edits, raw_notes = read
    notes = _flag_notes(project, raw_notes, chat.used_node_ids)
    project.record_ai_trace(
        {
            **trace,
            "edits": len(edits),
            "notes": len(notes),
            **_reply_trace_fields(final_reply),
            "ok": True,
            "error": None,
            "retried": retried,
            "first_raw_reply": first_reply.content if retried else None,
        }
    )
    return FlagExtraction(
        edits=edits, notes=notes, cost_usd=cost, usage=usage, cost_usd_total=cost_usd_total
    )
