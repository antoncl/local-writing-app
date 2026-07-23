"""AI policy resolves over the declared layer chain (#312, slice F of #7).

The rule, decided on #312: **nearest explicit statement wins, and a chain that
states nothing anywhere is `off`.** An ancestor's policy is a default for
everything beneath it, not a lock — a universe set to `cloud-allowed` lets its
books use the model without each one saying so, and a book may still say `off`.

The alternative that was rejected is *most-restrictive along the chain*. Two
tests here fail under it, deliberately and by name
(`test_a_nearer_layer_may_be_more_permissive_than_its_ancestor`,
`test_a_book_may_switch_the_model_on_under_a_universe_that_left_it_off`); if a
future change flips the rule, those are the two that must be argued with rather
than edited.

What makes any of it expressible is that `_new_project_manifest` no longer seeds
`settings.ai.policy: "off"`. While it did, every layer stated `off` at birth,
"no opinion" did not exist on disk, and most-restrictive would have pinned every
descendant off forever — pinned here by
`test_a_created_project_states_no_policy_of_its_own`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from layer_fixtures import (
    declare,
    declare_full_chain,
    make_project_folder,
    set_projects_root,
)
from project_fixtures import open_test_project

from app.services.project_service import ProjectService


def _set_policy(service: Any, root: Path, policy: Any) -> None:
    manifest = service._read_yaml(root / "project.yaml")
    manifest.setdefault("settings", {}).setdefault("ai", {})["policy"] = policy
    service._write_yaml(root / "project.yaml", manifest)


class AiPolicyChainTests(unittest.TestCase):
    """A three-level chain: shelf › universe › book, fully declared."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.universe = self.base / "universe"
        self.book = self.universe / "book"
        self.service = open_test_project(self.book, "Book")
        make_project_folder(self.service, self.universe, "Universe")
        declare_full_chain(self.service, self.book, self.base)

    # ----- the rule -----------------------------------------------------

    def test_an_ancestor_policy_reaches_a_book_that_states_none(self) -> None:
        """The feature. Set it once on the universe, every book below inherits."""
        _set_policy(self.service, self.universe, "cloud-allowed")
        self.assertEqual(self.service.ai_policy(), "cloud-allowed")

    def test_a_book_may_switch_the_model_on_under_a_universe_that_left_it_off(self) -> None:
        """⚠ Fails under most-restrictive, which is the point of writing it.

        Most-restrictive resolves this chain to `off`, because the universe says
        so and nothing beneath it may relax that. "B, but overrideable" says the
        nearer, deliberate statement is the answer.
        """
        _set_policy(self.service, self.universe, "off")
        _set_policy(self.service, self.book, "cloud-allowed")
        self.assertEqual(self.service.ai_policy(), "cloud-allowed")

    def test_a_nearer_layer_may_be_more_permissive_than_its_ancestor(self) -> None:
        """The same rule one notch down the scale — `local-only` → `cloud-allowed`.

        Separate from the `off` case because most-restrictive and nearest-wins
        agree on tightening and disagree only on relaxing; a suite that pinned
        the rule solely through `off` would leave the ordering of the other two
        values untested.
        """
        _set_policy(self.service, self.universe, "local-only")
        _set_policy(self.service, self.book, "cloud-allowed")
        self.assertEqual(self.service.ai_policy(), "cloud-allowed")

    def test_a_book_may_still_switch_itself_off_under_a_permissive_universe(self) -> None:
        _set_policy(self.service, self.universe, "cloud-allowed")
        _set_policy(self.service, self.book, "off")
        self.assertEqual(self.service.ai_policy(), "off")

    def test_a_chain_that_states_nothing_anywhere_is_off(self) -> None:
        """The floor. Absent everywhere is not "unconstrained"."""
        self.assertEqual(self.service.ai_policy(), "off")

    def test_the_outermost_statement_is_used_when_nothing_nearer_speaks(self) -> None:
        """The shelf is a layer too — resolution does not stop at the parent."""
        _set_policy(self.service, self.base, "local-only")
        self.assertEqual(self.service.ai_policy(), "local-only")

    def test_current_project_reports_the_same_resolved_value(self) -> None:
        """The two readers must not disagree — that is #433's lesson restated.

        `ProjectInfo.ai_policy` is what the settings pane renders and
        `ai_policy()` is what the five AI routes enforce with. A pane showing
        `off` over a chain that permits cloud calls is worse than either answer.
        """
        _set_policy(self.service, self.universe, "cloud-allowed")
        self.assertEqual(self.service.current_project().ai_policy, "cloud-allowed")
        self.assertEqual(self.service.current_project().ai_policy, self.service.ai_policy())

    # ----- what the chain is, and is not --------------------------------

    def test_an_undeclared_ancestor_contributes_nothing(self) -> None:
        """Inheritance is declared (#309). A folder that happens to sit above
        this one may not hand it a permission it never asked for — which is the
        permission-bug framing that blocked this slice until #337/#309 landed.
        """
        declare(self.service, self.book, [], base=self.base)
        _set_policy(self.service, self.universe, "cloud-allowed")
        self.assertEqual(self.service.ai_policy(), "off")

    def test_a_gap_in_the_chain_resolves_from_the_declared_grandparent(self) -> None:
        """Gaps are legal by construction, so skipping a level is a choice, not
        a truncation: the shelf still speaks when the universe is not declared.
        """
        declare(self.service, self.book, [self.base], base=self.base)
        _set_policy(self.service, self.base, "local-only")
        _set_policy(self.service, self.universe, "cloud-allowed")
        self.assertEqual(self.service.ai_policy(), "local-only")

    def test_a_project_outside_the_machine_root_is_a_chain_of_one(self) -> None:
        """No root configured means no walk (#429), so nothing above can grant
        anything. Fail-closed survives the degenerate case.
        """
        _set_policy(self.service, self.universe, "cloud-allowed")
        set_projects_root(None)
        self.assertEqual(self.service.ai_policy(), "off")

    # ----- fail-closed, in the two places it belongs --------------------

    def test_a_typo_states_off_rather_than_deferring_to_an_ancestor(self) -> None:
        """An unrecognised *value* is a statement we cannot honour, so it falls
        closed (`decisions_ai_permission_fails_closed`) — and it is still a
        statement, so it stops the search. Deferring to the ancestor instead
        would let a mistyped character silently hand the project the universe's
        broader permission, which is the one outcome nobody would notice.
        """
        _set_policy(self.service, self.universe, "cloud-allowed")
        for bad in ("cloud_allowed", "", "ON", None, 3):
            with self.subTest(policy=bad):
                _set_policy(self.service, self.book, bad)
                reopened = ProjectService.opened_at(self.book)
                self.assertEqual(reopened.ai_policy(), "off")
                self.assertEqual(reopened.current_project().ai_policy, "off")

    def test_an_unreadable_layer_states_off_rather_than_disappearing(self) -> None:
        """A manifest we cannot parse is a permission we cannot read.

        The sibling property — an unreadable *ancestor* cannot take away a
        policy the open project states for itself — is
        `test_an_unreadable_ancestor_manifest_cannot_change_the_answer` in
        `test_ai_policy_read.py`. Both follow from nearest-explicit-wins over a
        walk that never raises.
        """
        _set_policy(self.service, self.base, "cloud-allowed")
        (self.universe / "project.yaml").write_text("title: [unclosed\n  bad: :\n", encoding="utf-8")
        self.assertEqual(self.service.ai_policy(), "off")

    # ----- the seed that had to go --------------------------------------

    def test_a_created_project_states_no_policy_of_its_own(self) -> None:
        """`create_project` used to write `settings.ai.policy: "off"`.

        Nothing about the default changed — a fresh flat project still resolves
        to `off`. What changed is that it is no longer *written down*, so a book
        created under a `cloud-allowed` universe inherits it instead of silently
        pinning itself shut on the day it was made.
        """
        fresh = self.base / "universe" / "fresh"
        service = ProjectService.created_at(fresh, "Fresh")
        manifest = service._read_yaml(fresh / "project.yaml")
        self.assertNotIn("ai", manifest.get("settings", {}))
        self.assertEqual(service.ai_policy(), "off")

        declare_full_chain(service, fresh, self.base)
        _set_policy(service, self.universe, "cloud-allowed")
        self.assertEqual(service.ai_policy(), "cloud-allowed")


if __name__ == "__main__":
    unittest.main()
