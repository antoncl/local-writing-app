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
        name = raw_name.strip()
        stem = name[:-3] if name.lower().endswith(".md") else name
        try:
            schema = self.project.read_metadata_schema()
            entries = self.project.list_prompt_entries().entries
        except Exception:
            return None

        snippets = [
            entry
            for entry in entries
            if _entry_type_descends_from(schema, entry.entry_type, "prompt:snippet")
        ]
        for entry in snippets:
            if entry.id == name or entry.id == stem:
                try:
                    return self.project.read_prompt_entry(entry.id)
                except Exception:
                    return None

        title_matches = [entry for entry in snippets if entry.title in {name, stem}]
        if len(title_matches) != 1:
            return None
        try:
            return self.project.read_prompt_entry(title_matches[0].id)
        except Exception:
            return None


def _entry_type_descends_from(schema: Any, entry_type: Any, ancestor: str) -> bool:
    cursor = str(entry_type or "")
    seen: set[str] = set()
    while cursor and cursor not in seen:
        if cursor == ancestor:
            return True
        seen.add(cursor)
        definition = getattr(schema, "entry_types", {}).get(cursor)
        parent = getattr(definition, "parent", "") if definition is not None else ""
        cursor = parent if isinstance(parent, str) else ""
    return False
