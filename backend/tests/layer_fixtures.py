"""Shared layered-project fixture helpers (#309).

Before #309 a test built a folder tree, pointed `projects_base_folder` at the
top of it, and the walk *inferred* a layer per folder. Inheritance is now
**declared**, and a layer is a **project** — a folder with a `project.yaml`,
which is also the only place a name to display comes from — so a fixture has to
say both things: these folders are projects, and this project inherits from
them.

`declare_full_chain` reproduces exactly what the old inference produced, which
is what nearly every existing fixture meant. A test that wants a *partial*
chain — a gap, an undeclared ancestor, a folder that is deliberately not a
project — should call `declare` directly and name the layers it wants, because
that is the interesting case and it should be visible in the test.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

MANIFEST = "project.yaml"


def ancestors_between(root: Path, base: Path) -> list[Path]:
    """Folders from `base` down to (not including) `root`, outermost first."""
    root, base = root.resolve(), base.resolve()
    chain = [root, *root.parents]
    if base not in chain:
        return []
    return list(reversed(chain[: chain.index(base) + 1]))[:-1]


def make_project_folder(service: Any, folder: Path, title: str | None = None) -> None:
    """Give `folder` the minimal manifest that makes it a project.

    Deliberately not `create_project`: that also seeds `scenes/`, a first scene
    and a `project.md`, which would change every node count a layered index test
    asserts. What makes a folder a project is the manifest; the rest is content.
    """
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder / MANIFEST).exists():
        service._write_yaml(folder / MANIFEST, {"title": title or folder.name})


def declare(service: Any, root: Path, layers: list[Path], *, base: Path | None = None) -> None:
    """Declare `layers` as `root`'s inheritance, making each one a project.

    `base` sets `projects_base_folder` when given — the outer bound the
    declaration selects within. Entries are stored relative to the project, the
    same form the app writes.
    """
    manifest = service._read_yaml(root / MANIFEST)
    if base is not None:
        manifest.setdefault("settings", {})["projects_base_folder"] = str(base)
    for folder in layers:
        make_project_folder(service, folder)
    manifest["inherits"] = [os.path.relpath(folder, root).replace("\\", "/") for folder in layers]
    service._write_yaml(root / MANIFEST, manifest)


def declare_full_chain(service: Any, root: Path, base: Path) -> None:
    """Point `root` at `base` and inherit from every folder between them.

    The pre-#309 behaviour, stated explicitly.
    """
    declare(service, root, ancestors_between(root, base), base=base)
