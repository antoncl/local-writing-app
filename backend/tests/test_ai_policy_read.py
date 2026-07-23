"""`ai_policy()` — the permission without the hierarchy walk (#433).

Five AI routes want one scalar and were calling `current_project()`, which
builds the whole `ProjectInfo`: the ancestor enumeration with a manifest parse
per project ancestor (#311's titles) and an `iterdir()` plus a manifest parse
per child project (#310's roster). On the prompt-preview path that ran on a
typing debounce.

The tests that matter here are the two that *fail on a revert*: one counts the
files read, one proves the answer survives an ancestor the walk cannot read.
Asserting only the returned value would pass just as well against
`current_project()`, which is the thing being moved away from.
"""

from __future__ import annotations

import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from layer_fixtures import declare_full_chain, make_project_folder
from project_fixtures import open_test_project

from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


def _set_policy(service: Any, root: Path, policy: Any) -> None:
    manifest = service._read_yaml(root / "project.yaml")
    manifest.setdefault("settings", {}).setdefault("ai", {})["policy"] = policy
    service._write_yaml(root / "project.yaml", manifest)


class AiPolicyReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()

    # ----- the value ----------------------------------------------------

    def test_it_reports_each_policy_the_manifest_can_hold(self) -> None:
        for policy in ("off", "local-only", "cloud-allowed"):
            with self.subTest(policy=policy):
                root = self.base / f"book-{policy}"
                service = open_test_project(root, "Book")
                _set_policy(service, root, policy)
                self.assertEqual(service.ai_policy(), policy)

    def test_a_project_with_no_ai_block_is_off(self) -> None:
        service = open_test_project(self.base / "bare", "Bare")
        self.assertEqual(service.ai_policy(), "off")

    def test_a_hand_edited_policy_typo_does_not_make_the_project_unopenable(self) -> None:
        """A value the Literal does not admit must fall closed in BOTH readers.

        Two failures in one, which is why they are one test.

        *Fail-closed* (`decisions_ai_permission_fails_closed`): returning the
        raw string would type-check nowhere and compare unequal to every guard
        downstream, which is a silent **allow** in any code testing for
        `== "off"`. A rejected AI action is always cheaper than an unwanted one.

        *Unopenable*: `current_project()` passes the policy into `ProjectInfo`'s
        `AIPolicy` Literal. Un-normalised, a typo raised a Pydantic
        `ValidationError` — which `translate_errors` does not catch, so it
        escaped as a 500 from `GET /api/project` and from
        `POST /api/project/open`, where the call precedes
        `current_scope.set(...)`. One mistyped character made the project
        permanently unopenable, with an error naming nothing.

        Both readers are asserted because guarding only the one that noticed is
        precisely the defect: that is how they came to disagree.
        """
        for bad in ("cloud_allowed", "", "ON", None, 3):
            with self.subTest(policy=bad):
                root = self.base / f"typo-{bad!r}"
                service = open_test_project(root, "Typo")
                _set_policy(service, root, bad)
                reopened = ProjectService.opened_at(root)
                self.assertEqual(reopened.ai_policy(), "off")
                self.assertEqual(reopened.current_project().ai_policy, "off")

    def test_no_project_open_raises_rather_than_answering_off(self) -> None:
        """The routes turn this into "off" themselves.

        Answering "off" here would make "no project" indistinguishable from a
        project that chose it, and would hide a resolution bug behind a
        plausible permission.
        """
        with self.assertRaises(ProjectServiceError):
            ProjectService().ai_policy()

    # ----- the point of the change -------------------------------------

    def test_it_reads_one_file_regardless_of_how_deep_the_chain_is(self) -> None:
        """The regression test. `current_project()` scales with the shelf.

        A four-level chain with three sibling books: `current_project()` parses
        the root manifest several times over, one manifest per project ancestor
        and one per child. `ai_policy()` must not care that any of that exists.
        """
        universe = self.base / "universe"
        series = universe / "series"
        book = series / "book"
        service = open_test_project(book, "Book")
        make_project_folder(service, universe, "Universe")
        make_project_folder(service, series, "Series")
        declare_full_chain(service, book, self.base)
        for name in ("part-one", "part-two", "part-three"):
            make_project_folder(service, book / name, name)
        _set_policy(service, book, "cloud-allowed")

        reads: list[Path] = []
        original = service._read_yaml

        def counting(path: Path) -> dict[str, Any]:
            reads.append(Path(path))
            return original(path)

        # Shadowed on the *instance*, not patched onto `ProjectService`: the
        # class is module-global, so a class-level patch would collect reads
        # from any test running beside this one and turn the assertion below
        # into an unreproducible flake the day the suite gains a parallel
        # runner.
        service._read_yaml = counting  # type: ignore[method-assign]
        try:
            self.assertEqual(service.ai_policy(), "cloud-allowed")
        finally:
            del service._read_yaml  # type: ignore[attr-defined]

        self.assertEqual(
            reads,
            [book / "project.yaml"],
            "ai_policy() must read the open project's manifest and nothing else; "
            f"it read {[str(p) for p in reads]}",
        )

    def test_an_unreadable_ancestor_manifest_cannot_change_the_answer(self) -> None:
        """A property test, NOT a regression test for #433 — stated plainly
        because claiming otherwise is how a suite grows tests that guard
        nothing.

        This passes against the pre-#433 code too: PR #420 already guarded the
        enumeration (`_readable_project_title`), so `current_project()` survives
        a malformed ancestor manifest on its own. What makes it *structurally*
        impossible here is not reading the ancestor at all, and the test that
        actually pins that is the read-count one above.

        It earns its place as an end-to-end statement of the property, because
        the failure it describes was real: the five AI routes catch
        `ProjectServiceError` and fall back to `policy="off"`, so before #420 a
        malformed `project.yaml` in a folder the author had not touched in
        months silently turned AI off with nothing naming the cause.
        """
        universe = self.base / "universe"
        book = universe / "book"
        service = open_test_project(book, "Book")
        make_project_folder(service, universe, "Universe")
        declare_full_chain(service, book, self.base)
        _set_policy(service, book, "cloud-allowed")

        (universe / "project.yaml").write_text("title: [unclosed\n  bad: :\n", encoding="utf-8")

        self.assertEqual(service.ai_policy(), "cloud-allowed")


if __name__ == "__main__":
    unittest.main()
