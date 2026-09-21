<script lang="ts">
  // The rail's metadata + backlinks + lore-mutation content (#2029 follow-up,
  // Conversations and Mutation sets moved out to body tabs in ADR-0089
  // Amendment 1 §4, #2101): moved VERBATIM out of NodeEditor's `metaContent`
  // snippet, which now just renders this component. Stays a component (not a
  // snippet itself) because it holds no shell state of its own — everything it
  // reads comes down through `{ model, deps, on }` (#2022's RailFieldRow
  // pattern), same as EditorBodyHost/EditorHeader. NodeEditor's `metaContent`
  // snippet still exists and still wraps this: EditorRail and the detached
  // Details pane both render THAT snippet (not this component directly), so a
  // detach/reattach never re-mounts this content — see NodeEditor's own
  // `metaContent` comment.
  import MetadataPanel from "@/components/editor/MetadataPanel.svelte";
  import MutationTimeline from "@/components/editor/MutationTimeline.svelte";
  import type { LoreScrubController } from "@/lib/stores/loreScrub.svelte";
  import type { SectionRegistry } from "@/lib/editor-core/sectionKeyboardBridge";
  import type { ResolvedCascadeField } from "@/lib/manuscriptTypes";
  import type {
    Backlink,
    BodyShape,
    DocumentKind,
    EditableDocument,
    EntryMetadata,
    EntryTypeDefinition,
    LoreEntrySummary,
    MetadataSchema,
    NavigateTarget,
    PromptEntrySummary,
  } from "@/lib/types";

  // Grouped per the RailFieldRow `{ model, deps, on }` pattern (#2022).
  interface RailContentModel {
    metadataSchema: MetadataSchema | null;
    entryType: string;
    status: string;
    metadata: EntryMetadata;
    documentKind: DocumentKind;
    documentLabel: string;
    documentEntryTypes: [string, EntryTypeDefinition][];
    metadataFieldIds: string[];
    scene: EditableDocument | null;
    createLayerId: string | null;
    overriddenFieldsForPanel: string[];
    scrubbed: boolean;
    scrub: LoreScrubController;
    compare: {
      fields: Record<string, { was: unknown; now: unknown }>;
      side: "now" | "was";
      resolve?: { adopted: (fieldId: string) => boolean; onToggle: (fieldId: string) => void };
    } | null;
    editorReadOnly: boolean;
    bodyShape: BodyShape;
    resolvedCascade: Record<string, ResolvedCascadeField> | null;
    backlinks: Backlink[];
    title: string;
    hostPaneId: string | null;
  }

  interface RailContentDeps {
    loreEntries: LoreEntrySummary[];
    promptEntries: PromptEntrySummary[];
    structure: import("@/lib/types").StructureDocument | null;
    researchStructure: import("@/lib/types").StructureDocument | null;
    implicitContextMatcher: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    sectionRegistry: SectionRegistry;
    computedFieldString: (fieldId: string) => string;
  }

  interface RailContentCallbacks {
    entryTypeChange: (next: string) => void;
    statusChange: (next: string) => void;
    metadataChange: (next: EntryMetadata) => void;
    customData: () => void;
    navigate: (target: NavigateTarget) => void;
    resetField: (fieldId: string) => void;
    goToSection: (fieldId: string) => void;
    // #2010: a list-index row's hit — switch the body tab strip to this
    // field's list tab. Owned by NodeEditor (which owns `activeBodyTab`).
    goToList: (fieldId: string) => void;
    // Engaging the mutation axis from the rail returns the snapshot axis to
    // Live (ADR-0088 S2) — see the MutationTimeline `onSelect` below.
    park: () => void;
  }

  interface Props {
    model: RailContentModel;
    deps: RailContentDeps;
    on: RailContentCallbacks;
    // #2054: which part of the content to render. `rail` is the whole rail
    // (the fact rows with the trailing sections inside, #2037). While the rail
    // is collapsed on a prose body the SAME content renders in the document
    // as two blocks: `facts` = the rows as front matter (MetadataPanel's
    // front-matter layout, no trailing), `trailing` = the appendix after the
    // body. Never both a rail and the blocks: one editor per value.
    part?: "rail" | "facts" | "trailing";
  }

  let { model, deps, on, part = "rail" }: Props = $props();
