"""Jinja loader that resolves `{% include %}` names to prompt snippets.

Prompts can factor shared boilerplate into `prompt:snippet` entries and pull
them in with `{% include "<name-or-id>" %}`. This loader is what makes that
work: the render env built by `create_environment_for_project()` gets one
installed as `env.loader`, so an include name is resolved against the project's
prompt entries rather than the filesystem.

The include name is normally the snippet's **title** (the name shown in the UI);
an id still resolves too, but the shipped prompts reference titles so the
template reads as what the author sees. Resolution is layer-aware — a project's
own snippet shadows an inherited or built-in one of the same title — so overriding
a built-in snippet is just "make one with the same title" (#1716 / #1717).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

from jinja2 import BaseLoader, TemplateNotFound

if TYPE_CHECKING:
    from app.services.project_service import ProjectService

_T = TypeVar("_T")

SnippetMatchStatus = Literal["resolved", "not_found", "ambiguous"]


@dataclass(frozen=True)
class SnippetMatch(Generic[_T]):
    """Outcome of resolving an `{% include %}` name.

    `entry` is set only when `status == "resolved"`. `colliding` carries the
    same-layer title clashes for the `"ambiguous"` case, so a diagnostic can name
    them.
    """

    status: SnippetMatchStatus
    entry: _T | None = None
    colliding: tuple[_T, ...] = ()


def resolve_snippet_name(
    raw_name: str,
    snippets: Sequence[_T],
    *,
    id_of: Callable[[_T], str],
    title_of: Callable[[_T], str],
    layer_rank_of: Callable[[_T], int] = lambda _entry: 0,
) -> SnippetMatch[_T]:
    """Resolve an `{% include %}` name against already-filtered snippet
    candidates.

    An exact **id** match wins first — an id is unique, so it is unambiguous.
    Failing that, a **title** match resolves by **layer precedence**: among
    candidates carrying the name as their title, the one in the nearest layer
    (highest `layer_rank_of`) wins, so a project's own snippet shadows an
    inherited or built-in one of the same title — exactly as an id override
    would. Only a tie at that nearest rank — two snippets sharing a title *within
    one layer* — is `"ambiguous"`; that is a genuine authoring collision, like a
    duplicate symbol in a program, and resolves to nothing. A trailing `.md` is
    stripped so `{% include "voice.md" %}` and `{% include "voice" %}` resolve
    alike.

    `layer_rank_of` defaults to a constant, which collapses to the pre-layer
    behaviour ("a unique title or nothing"): every candidate then shares a rank,
    so any title with more than one match is ambiguous. A flat in-memory registry
    (a unit test) can omit it; the render/gather/edge paths pass real ranks.

    Extracted so the render loader (below), the effective-inputs resolver
    (`effective_inputs.py`) and the include reference-graph (`references.py`)
    share one matching rule — if they disagreed on which snippet a name refers to,
    the form would ask for a different snippet's inputs than the one rendered, or
    the dependency edge would point at the wrong snippet: the exact drift ADR-0061
    removes.
    """
    name = raw_name.strip()
    stem = name[:-3] if name.lower().endswith(".md") else name
    for entry in snippets:
        if id_of(entry) in (name, stem):
            return SnippetMatch("resolved", entry)
    title_matches = [entry for entry in snippets if title_of(entry) in {name, stem}]
    if not title_matches:
        return SnippetMatch("not_found")
    nearest = max(layer_rank_of(entry) for entry in title_matches)
    top = [entry for entry in title_matches if layer_rank_of(entry) == nearest]
    if len(top) == 1:
        return SnippetMatch("resolved", top[0])
    return SnippetMatch("ambiguous", colliding=tuple(top))


def match_snippet_name(
    raw_name: str,
    snippets: Sequence[_T],
    *,
    id_of: Callable[[_T], str],
    title_of: Callable[[_T], str],
    layer_rank_of: Callable[[_T], int] = lambda _entry: 0,
) -> _T | None:
    """The resolved entry (or None), for callers that only need the snippet.

    A thin wrapper over `resolve_snippet_name` so the render/gather/edge paths and
    the unit tests keep a single matching implementation.
    """
    return resolve_snippet_name(
        raw_name, snippets, id_of=id_of, title_of=title_of, layer_rank_of=layer_rank_of
    ).entry


def _include_error_message(name: str, match: SnippetMatch[Any]) -> str:
    """A human message for an include that did not resolve to one snippet."""
    if match.status == "ambiguous":
        return (
            f'The include name "{name}" matches more than one snippet in the same '
            "project. Rename one so the name is unique."
        )
    return f'No snippet named "{name}" was found to include.'


class PromptSnippetLoader(BaseLoader):
    """Resolve Jinja `{% include %}` names against prompt snippet entries."""

    def __init__(self, project: ProjectService) -> None:
        self.project = project

    def get_source(self, environment: Any, template: str) -> tuple[str, str | None, Any]:
        del environment
        match = self._resolve_snippet(template)
        if match.entry is None:
            # Carry the reason (missing vs ambiguous) in the exception message so
            # the render call site can surface it verbatim (#1719); Jinja re-raises
            # a bare TemplateNotFound from `{% include %}` otherwise.
            raise TemplateNotFound(template, message=_include_error_message(template, match))
        return match.entry.body, match.entry.id, lambda: False

    def _resolve_snippet(self, raw_name: str) -> SnippetMatch[Any]:
        """Resolve an include name to a `prompt:snippet` entry.

        A `"not_found"`/`"ambiguous"` status (entry None) becomes TemplateNotFound
        in `get_source`; read/schema errors are left to propagate so a
        genuinely-present-but-unreadable snippet surfaces the real failure instead
        of a misleading "not found".
        """
        schema = self.project.read_metadata_schema()
        # `_build_prompt_summaries`, not `list_prompt_entries`: resolution only
        # needs id/title/entry_type/layer, and going through the public list would
        # run the effective-inputs pass (a parse of every prompt body) on every
        # include of every render for a field the render path never reads. Pass the
        # schema so the builder's disposition stamp (#1684) reuses this read.
        entries = self.project._build_prompt_summaries(schema)

        # `entry_type_ancestry` is the shared "is X a kind-of Y" primitive
        # (ADR-0026) — reuse it rather than re-walking the parent chain here.
        snippets = [
            entry
            for entry in entries
            if "prompt:snippet"
            in self.project.entry_type_ancestry(entry.entry_type, schema=schema)
        ]
        ranks = self.project._layer_rank_map()
        return resolve_snippet_name(
            raw_name,
            snippets,
            id_of=lambda entry: entry.id,
            title_of=lambda entry: entry.title,
            layer_rank_of=lambda entry: ranks.get(entry.source_layer_id, -1),
        )
