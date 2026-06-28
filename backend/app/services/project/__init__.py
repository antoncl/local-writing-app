"""Per-kind slices of the ProjectService god-class (#14 backend split).

`project_service.py` grew past 5000 LOC as a single class. Rather than a
big-bang rewrite, each cohesive slice (chats, scenes, lore, …) moves into
a mixin module here, one slice per commit. `ProjectService` composes the
mixins; the public import path `app.services.project_service.ProjectService`
stays stable.

Mixins reference shared helpers (`self._read_yaml`, `self._require_project`,
…) that still live on the core class — Python's MRO resolves them at call
time regardless of which class they're physically defined in, so method
bodies move verbatim. Shared, import-cycle-prone pieces (the
`ProjectServiceError` exception) live in their own modules here so both the
mixins and the core can import them without a cycle.
"""
