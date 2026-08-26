"""The shared entry-type identity regex for the metadata schema.

Split out of `schema.py` (which sits at the file-size cap); used by both the
entry-type write path there and the definition validator
(`schema_definition_validation.py`)."""

from __future__ import annotations

import re

# Entry-type identity is the kind-qualified FQN `kind:key` (#77). The key may nest
# (`kind:seg:seg…`, e.g. `prompt:revise:scene`) — the extra colons are a pure naming
# separator with no tie to the `parent:` chain (#600). The kind is always the first
# segment (group 1); each segment starts with a letter, then letters/digits/underscores.
# Shared by the entry-type write path (`schema.py`) and the definition validator
# (`schema_definition_validation.py`).
ENTRY_TYPE_FQN_RE = re.compile(r"([a-z][a-z0-9_]*):([A-Za-z][A-Za-z0-9_]*(?::[A-Za-z][A-Za-z0-9_]*)*)")
