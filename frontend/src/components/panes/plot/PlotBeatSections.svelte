<!--
  PlotBeatSections (#2043 slice 3): the plot board's host for the repeating
  body sections (BodyListSection) of a plot:thread entry (a plotline or a
  character arc — CharacterArcEntry is the same shape), mounted inside a
  board node's expanded editor in place of the old bespoke beat editor
  (BeatDraft/toBeats/detailsOpen). Reads its collaborator stores directly
  (schema/lore/prompts/structure/tags) rather than taking them as props: the
  arc node already reads loreEntriesStore this way, and this component only
  mounts while a node is expanded, so it's one subscription set per open
  editor — not a standing cost of the board. Density is "compact" (#2043 §2):
  a board node is node-scale, not the NodeEditor's full prose column.
  `createLayerId` is null — a plot:thread entry is book-local, and NodeEditor
  computes null for a book-local document too (nothing to promote a newly
  created tag past).
-->
<script lang="ts">
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { loreEntriesStore } from "@/lib/stores/lore";
  import { promptEntriesStore } from "@/lib/stores/prompts";
  import { structureStore, researchStructureStore } from "@/lib/stores/structure";
  import { tagTitleById } from "@/lib/stores/tagNodes";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { buildBodyListSections, listItemEditorId } from "@/lib/editor-core/bodySections";
  import { createSectionRegistry } from "@/lib/editor-core/sectionKeyboardBridge";
  import { createSectionEditorRoster } from "@/lib/editor-core/sectionEditorRoster.svelte";
  import BodyListSection from "@/components/editor/body/BodyListSection.svelte";
  import type { EntryMetadata, MetadataValue, PlotlineEntry } from "@/lib/types";

  interface Props {
    entry: PlotlineEntry; // CharacterArcEntry is the same shape
    onChange: (metadata: EntryMetadata) => void;
  }

  let { entry, onChange }: Props = $props();

  const sections = $derived(buildBodyListSections($metadataSchemaStore, entry.entry_type));
  function items(listId: string): MetadataValue[] {
    const value = entry.metadata[listId];
    return Array.isArray(value) ? (value as MetadataValue[]) : [];
  }

  const register = createSectionRegistry();
  const orderedIds = $derived(
    sections.flatMap((list) =>
      items(list.id).flatMap((_, index) => list.proseMembers.map((member) => listItemEditorId(list.id, index, member.key))),
    ),
  );
  const roster = createSectionEditorRoster(register, () => orderedIds);
</script>

<div class="plot-beat-sections">
  {#each sections as section (section.id)}
    <BodyListSection
      model={{
        section,
        items: items(section.id),
        readOnly: false,
        schema: $metadataSchemaStore!,
        entryType: entry.entry_type,
        documentKind: "plotline",
        density: "compact",
      }}
      deps={{
        register,
        sectionIndex: roster.sectionIndex,
        implicitContextMatcher: null,
        loreEntries: $loreEntriesStore,
        promptEntries: $promptEntriesStore,
        structure: $structureStore,
        researchStructure: $researchStructureStore,
        excludeId: entry.id,
        createLayerId: null,
        tagTitleById: $tagTitleById,
      }}
      on={{
        change: (list) => onChange({ ...entry.metadata, [section.id]: list }),
        editorReady: roster.editorReady,
        navigate: (t) => void editorPanes.openNodeOfKind(t.id, t.kind, t.entryType),
      }}
    />
  {/each}
</div>

<style>
  .plot-beat-sections {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
</style>
