"""One safe YAML loader for the read path, C-accelerated when libyaml is there (#1847).

Front-matter parsing dominates every cold index and search-corpus build: on a
copy of the largest live project (62 nodes) ~90% of the corpus build was
`yaml.safe_load` — PyYAML's pure-Python scanner at ~5 ms per file. PyYAML ships
libyaml bindings in its wheels (`yaml.__with_libyaml__`), and `CSafeLoader`
produces the same objects as `SafeLoader` for everything the app writes, 5–10×
faster.

The choice lives here, once, and EVERY read in the backend goes through it —
not just the hot path. The two scanners disagree on a few hand-edit shapes
(libyaml accepts a stray tab after a value that the pure scanner rejects, and
rejects a `|` block whose first line starts with a tab that the pure scanner
accepts), so a file parsed by one engine in the index and by the other in a
migration would be a node the app shows but a migration skips. One engine means
one answer. `test_yaml_io.py` fails on any `yaml.safe_load(` reappearing under
`app/`.

Callers use `load_yaml` and keep catching `yaml.YAMLError` — the C loader
raises the same error family. A source build without libyaml (or a platform
PyYAML has no wheel for) falls back to the pure-Python `SafeLoader`, so the
loader is a speed-up, never a requirement.
"""

from __future__ import annotations

from typing import IO, Any

import yaml

SAFE_LOADER: type = yaml.CSafeLoader if yaml.__with_libyaml__ else yaml.SafeLoader


def load_yaml(stream: str | bytes | IO[str] | IO[bytes]) -> Any:
    """`yaml.safe_load`, through the fastest safe loader this interpreter has."""
    return yaml.load(stream, Loader=SAFE_LOADER)  # noqa: S506 - SAFE_LOADER is a safe loader
