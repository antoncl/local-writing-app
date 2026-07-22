"""The scope of a unit of work is structural, not a convention (#399, ADR-0045).

The race tests (`test_reference_purge`, `test_structure_write_scope`) pin what
happens when a concurrent open lands mid-unit. They cannot pin the *general*
property, and mutation testing shows the hole: teaching `read_metadata_schema`
to consult the process's open project leaves all thirteen of them green,
because none of them exercises a bare no-root call inside a race. Racing every
one of ~50 such call sites is not a test suite, it is a treadmill.

So this file asserts the shape instead, which is what actually makes them safe:

1. A service cannot be re-pointed after construction.
2. The service layer never reads the process's record of what is open.

Together those mean a unit resolves its scope exactly once — at the route's
`CurrentProject` dependency — and every helper below reads the handle it was
called on. The regression these guard against is not a subtle race but the
obvious edit: a new helper "just getting the current project" the way the old
singleton let it.
"""

from __future__ import annotations

import ast
import dataclasses
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.scope import WorkScope
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService

SERVICE_ROOT = Path(__file__).resolve().parents[1] / "app" / "services"


def _modules_importing_the_registry() -> list[str]:
    """Service modules that reach for `app.runtime` — by any import spelling."""
    offenders: list[str] = []
    for path in sorted(SERVICE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.runtime"):
                offenders.append(path.name)
                break
            if isinstance(node, ast.Import) and any(
                alias.name.startswith("app.runtime") for alias in node.names
            ):
                offenders.append(path.name)
                break
    return offenders


class ScopeIsBoundOnceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = ProjectService.created_at(self.root, "Bound Once")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_root_path_cannot_be_reassigned(self) -> None:
        """The pre-#399 data-loss paths all began with this assignment being
        legal — `open_project` did exactly it, on an object other requests held."""
        with self.assertRaises(AttributeError):
            self.service.root_path = self.root.parent  # type: ignore[misc]

    def test_the_scope_itself_is_frozen(self) -> None:
        """Blocking the property is not enough if the scope behind it is mutable."""
        scope = self.service.scope
        assert scope is not None
        with self.assertRaises(dataclasses.FrozenInstanceError):
            scope.root = self.root.parent  # type: ignore[misc]

    def test_two_services_do_not_share_scope(self) -> None:
        """Two units, two projects, no interference — the shape the singleton
        made impossible."""
        other_root = self.root.parent / "other"
        other = ProjectService.created_at(other_root, "Other")

        self.assertEqual(self.service.root_path, self.root)
        self.assertEqual(other.root_path, other_root)

    def test_a_service_with_no_scope_refuses_rather_than_guesses(self) -> None:
        unbound = ProjectService(None)

        self.assertIsNone(unbound.root_path)
        with self.assertRaises(ProjectServiceError) as caught:
            unbound.read_structure()
        self.assertIn("No project is open", str(caught.exception))

    def test_migrations_travel_with_the_scope(self) -> None:
        """`last_migrations` is a property of the open event, so it must arrive
        with the scope rather than be set on the service afterwards — otherwise
        it is a second mutable field to keep in step with the root."""
        service = ProjectService(WorkScope(root=self.root, migrations_applied=("v9_something",)))

        self.assertEqual(service.last_migrations, ("v9_something",))
        self.assertEqual(service.validate_project().migrations_applied, ["v9_something"])


class TheServiceLayerNeverReadsTheRegistryTests(unittest.TestCase):
    def test_no_service_module_imports_app_runtime(self) -> None:
        """`current_scope` answers "what did the client last open", which is a
        question only the route boundary may ask. A service module asking it is
        the whole #399 defect re-introduced, whatever the surrounding care."""
        offenders = _modules_importing_the_registry()

        self.assertEqual(
            offenders,
            [],
            f"these read the process's open project instead of their handle: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
