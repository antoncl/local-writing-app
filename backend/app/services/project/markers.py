"""Shared machinery for in-prose HTML-comment markers (#33 follow-up).

Three ProjectService slices embed HTML-comment markers inline in scene markdown
and each needs the same atomic single-marker rewrite machinery — a module regex,
a body scan that turns matches into records, and capture-group substitution
callbacks that rewrite/remove exactly one marker before an atomic scene write:

- `SceneTodoAnchorsMixin`  — `<!-- todo-anchor:id=ID -->PROSE<!-- /todo-anchor -->`
- `EmbeddedTodosMixin`     — `<!-- embedded-todo:id=ID;status=..;note=.. -->PROSE<!-- /embedded-todo -->`
- `LoreMutationsMixin`     — `<!-- mutate:entity=..;field=..;value=..;id=ID -->` (point marker)

`MarkerMixin` owns that machinery once; each concrete mixin declares only its
compiled pattern, which capture group holds the marker id, and how to render a
match into its own record / rewritten marker. It is composed onto `ProjectService`
transitively (each marker mixin subclasses it), so the shared helpers resolve the
project IO methods (`read_scene`, `_path_for_node_id`, `_write_scene_file`,
`_read_markdown_with_front_matter`, `_atomic_write`) via the full MRO.

The marker *grammar* is necessarily mirrored on the frontend
(`frontend/src/lib/utils/markdown.ts`: `markEmbedded*` parse regexes + turndown
serializers) — the ProseMirror round-trip and the on-disk format are two ends of
the same wire format, so that split is inherent, not accidental duplication. Keep
the regexes here and there in lockstep; there is no single cross-language source.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, TypeVar

from app.services.project.errors import ProjectServiceError

if TYPE_CHECKING:
    from app.models import Scene

_Record = TypeVar("_Record")


class MarkerMixin:
    def _scan_body_markers(
        self,
        body: str,
        pattern: re.Pattern[str],
        build: Callable[[re.Match[str], int], _Record],
    ) -> Iterator[_Record]:
        """Yield `build(match, line)` for every marker in `body`, in prose order,
        where `line` is the marker start's 1-based source line. The per-body scan
        both the embedded-todo and mutation indexes walk; each kind supplies
        `build` to turn a regex match into its own record type (`match.start()`
        is available on the match for kinds that also need a char offset)."""
        for match in pattern.finditer(body):
            yield build(match, body[: match.start()].count("\n") + 1)

    def _rewrite_single_marker(
        self,
        body: str,
        pattern: re.Pattern[str],
        id_group: int | str,
        marker_id: str,
        render: Callable[[re.Match[str]], str],
    ) -> tuple[str, bool]:
        """Rewrite exactly the marker whose `id_group` capture equals `marker_id`,
        replacing it with `render(match)`; every other marker is left
        byte-for-byte. Returns `(new_body, found)`. A `render` that returns the
        marker's unwrapped inner prose (or "") turns this into a delete. The
        single-marker rewrite/delete callback the embedded-todo and mutation
        mixins share."""
        found = False

        def replace(match: re.Match[str]) -> str:
            nonlocal found
            if match.group(id_group) != marker_id:
                return match.group(0)
            found = True
            return render(match)

        return pattern.sub(replace, body), found

    def _apply_scene_marker_edit(
        self,
        scene_id: str,
        kind_label: str,
        marker_id: str,
        rewrite: Callable[[str], tuple[str, bool]],
    ) -> Scene:
        """Apply a single-marker `rewrite(body) -> (new_body, found)` to a scene
        and persist it, without a full body save. Raises 404 (`{kind_label}
        {marker_id} does not exist ...`) when the marker is absent; otherwise
        writes the scene and returns the re-read `Scene` so an open editor pane
        can reconcile. Shared by the `update_`/`delete_` methods across the
        embedded-todo and mutation mixins."""
        scene = self.read_scene(scene_id)
        new_body, found = rewrite(scene.body)
        if not found:
            raise ProjectServiceError(
                f"{kind_label} {marker_id} does not exist in scene {scene.id}.", 404
            )
        path = self._path_for_node_id(scene.id, "scene")
        self._write_scene_file(path, scene.model_copy(update={"body": new_body}))
        return self.read_scene(scene.id)

    def _apply_scene_marker_repair(
        self,
        scene_id: str,
        pattern: re.Pattern[str],
        replace: Callable[[re.Match[str]], str],
    ) -> None:
        """Run `pattern.sub(replace, body)` over a scene body and persist it
        front-matter-aware, only when it changed. Unlike `_apply_scene_marker_edit`
        this tolerates front-matter-less scene files — orphan/duplicate anchor
        repair operates on raw markdown — and returns nothing. Used by the
        todo-anchor repair paths, where `replace` matches against a whole
        capture set rather than a single id."""
        try:
            path = self._path_for_node_id(scene_id, "scene")
        except ProjectServiceError:
            return
        front_matter, body = self._read_markdown_with_front_matter(path)
        repaired_body = pattern.sub(replace, body)
        if repaired_body == body:
            return
        if front_matter:
            scene = self.read_scene(scene_id)
            self._write_scene_file(path, scene.model_copy(update={"body": repaired_body}))
        else:
            self._atomic_write(path, repaired_body)
