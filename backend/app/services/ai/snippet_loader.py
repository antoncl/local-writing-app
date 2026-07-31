"""Jinja loader that resolves `{% include %}` names to prompt snippets.

Prompts can factor shared boilerplate into `prompt:snippet` entries and pull
them in with `{% include "<name-or-id>" %}`. This loader is what makes that
work: the render env built by `create_environment_for_project()` gets one
installed as `env.loader`, so an include name is resolved against the project's
prompt entries rather than the filesystem.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jinja2 import BaseLoader, TemplateNotFound

if TYPE_CHECKING:
    from app.services.project_service import ProjectService


class PromptSnippetLoader(BaseLoader):
    """Resolve Jinja `{% include %}` names against prompt snippet entries."""

    def __init__(self, project: ProjectService) -> None:
        self.project = project

    def get_source(self, environment: Any, template: str) -> tuple[str, str | None, Any]:
        del environment
        entry = self._resolve_snippet(template)
        if entry is None:
            raise TemplateNotFound(template)
        return entry.body, entry.id, lambda: False

    def _resolve_snippet(self, raw_name: str) -> Any | None:
        """Find the `prompt:snippet` entry an include name refers to, or None.

        None means "no such snippet" (→ TemplateNotFound); read/schema errors
        are left to propagate so a genuinely-present-but-unreadable snippet
        surfaces the real failure instead of a misleading "not found".
        """
        name = raw_name.strip()
        stem = name[:-3] if name.lower().endswith(".md") else name
        schema = self.project.read_metadata_schema()
        entries = self.project.list_prompt_entries().entries

        # `entry_type_ancestry` is the shared "is X a kind-of Y" primitive
        # (ADR-0026) — reuse it rather than re-walking the parent chain here.
        snippets = [
            entry
            for entry in entries
            if "prompt:snippet"
            in self.project.entry_type_ancestry(entry.entry_type, schema=schema)
        ]
        for entry in snippets:
            if entry.id in (name, stem):
                return self.project.read_prompt_entry(entry.id)

        title_matches = [entry for entry in snippets if entry.title in {name, stem}]
        if len(title_matches) != 1:
            return None
        return self.project.read_prompt_entry(title_matches[0].id)
