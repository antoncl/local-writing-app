<script lang="ts">
  // The body of an editor-document tab: the ancestor/clone banner, the
  // written-card banner, and the NodeEditor itself. Split out of App.svelte
  // (#2528); it reads the shared stores directly, exactly as App does, and takes
  // only the App-local action (`run`) and the schema-pane entry point as props.
  import NodeEditor from "@/components/editor/NodeEditor.svelte";
  import { findNodeBySceneId, flattenStructureScenes } from "@/lib/utils/treeHelpers";
  import { isInherited, readOnlyInPlace } from "@/lib/utils/provenance";
  import type { EditorPaneState } from "@/lib/editor-core/editorPaneModel";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
  import { roleplayPresence } from "@/lib/stores/roleplayPresence.svelte";
  import { chatSessions } from "@/lib/stores/chatSessions.svelte";
  import { embeddedTodosStore } from "@/lib/stores/todos";
  import { structureStore, researchStructureStore } from "@/lib/stores/structure";
  import { loreEntriesStore } from "@/lib/stores/lore";
  import { promptEntriesStore } from "@/lib/stores/prompts";
  import { assistantEntriesStore, defaultAssistantIdStore } from "@/lib/stores/assistants";
  import { metadataSchemaStore, projectLayerIdStore } from "@/lib/stores/schema";
  import { implicitContextMatcherStore } from "@/lib/stores/derived";
  import type { DocumentKind, NavigateTarget, Scene } from "@/lib/types";

  let {
    id,
    run,
    onCustomData,
  }: {
    id: string;
    run: (action: () => Promise<void>) => Promise<boolean>;
    onCustomData: (entryType: string, kind: DocumentKind, paneId: string) => void;
  } = $props();

  const editorPane = $derived(editorPanes.panes.find((pane) => pane.id === id));
  const structure = $derived($structureStore);
  const metadataSchema = $derived($metadataSchemaStore);
  const embeddedTodos = $derived($embeddedTodosStore);

  function paneEntryFromAncestor(pane: EditorPaneState): boolean {
    // For an ADR-0049 Library tenant (a prompt, or a plot template — ADR-0048
    // S4c) the banner's "inherited / read-only here" is the backend's own
    // `editable` verdict, read through the SAME helper as NodeEditor's read-only
    // lock (#689) — so the banner and the lock cannot disagree. This also drops
    // the tenant path's dependence on the async schema store: the flag rides on
    // the document, so the banner no longer lags the lock during schema load (the
    // #676 review's concern, now removed rather than worked around).
    if (pane.document?.type === "prompt" || pane.document?.type === "plot_template") {
      return readOnlyInPlace(pane.scene);
    }
    // Lore and other inheritable kinds keep the display-only provenance read
    // (#313), shared with the level pill and rail treatment. Reads the store
    // REACTIVELY so the banner re-renders when the schema layers finish loading;
    // fails open in the gap, which is fine for a non-gating affordance.
    return isInherited({ source_layer_id: pane.scene?.source_layer_id }, $projectLayerIdStore);
  }

  function sceneEntryHasBody(scene: Scene): boolean {
    const entryDefinition = metadataSchema?.entry_types[scene.entry_type];
    return entryDefinition?.has_body ?? true;
  }

  // Every kind the reference index can produce, not lore-else-scene (#344).
  // The dispatch lives on the controller with the openers it chooses between;
  // `run` puts an unopenable kind's message in the error banner.
  function navigateToBacklink(target: NavigateTarget) {
    void run(() => editorPanes.openNodeOfKind(target.id, target.kind, target.entryType));
  }

  function embeddedHintForScene(sceneId: string): string {
    const items = embeddedTodos.filter((item) => item.scene_id === sceneId);
    if (items.length === 0) return "";
    const open = items.filter((item) => item.status === "open").length;
    const done = items.length - open;
    return `${open} open embedded TODO${open === 1 ? "" : "s"} · ${done} completed.`;
  }
