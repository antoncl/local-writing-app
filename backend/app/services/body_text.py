"""Story text — a body with the app's persisted markers removed (#2427).

Every marker the app keeps in a body is an HTML comment: mutation anchors
(`<!-- mutate:… -->`), roleplay beats (`<!-- character:id=…;internal=… -->…
<!-- /character -->`), embedded todos, legacy todo anchors. Only the tags go; the
text between an open and close tag (a beat's visible words, a todo's anchored
text) stays. A body rendered for a model goes through here so no marker — and no
roleplay beat's private interiority — reaches it. Dependency-free so any service
can import it without a cycle.
"""

from __future__ import annotations

import re
from typing import Any

HTML_COMMENT = re.compile(r"<!--[\s\S]*?-->")


def story_text(text: Any) -> str:
    """`text` with every HTML-comment marker removed; None → ""."""
    if text is None:
        return ""
    return HTML_COMMENT.sub("", str(text))
