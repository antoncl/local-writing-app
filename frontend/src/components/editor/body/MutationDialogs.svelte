<script lang="ts">
  // The two `/mutate` dialogs (#33, #56, #59, #69) + their open/submit state,
  // extracted from ProseBodyView (which keeps only the pill-click and slash
  // wiring via the exported open* methods, bound through `bind:this`).
  //
  // Authoring: create mode inserts ONE unit pill (client-minted ids) carrying
  // every selected field row at the cursor; edit mode rewrites/removes the
  // whole unit node in place. Close picker: inserts an interval-close pill.
  // Units round-trip to scene-body comments (single-line or multi-line
  // carrier) via the turndown rule on save.
  import MutationAuthoringForm from "./MutationAuthoringForm.svelte";
  import MutationCloseForm from "./MutationCloseForm.svelte";
  import {
    applyMutationUnitDraft,
    insertMutationClose,
    removeMutationNode,
    type MutationUnitDraft,
  } from "@/lib/editor-core/mutationNodes";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import type { Editor } from "@tiptap/core";
  import type { LoreEntrySummary, MetadataSchema } from "@/lib/types";

  let {
    getEditor,
    sceneId = "",
    isScene = false,
    loreEntries = [],
    schema = null,
    implicitContextMatcher = null,
  }: {
    /** The live TipTap editor, read at action time (it outlives re-renders). */
    getEditor: () => Editor | null;
    sceneId?: string;
    /** Only scene documents flush + resolve mutation baselines. */
    isScene?: boolean;
    loreEntries?: LoreEntrySummary[];
    schema: MetadataSchema | null;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
  } = $props();

  let authoringOpen = $state(false);
  let presetEntityId = $state("");
  let editInitial = $state<MutationUnitDraft | null>(null);
  let closeOpen = $state(false);
  let closePresetEntityId = $state("");

  // The list-edit baseline (#71) reads the saved mutation index, so the scene
  // is flushed before either dialog opens (the GH-#45 spine) — unsaved pills
  // would otherwise be invisible to the resolver.
  async function flushFirst() {
    if (isScene && sceneId) {
      try {
        await editorPanes.flushSceneIfDirty(sceneId);
      } catch {
        // A failed flush falls back to the last-saved baseline; authoring stays possible.
      }
    }
  }

  export async function openAuthoring(preset = "") {
    await flushFirst();
    editInitial = null;
    presetEntityId = preset;
    authoringOpen = true;
  }

  export async function openEdit(initial: MutationUnitDraft) {
    await flushFirst();
    presetEntityId = "";
    editInitial = initial;
    authoringOpen = true;
  }

  export function openClose(preset = "") {
    closePresetEntityId = preset;
    closeOpen = true;
  }

  function handleSubmit(draft: MutationUnitDraft) {
    authoringOpen = false;
    const editor = getEditor();
    if (editor) applyMutationUnitDraft(editor, draft);
  }

  function handleDelete(markerId: string) {
    authoringOpen = false;
    const editor = getEditor();
    if (editor) removeMutationNode(editor, markerId);
  }

  function handleClosePick(ref: string) {
    closeOpen = false;
    const editor = getEditor();
    if (editor) insertMutationClose(editor, ref);
  }
</script>

{#if authoringOpen}
  <MutationAuthoringForm
    {loreEntries}
    {schema}
    {implicitContextMatcher}
    initial={editInitial}
    {presetEntityId}
    {sceneId}
    onSubmit={handleSubmit}
    onDelete={handleDelete}
    onCancel={() => (authoringOpen = false)}
  />
{/if}

{#if closeOpen}
  <MutationCloseForm
    {loreEntries}
    {sceneId}
    presetEntityId={closePresetEntityId}
    onPick={handleClosePick}
    onCancel={() => (closeOpen = false)}
  />
{/if}
