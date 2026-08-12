# The commit-side of a brainstorm chat (ADR-0051 S4): a **fresh, self-instructed
# extraction** that replaces the old finalize-replay.
#
# The old commit re-shipped the frozen seed system prompt (which carried the JSON
# format contract) plus the whole transcript plus a terse "finalize" cue — so the
# contract sat far up a growing context and got less reliable the longer the chat
# ran (ADR §4). Here the contract is rebuilt from the schema every time and run as
# its own pass: the transcript is pure input, the format lives at the top of a
# small fresh context. Length-independent by construction.
#
# The contract is a Jinja template rendered through the ordinary preview pipeline,
# so it reuses `field_catalog` and the entry helpers rather than re-deriving the
# field descriptors in Python (the seed templates' item-shape logic is non-trivial
# — one source of it, not two). `DEFAULT_EXTRACTION_TEMPLATE` is the generated
# contract for the common case (body + all proposable fields); a prompt that needs
# a narrower shape supplies its own via `output.extract` (e.g. the scene-summary
# prompt, fields-only) and it is rendered here verbatim in its place.
from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.ai.preview import build_chat_payload, build_preview

if TYPE_CHECKING:
    from app.services.project_service import ProjectService

# The user turn that triggers the extraction. The format contract is the system
# prompt (rendered below); this only says "do it now". Mirrors the intent of the
# old FINALIZE_INSTRUCTION, but the contract no longer rides the seed prompt.
EXTRACT_CUE = (
    "Extract the final result of the conversation above now, exactly as the "
    "instructions describe — reply with ONLY the JSON, no preamble, no commentary, "
    "no code fences."
)

# The default generated contract (ADR-0051 S4). Body + every proposable field of
# the target type, straight from `field_catalog` — correct for the revise-entry
# and revise-plot-card prompts, which no longer carry the contract themselves. The
# field-descriptor / item-shape rendering is intentionally identical to the seed
# templates it replaces, so a `list`/`select` field is described the same way it
# always was. `input.entry_type` is the target FQN; `input.creating` distinguishes
# a from-scratch draft (title required) from a revise (title optional).
DEFAULT_EXTRACTION_TEMPLATE = """{% role "system" %}
You are extracting the final result of the brainstorm above into a structured patch. The conversation is your only input — read it and produce the result the author and you converged on.

Reply with ONLY a JSON object, with no preamble, no commentary, and no code fences, of exactly this shape:

{"body": "<the complete revised markdown body>", "fields": {"<field id>": <value>}}

- "body": the complete revised markdown body{% if input.creating %} for the new entry{% endif %}.
- "fields": {% if input.creating %}ALWAYS include "title". Add any other field the conversation set, {% else %}include a field ONLY when the conversation changed it, {% endif %}keyed by its field id. For tags / multi_select give a JSON array of strings; for a select field use one of its listed options exactly; for an ordered-list field give the complete new list in its stated item shape (the whole list, in order).{% if not input.creating %} You may also propose a new "title". Use {} if nothing changed.{% endif %}

The fields you may set:
{% for f in field_catalog(input.entry_type) %}
- {{ f.id }} ({{ f.label }}) — {{ f.type }}{% if f.options %}; one of: {{ f.options | join(", ") }}{% endif %}{% if f.get("items") %}{% if f.item_scalar %}; a JSON array of {{ f["items"][0].type }} values{% if f["items"][0].options %}, each one of: {{ f["items"][0].options | join(", ") }}{% endif %}{% else %}; a JSON array of objects, each with keys: {% for m in f["items"] %}{{ m.key }} ({{ m.type }}{% if m.options %}; one of: {{ m.options | join(", ") }}{% endif %}){% if not loop.last %}, {% endif %}{% endfor %}{% endif %}{% endif %}
{% else %}
- (none beyond title/body)
{% endfor %}

Output only that JSON object. It is parsed, validated against the entry's schema, and reviewed against the current entry before anything is saved.
{% endrole %}"""


def render_extraction_contract(
    project_service: ProjectService,
    *,
    entry_type: str,
    creating: bool,
    override_template: str | None = None,
) -> str:
    """Render the extraction contract (the system prompt) for ``entry_type``.

    Uses the prompt's ``output.extract`` override verbatim when supplied, else the
    default generated contract. Rendered through `build_preview` so `field_catalog`
    and the entry helpers are available exactly as in the seed templates; the
    system block is the contract. Raises `PreviewError` on a broken template (the
    route surfaces it).
    """

    template_source = override_template if override_template else DEFAULT_EXTRACTION_TEMPLATE
    rendered, _ = build_preview(
        project_service=project_service,
        template_source=template_source,
        target_scene_id="",
        session_id=None,
        inputs={"entry_type": entry_type, "creating": creating},
        text_before="",
        text_after="",
        commit=False,
    )
    system_prompt, _ = build_chat_payload(rendered)
    return system_prompt
