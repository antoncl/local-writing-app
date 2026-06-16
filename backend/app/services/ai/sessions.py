"""AI session tracking for cache-coherent envelope assembly.

A session remembers the `revision` (content hash) of every lore entry it pulled
into the envelope on previous calls, so the next call can partition the same
set into:

- **stable** — entries whose revision still matches the baseline
- **volatile** — entries that are new or changed since the baseline

The template author opts into the partition by calling
`relevant_lore(scene, partition="stable")`, emitting `{% cache_break %}`, then
calling `relevant_lore(scene, partition="volatile")`. The provider serializer
turns the cache_break into Anthropic `cache_control` markers, hitting the cache
on the stable prefix.

Lifecycle:

```python
session = registry.get_or_create("scene_xxxxx")
# ... helpers accumulate touched[id] = revision during render ...
session.commit()  # touched → baseline; next call compares against this
```

The first call has an empty baseline, so everything is volatile — but after
commit, the second call sees the same set as stable. The cache builds up
naturally over the session.

No expiry yet. Callers drop sessions explicitly via `registry.drop(session_id)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AISession:
    """Per-target session state. `id` is caller-supplied (typically a scene_id)."""

    id: str
    baseline: dict[str, str] = field(default_factory=dict)
    touched: dict[str, str] = field(default_factory=dict)

    def snapshot(self, entry_id: str, revision: str) -> None:
        """Record that an entry was pulled into the envelope this call."""
        self.touched[entry_id] = revision

    def is_stable(self, entry_id: str, revision: str) -> bool:
        """True if this entry's revision matches the baseline from the prior call."""
        return self.baseline.get(entry_id) == revision

    def commit(self) -> None:
        """Promote touched revisions to baseline. Clears touched for the next call."""
        self.baseline = dict(self.touched)
        self.touched = {}

    def reset(self) -> None:
        """Wipe both baseline and touched (e.g., on cache invalidation)."""
        self.baseline = {}
        self.touched = {}


class AISessionRegistry:
    """In-memory map of session_id → AISession. No expiry."""

    def __init__(self) -> None:
        self._sessions: dict[str, AISession] = {}

    def get_or_create(self, session_id: str) -> AISession:
        existing = self._sessions.get(session_id)
        if existing is None:
            existing = AISession(id=session_id)
            self._sessions[session_id] = existing
        return existing

    def get(self, session_id: str) -> AISession | None:
        return self._sessions.get(session_id)

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def clear(self) -> None:
        self._sessions.clear()


# Process-wide default registry. Tests can pass an isolated instance instead.
default_registry = AISessionRegistry()
