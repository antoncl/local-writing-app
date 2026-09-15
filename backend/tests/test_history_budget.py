"""#1958: the conversation-history window (`fit_history_window`).

Pure-function tests like `lore_budget`'s — the token estimator is injected. Each
message's content is the string of its own token count, and `count=int`, so the
budget arithmetic in the assertions is exact and readable.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.models import HistoryFit
from app.services.ai.history_budget import (
    apply_history_window,
    fit_history_window,
)


def _m(role: str, tokens: int) -> dict:
    return {"role": role, "content": str(tokens)}


def _count(text: str) -> int:
    return int(text) if text else 0


def _fit(messages, budget):
    return fit_history_window(messages, budget, count=_count)


def test_none_budget_is_unlimited_noop() -> None:
    msgs = [_m("user", 100), _m("assistant", 100), _m("user", 100)]
    result = _fit(msgs, None)
    assert result.messages is msgs
    assert result.report is None


def test_no_user_messages_returns_unchanged() -> None:
    msgs = [_m("assistant", 100), _m("assistant", 100)]
    result = _fit(msgs, 10)
    assert result.messages is msgs
    assert result.report is None


def test_everything_fits_sends_all_without_a_report() -> None:
    msgs = [_m("user", 100), _m("assistant", 100), _m("user", 100)]
    result = _fit(msgs, 100_000)
    assert result.messages == msgs
    assert result.report is None


def test_drops_oldest_round_keeps_newest_and_current() -> None:
    # rounds: [u,a](200) [u,a](200) + current u(100). budget 350 keeps the
    # newest completed round + current (300), drops the oldest.
    msgs = [
        _m("user", 100), _m("assistant", 100),
        _m("user", 100), _m("assistant", 100),
        _m("user", 100),
    ]
    result = _fit(msgs, 350)
    assert result.messages == msgs[2:]  # dropped the first [u,a]
    assert result.messages[0]["role"] == "user"  # window opens on a user turn
    assert result.report == HistoryFit(
        budget_tokens=350, used_tokens=300, kept_rounds=1, dropped_rounds=1
    )


def test_budget_zero_keeps_only_the_current_turn() -> None:
    msgs = [_m("user", 100), _m("assistant", 100), _m("user", 100)]
    result = _fit(msgs, 0)
    assert result.messages == [_m("user", 100)]
    assert result.report is not None
    assert result.report.dropped_rounds == 1
    assert result.report.kept_rounds == 0


def test_current_turn_alone_over_budget_is_still_kept() -> None:
    msgs = [_m("user", 100), _m("assistant", 100), _m("user", 500)]
    result = _fit(msgs, 50)
    assert result.messages == [_m("user", 500)]  # never drop the question
    assert result.report is not None
    assert result.report.used_tokens == 500  # honest, above budget


def test_leading_assistant_kept_when_it_fits() -> None:
    # [a,u,a] history + current u. Under a budget that fits everything (incl. the
    # opener), nothing is dropped and there is no report.
    msgs = [_m("assistant", 50), _m("user", 100), _m("assistant", 100), _m("user", 100)]
    result = _fit(msgs, 350)
    assert result.messages == msgs
    assert result.report is None


def test_leading_assistant_dropped_silently_when_it_cannot_fit() -> None:
    # Same transcript, budget too tight for the opener but fitting every round:
    # the orphan opener is dropped, the window opens on a user, no round-report.
    msgs = [_m("assistant", 50), _m("user", 100), _m("assistant", 100), _m("user", 100)]
    result = _fit(msgs, 340)
    assert result.messages == msgs[1:]  # opener dropped
    assert result.messages[0]["role"] == "user"
    assert result.report is None  # no whole round dropped


def test_never_splits_a_round() -> None:
    # A mid-history oversized round stops the walk; the newer whole round is kept
    # intact, the assistant never orphaned from its user.
    msgs = [
        _m("user", 100), _m("assistant", 900),  # oldest round: 1000
        _m("user", 100), _m("assistant", 100),  # newer round: 200
        _m("user", 100),                          # current: 100
    ]
    result = _fit(msgs, 500)
    assert result.messages == msgs[2:]  # newer round + current, whole
    assert result.report.dropped_rounds == 1


def test_apply_history_window_is_a_noop_when_budget_is_none() -> None:
    msgs = [_m("user", 100), _m("assistant", 100), _m("user", 100)]
    resolved = SimpleNamespace(provider="ollama", model="llama3.2", history_budget_tokens=None)
    sent, fit = apply_history_window(msgs, resolved, settings=None)
    assert sent is msgs
    assert fit is None
