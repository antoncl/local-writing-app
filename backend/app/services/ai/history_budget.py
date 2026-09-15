"""#1958: an opt-in per-turn cap on the conversation history sent to the model.

Conversation history grows unbounded — every turn forwards the whole transcript.
On a small Ollama `num_ctx` that overflows the window and the daemon truncates
from the FRONT, dropping the system prompt and lore (the highest-value context).
`fit_history_window` walks the transcript newest→oldest, keeps each user+assistant
round whole, and drops the oldest rounds past a token budget — front-truncation
the app controls, so the system prompt and lore survive instead.

The pure half mirrors `lore_budget`: no project access, the caller injects the
token estimator, so it is tested as a function. `apply_history_window` is the
project-aware seam helper both chat-send routes share. A blank budget resolves
to `None` (unlimited) and every function here is a no-op — so an assistant that
sets nothing sends the full transcript, byte-identical to today, and cloud
prefix-caching is untouched.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models import HistoryFit
from app.services.ai.profiles.base import default_token_count

if TYPE_CHECKING:
    from app.services.ai.call_resolver import ResolvedCall
    from app.services.machine_settings import MachineSettings


@dataclass(frozen=True)
class BudgetedHistory:
    """`fit_history_window`'s result: the messages to send (a contiguous tail of
    the transcript, always opening on a user turn) and the report the send hands
    back, or `None` when nothing was dropped."""

    messages: list[dict]
    report: HistoryFit | None


def fit_history_window(
    messages: list[dict],
    budget_tokens: int | None,
    *,
    count: Callable[[str], int] = default_token_count,
) -> BudgetedHistory:
    """Keep the newest whole rounds that fit `budget_tokens`, dropping the oldest.

    A round is a user turn plus everything up to the next user turn (its
    assistant reply, and any stray same-role continuation, glued in so a pair is
    never split and an assistant reply is never orphaned). The current turn — the
    trailing user message that triggered the send — is ALWAYS kept, even if it
    alone exceeds the budget (there must be a question to answer; `num_ctx` is
    already clamped to the model max, so the reply just takes what remains).

    `budget_tokens is None` means unlimited: the transcript is returned unchanged
    and no report is made. `count` is the one estimator every profile uses,
    injectable for tests. The kept window always opens on a user message, so a
    leading assistant greeting is dropped with the oldest round rather than sent
    orphaned (providers reject a leading assistant).
    """
    if budget_tokens is None:
        return BudgetedHistory(messages, None)
    user_idxs = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if not user_idxs:
        # No user turn to anchor on (degenerate) — nothing to window.
        return BudgetedHistory(messages, None)

    budget = max(0, budget_tokens)

    def _tokens(lo: int, hi: int) -> int:
        return sum(count(str(messages[j].get("content") or "")) for j in range(lo, hi))

    keep_from = user_idxs[-1]  # the current turn, never dropped
    used = _tokens(keep_from, len(messages))
    # Walk older rounds newest→oldest; admit a whole round only while it fits.
    for i in reversed(user_idxs[:-1]):
        block = _tokens(i, keep_from)
        if used + block > budget:
            break  # this round and everything older is dropped
        used += block
        keep_from = i
    else:
        # Every round fit: if the transcript opens with a leading assistant atom
        # (a template opener, before the first user), keep it too when it fits —
        # so a non-binding budget never drops the opener. It's dropped only when
        # it can't fit, and the window then still opens on a user turn.
        lead = _tokens(0, keep_from)
        if lead and used + lead <= budget:
            used += lead
            keep_from = 0

    dropped_rounds = sum(1 for i in user_idxs[:-1] if i < keep_from)
    if dropped_rounds == 0:
        # Nothing meaningful dropped (whole transcript fit, or only a leading
        # orphan fragment that couldn't) — send it, no report to avoid clutter.
        return BudgetedHistory(messages[keep_from:], None)

    kept_rounds = len(user_idxs) - 1 - dropped_rounds
    report = HistoryFit(
        budget_tokens=budget,
        used_tokens=used,
        kept_rounds=kept_rounds,
        dropped_rounds=dropped_rounds,
    )
    return BudgetedHistory(messages[keep_from:], report)


def apply_history_window(
    messages: list[dict],
    resolved: ResolvedCall,
    settings: MachineSettings,
) -> tuple[list[dict], HistoryFit | None]:
    """Seam helper: window `messages` to the assistant's `history_budget_tokens`,
    counting with the resolved provider+model's estimator so the trim agrees with
    #1957's `num_ctx` sizing. A no-op (returns the list unchanged, report `None`)
    when the budget is blank/unlimited."""
    from app.services.ai.tokens import count_tokens

    def count(text: str) -> int:
        return count_tokens(
            text, provider=resolved.provider, model=resolved.model, settings=settings
        )

    budgeted = fit_history_window(messages, resolved.history_budget_tokens, count=count)
    return budgeted.messages, budgeted.report
