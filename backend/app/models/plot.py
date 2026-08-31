"""Plot-template models (ADR-0048 S4b).

A `plot:template` is a diagnostic story-structure lens (three-act, mythic quest,
kishotenketsu, …) shipped by the built-in Library (ADR-0049) as a read-only
ancestor node, or an owned copy a writer cloned to adapt. The beat roster is the
`beats` ordered-list metadata field (S7 Slice 1, #736), not part of this spec;
the `template:` front-matter block modelled here carries the remaining
template-level attributes (family, guidance, provenance) so AI/context code can
resolve them without scraping the prose guide (the node body).

Ported from the `origin/plotting` quarry's `models_plot.py`, dropping its
legacy-shape acceptance (field aliases + before-validators): pre-1.0 stores only
the current shape, so there is nothing old to read (`feedback_no_pre_1_0_migrations`).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PlotTemplateFamily = Literal[
    "act",
    "journey",
    "cycle",
    "genre",
    "puzzle",
    "relationship",
    "character_arc",
    "custom",
]
PlotTemplatePrescriptiveness = Literal["descriptive", "diagnostic", "prescriptive"]
PlotTemplateIPRisk = Literal["low", "medium", "high", "unknown"]
PlotTemplateBuiltinPolicy = Literal["seed", "seed_generic", "reference_only", "user_authored"]


class SourceRef(BaseModel):
    """Provenance for a template — where its structure guidance came from."""

    id: str = Field(min_length=1)
    title: str = ""
    url: str | None = None
    citation: str = ""
    note: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotTemplateSpec(BaseModel):
    """The structured payload of a `plot:template`, carried in the `template:`
    front-matter block — template-level attributes only. The beat roster moved to
    the `beats` ordered-list metadata field (S7 Slice 1, #736)."""

    model_config = ConfigDict(populate_by_name=True)

    version: int = 1
    slug: str = ""
    display_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    family: PlotTemplateFamily = "custom"
    description: str = ""
    genre: str = ""
    cultural_context: str = ""
    prescriptiveness: PlotTemplatePrescriptiveness = "diagnostic"
    ai_use_guidance: str = ""
    global_diagnostic_questions: list[str] = Field(default_factory=list)
    # The structure's characteristic failure modes (its `## Common Weak Spots`),
    # fed to the diagnostic as things to check the draft against (ADR-0048 S7 item 7,
    # #948). The distilled, AI-facing counterpart to the body's prose weak-spots
    # section; snapshotted onto a plotline at instantiate like the guidance above.
    common_weak_spots: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    ip_risk: PlotTemplateIPRisk = "unknown"
    builtin_policy: PlotTemplateBuiltinPolicy = "user_authored"
    template_version: str = ""
    locale: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotTemplateSummary(BaseModel):
    """A template as it appears in a list — the full spec (templates are small)
    plus the Library provenance the picker needs to show read-only/clone state."""

    id: str
    title: str
    body: str = ""
    entry_type: str = "plot:template"
    template: PlotTemplateSpec = Field(default_factory=PlotTemplateSpec)
    # The size of the template's beat roster — what the palette shows as "7 beats"
    # so the writer can size a structure before instantiating it. The roster itself
    # (the `beats` metadata list) is not carried on the summary; only its count is.
    beat_count: int = 0
    source_layer_id: str = ""
    source_layer_label: str = ""
    is_library: bool = False
    editable: bool = False


class PlotTemplate(BaseModel):
    """A single template read model. `editable` is the fail-closed truth the
    UI's read-only lock reads (ADR-0049 #689): False unless this project owns the
    node. `is_library` governs banner wording only, orthogonal to editability."""

    id: str
    title: str
    body: str = ""
    revision: str = ""
    entry_type: str = "plot:template"
    template: PlotTemplateSpec = Field(default_factory=PlotTemplateSpec)
    # Schema-typed metadata, healed on read like every other node kind (#345):
    # `plot:template` carries no built-in fields today, but the schema editor can
    # add one to it, so the read path strips retired fields + dangling references
    # and validates rather than dropping author metadata silently (S4c finding #5).
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Read-only computed/mutable-field projection, same as every editable read
    # model the NodeEditor renders (empty until a computed field is defined here).
    computed_metadata: dict[str, Any] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""
    is_library: bool = False
    editable: bool = False


class PlotTemplateList(BaseModel):
    entries: list[PlotTemplateSummary] = Field(default_factory=list)


class SavePlotTemplateRequest(BaseModel):
    """Edit an owned template clone. Inherited (Library / ancestor) templates are
    read-only in place and 409 on save — clone one to adapt it."""

    title: str
    body: str = ""
    template: PlotTemplateSpec = Field(default_factory=PlotTemplateSpec)
    # Schema-typed metadata round-trips like every other editable node (S4c
    # finding #1): the read path heals + returns it, so the write path must
    # persist it, or a schema-editor-added field would be wiped on the first save.
    metadata: dict[str, Any] = Field(default_factory=dict)
    base_revision: str = ""


class CreatePlotTemplateRequest(BaseModel):
    """Blank-create an owned `plot:template` (the non-fork path, #918). Title is
    optional — a blank one gets a sensible default the writer then renames."""

    title: str = ""
