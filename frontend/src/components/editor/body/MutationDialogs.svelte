<script lang="ts">
  // The two `/mutate` dialogs (#33, #56, #59, #69, ADR-0095 §6) + their
  // open/submit state, extracted from ProseBodyView (which keeps only the
  // pill-click and slash wiring via the exported open* methods, bound through
  // `bind:this`).
  //
  // Authoring: create mode creates the SET first (via the API), then inserts
  // its anchor at the cursor — a failed create inserts nothing. Edit mode
  // (opened on a pill click) saves the SET; the scene document is never
  // touched, and Delete removes only the anchor. Close picker: inserts an
  // interval-close pill.
  import MutationAuthoringForm from "./MutationAuthoringForm.svelte";
  import MutationCloseForm from "./MutationCloseForm.svelte";
  import { insertAnchor, insertMutationClose, removeMutationNode } from "@/lib/editor-core/mutationNodes";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import type { Editor } from "@tiptap/core";
  import type { LoreEntrySummary, MetadataSchema, MutationSetEntry } from "@/lib/types";

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
  // Edit mode (ADR-0095 §6): the full set fetched from the store/API, and the
  // anchor id of the pill that opened it (baseline exclude + Delete target).
  // `null` ⇒ create mode.
  let editInitial = $state<MutationSetEntry | null>(null);
  let editAnchorId = $state("");
  // The dialog's own insertion position (ADR-0089 §4): the scene-markdown
  // char offset the baseline resolves at. `null`/undefined = end of scene,
  // unchanged from before the reversal.
  let authoringPosition = $state<number | null | undefined>(undefined);
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

  export async function openAuthoring(preset = "", position?: number | null) {
    await flushFirst();
    editInitial = null;
    editAnchorId = "";
    presetEntityId = preset;
    authoringPosition = position;
    authoringOpen = true;
  }

  /** Opened from a pill click (ADR-0095 §6): `set` is the anchored set,
   *  `anchorId` this pill's own anchor, `position` the pill's own char
   *  offset — the baseline excludes THIS anchor, not the end of scene. */
  export async function openEdit(set: MutationSetEntry, anchorId: string, position?: number | null) {
    await flushFirst();
    presetEntityId = "";
    editInitial = set;
    editAnchorId = anchorId;
    authoringPosition = position;
    authoringOpen = true;
  }

  export function openClose(preset = "") {
    closePresetEntityId = preset;
    closeOpen = true;
  }

  // Create mode: the set now exists — insert its anchor at the cursor.
  function handleCreated(setId: string) {
    authoringOpen = false;
    const editor = getEditor();
    if (editor) insertAnchor(editor, setId);
  }

  // Edit mode: the set is already saved — the document never changes.
  function handleSaved() {
    authoringOpen = false;
  }

  // Edit mode Delete (ADR-0095 §7): removes the ANCHOR only — the set stays,
  // staged if this was its last anchor.
  function handleRemoveAnchor() {
    authoringOpen = false;
    const editor = getEditor();
    if (editor && editAnchorId) removeMutationNode(editor, editAnchorId);
  }

  function handleClosePick(ref: string, row?: string) {
    closeOpen = false;
    const editor = getEditor();
    if (editor) insertMutationClose(editor, ref, row);
  }
</script>

{#if authoringOpen}
  <MutationAuthoringForm
    {loreEntries}
    {schema}
    {implicitContextMatcher}
    initial={editInitial}
    anchorId={editAnchorId}
    {presetEntityId}
    {sceneId}
    position={authoringPosition}
    onCreated={handleCreated}
    onSaved={handleSaved}
    onRemoveAnchor={handleRemoveAnchor}
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