</script>

{#if editorPane}
  {#if paneEntryFromAncestor(editorPane)}
    <!-- ADR-0049 Library tenants (a prompt, or a plot template — ADR-0048 S4c)
         share the read-only-in-place banner and the clone-to-a-new-id gesture;
         only the noun and the fork method differ. Lore is the odd one out (an
         in-place fork that keeps the id). -->
    {@const paneKind = editorPane.document?.type}
    {@const isPlotTemplate = paneKind === "plot_template"}
    {@const isLibraryTenant = paneKind === "prompt" || isPlotTemplate}
    {@const tenantNoun = isPlotTemplate ? "template" : "prompt"}
    {@const isShipped =
      isLibraryTenant && !!(editorPane.scene as { is_library?: boolean } | undefined)?.is_library}
    <div
      class="ancestor-banner"
      title={isLibraryTenant
        ? isShipped
          ? `This ${tenantNoun} ships with the app and is read-only here. Clone it for an editable copy in this project.`
          : `This ${tenantNoun} is inherited from an ancestor project and is read-only here. Clone it for an editable copy in this project.`
        : "This entry lives in an ancestor project. Edits write back to the original file."}
    >
      <span>{isShipped ? "Shipped with the app" : `from ${editorPane.scene?.source_layer_label ?? "ancestor"}`}</span>
      {#if paneKind === "lore" && editorPane.scene}
        <button
          class="fork-button"
          type="button"
          title="Fork into an editable copy in this project — keeps the id, stops inheriting"
          aria-label="Fork into this project"
          onclick={() => run(() => editorPanes.forkLore(editorPane.scene!.id))}
        >
          <span aria-hidden="true">⧉</span> Fork here
        </button>
      {:else if isLibraryTenant && editorPane.scene}
        <!-- Any inherited Library tenant (Library or an ancestor project, #676)
             clones to a new local id — the "duplicate the default" gesture,
             not lore's in-place fork. -->
        <button
          class="fork-button"
          type="button"
          title={`Clone this inherited ${tenantNoun} into an editable copy in this project`}
          aria-label="Clone into this project"
          onclick={() =>
            run(() =>
              isPlotTemplate
                ? editorPanes.forkPlotTemplate(editorPane.scene!.id)
                : editorPanes.forkPrompt(editorPane.scene!.id),
            )}
        >
          <span aria-hidden="true">⧉</span> Clone to edit
        </button>
      {/if}
    </div>
  {/if}
  {#if editorPane.document?.type === "plot_card"}
    <!-- ADR-0097 §3: a written card shows its scene's text; its own title + body are
         frozen in the editor. Say so, and offer the scene. -->
    {@const writtenSceneId = editorPane.scene?.metadata?.scene}
    {#if typeof writtenSceneId === "string" && writtenSceneId}
      {@const writtenTitle = (structure && findNodeBySceneId(structure.root, writtenSceneId)?.title) || "Untitled"}
      <div class="ancestor-banner">
        <span>Written as “{writtenTitle}”. The board shows the scene's summary; this is the card's synopsis from before.</span>
        <button
          class="fork-button"
          type="button"
          aria-label="Open scene"
          onclick={() => run(() => editorPanes.openScene(writtenSceneId))}
        >
          Open scene
        </button>
      </div>
    {/if}
  {/if}
  <!-- Key the bind:this off the stable prop `id`, NOT `editorPane.id`:
       Svelte re-evaluates a bind:this target on teardown, and `editorPane`
       (= the pane looked up by id) is already undefined once the pane is closed —
       dereferencing `.id` there threw and aborted the whole effect flush, so
       the layout reconcile never ran and dead editor tabs were left as
       "Editor" ghosts (#806). `id` always equals editorPane.id. -->
  <NodeEditor
    bind:this={editorPanes.editorPaneComponents[id]}
    scene={editorPane.scene}
    documentKind={editorPane.document?.type ?? "manuscript"}
    promptEntries={$promptEntriesStore}
    structure={structure}
    researchStructure={$researchStructureStore}
    loreEntries={$loreEntriesStore}
    implicitContextMatcher={$implicitContextMatcherStore}
    assistantEntries={$assistantEntriesStore}
    defaultAssistantId={$defaultAssistantIdStore}
    availableScenes={flattenStructureScenes(structure?.root)}
    metadataReload={editorPanes.metadataReloadsByPane[editorPane.id] ?? null}
    titleReload={editorPanes.titleReloadsByPane[editorPane.id] ?? null}
    dirty={editorPane.dirty}
    recentlySaved={editorPane.recentlySaved}
    authoringLayerId={editorPane.authoringLayerId}
    hostPaneId={editorPane.id}
    todoStatusHint={editorPane.document?.type === "manuscript" && editorPane.scene && sceneEntryHasBody(editorPane.scene as Scene) ? embeddedHintForScene(editorPane.scene.id) : ""}
    onFocus={() => workspaceLayout.focus(editorPane.id)}
    onChange={(detail) =>
      editorPanes.updateEditorPaneDraft(
        editorPane.id,
        detail.title,
        detail.body,
        detail.status,
        detail.entryType,
        detail.metadata,
        detail.inputs,
        detail.offer_on,
        detail.context_strategy,
      )}
    onCustomData={(detail) => onCustomData(detail.entryType, detail.kind, editorPane.id)}
    onNavigate={navigateToBacklink}
    onOpenChat={(detail) => chatSessions.openChatFromPromptEntry(detail.entry, detail.inputs, detail.sceneId, { assistantId: detail.assistantId })}
    onViewSaveState={(state) => editorPanes.setViewSaveState(editorPane.id, state)}
    onAuthoringLayerChange={(layerId) => void editorPanes.setEditorPaneAuthoringLayer(editorPane.id, layerId)}
    onResetField={(fieldId) => editorPane.scene && run(() => editorPanes.resetOverrideField(editorPane.scene!.id, fieldId))}
    onFlushScene={async () => {
      // A capture photographs the file and a restore overwrites it, so both
      // must run against a file that already holds the author's latest
      // words — autosave is a 6-second idle debounce behind (#401). Kind-
      // agnostic: the snapshot strip is on lore too now (ADR-0088 S1), and a
      // manuscript-only flush would photograph a dirty lore card stale.
      if (editorPane.scene) await editorPanes.flushOpenPaneIfDirty(editorPane.scene.id);
    }}
    onSceneRestored={(restored) => editorPanes.reconcileSceneFromServer(restored)}
    onNodeRestored={(nodeId) => editorPanes.reconcileNodeFromServer(nodeId, "lore")}
    onInteriorityChange={(has) => roleplayPresence.set(editorPane.id, has)}
    onReviewFreeze={(entryId, committer) =>
      committer
        ? void editorPanes.beginReviewLock(entryId, committer)
        : editorPanes.endReviewLock(entryId)}
    onFlushReviewCommit={(entryId) => editorPanes.flushReviewCommit(entryId)}
  />
{/if}

<style>
  /* Ancestor-entry documents: a slim banner above the editor (edits still write
     back to the ancestor file). Replaces the old header tint + badge. */
  .ancestor-banner {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    padding: var(--sp-1) var(--sp-3);
    background: var(--star-soft);
    border-bottom: 1px solid var(--star-border);
    color: var(--text-2);
    font-size: var(--fs-xs);
  }

  .ancestor-banner .fork-button {
    flex: 0 0 auto;
    padding: 2px var(--sp-2);
    border: 1px solid var(--star-border);
    border-radius: 999px;
    background: transparent;
    color: var(--star);
    font-size: var(--fs-xs);
    cursor: pointer;
  }

  .ancestor-banner .fork-button:hover {
    background: color-mix(in oklab, var(--star) 16%, transparent);
  }
</style>