</script>

{#snippet trailing()}
  {#if model.documentKind === "lore" && model.scene?.id}
    <!-- The mutation SCRUBBER relocated to the foot dock (ADR-0088 S2 §5),
         where it shares one dock and a mode control with the snapshot track.
         The mutation TIMELINE stays here in the rail — a separate view of the
         same ordered dataset; the ADR moves only the beads scrubber. -->
    <MutationTimeline
      units={model.scrub.units}
      activeIndex={model.scrub.index}
      onSelect={(index) => {
        // Engaging the mutation axis from the rail returns the snapshot axis to
        // Live, so the two are never both engaged (ADR-0088 S2): the foot dock
        // follows the engaged axis, and this keeps them mutually exclusive even
        // though the rail drives scrub outside the dock.
        void on.park();
        void model.scrub.scrubTo(index);
      }}
      onNavigate={(payload) => on.navigate(payload)}
    />
  {/if}
{/snippet}

{#if part === "trailing"}
  <!-- The appendix (#2054): the rail's trailing sections after the body, in
       the rail's order. UI content inside the prose column, so the font is
       pinned back. -->
  <div class="rail-appendix" data-testid="rail-appendix">{@render trailing()}</div>
{:else if model.metadataSchema}
  <MetadataPanel
    layout={part === "facts" ? "front-matter" : "rail"}
    entryType={model.entryType}
    status={model.status}
    metadata={model.metadata}
    documentKind={model.documentKind}
    documentLabel={model.documentLabel}
    documentEntryTypes={model.documentEntryTypes}
    metadataFieldIds={model.metadataFieldIds}
    loreEntries={deps.loreEntries}
    promptEntries={deps.promptEntries}
    structure={deps.structure}
    researchStructure={deps.researchStructure}
    implicitContextMatcher={deps.implicitContextMatcher}
    excludeId={model.scene?.id ?? null}
    sourceLayerId={model.scene?.source_layer_id ?? null}
    sourceLayerLabel={model.scene?.source_layer_label ?? null}
    createLayerId={model.createLayerId}
    overriddenFields={model.overriddenFieldsForPanel}
    computedFieldString={deps.computedFieldString}
    effectiveOverrides={model.scrubbed ? model.scrub.overrides : null}
    compare={model.compare}
    readOnly={model.editorReadOnly}
    sectionsInBody={model.bodyShape === "prose"}
    onGoToSection={(fieldId) => on.goToSection(fieldId)}
    listsInBody={model.bodyShape !== "chat"}
    onGoToList={(fieldId) => on.goToList(fieldId)}
    onEntryTypeChange={(next) => on.entryTypeChange(next)}
    onStatusChange={(next) => on.statusChange(next)}
    onMetadataChange={(next) => on.metadataChange(next)}
    onCustomData={() => on.customData()}
    onNavigate={(payload) => on.navigate(payload)}
    onResetField={model.documentKind === "lore" || model.documentKind === "prompt" ? on.resetField : undefined}
    resolvedCascade={model.resolvedCascade}
    trailing={part === "rail" ? trailing : undefined}
  />
  <!-- #2037: in the rail the trailing sections render INSIDE MetadataPanel,
       between its known rows and the empty-field fold, so "N more fields" is
       the last entry in the rail rather than sitting above Backlinks. As
       front matter (#2054) the panel gets no trailing. -->
{/if}

<style>
  /* The panels size their own text with tokens; only the family needs pinning
     back from the prose column's serif. */
  .rail-appendix {
    font-family: var(--sans);
  }
</style>
