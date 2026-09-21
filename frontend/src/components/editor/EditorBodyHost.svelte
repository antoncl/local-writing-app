<script lang="ts">
  // The editor body region (#2029 split of NodeEditor): the five body-shape
  // branches (none / code / prose / chat / view), moved VERBATIM out of
  // NodeEditor, plus the seam functions NodeEditor used to call straight on
  // ProseBodyView/CodeBodyView/ChatBodyView/ViewBodyView via bind:this. Kept a
  // sibling of EditorHeader rather than a wrapper element: the
  // `.prose-body-host`/`.code-body-host { display: contents }` rules exist so
  // these body views stay DIRECT grid children of `.editor-panel` (a wrapper
  // here would break `grid-template-rows` and the rail column pinning in
  // NodeEditor's style block) — so this component renders at its own root,
  // with no wrapper element, exactly like NodeEditor did inline.
  //
  // NOT mount-tested: TipTap (ProseBodyView) is not mountable under happy-dom
  // (see reference_svelteflow_headless_limits-style traps for editor
  // components), so there is no EditorBodyHost.test.ts — the moved branches
  // are exercised indirectly through each body view's own tests plus the
  // pane-reconcile/save-failure tests that already fake NodeEditor's exported
  // handles (unchanged names/signatures, see NodeEditor's own seam forwards).
  import ReadOnlyBodyOverlay from "@/components/editor/body/ReadOnlyBodyOverlay.svelte";
  import EntryReviewOverlay from "@/components/editor/body/EntryReviewOverlay.svelte";
  import FieldsOnlyView from "@/components/editor/body/FieldsOnlyView.svelte";
  import CodeBodyView from "@/components/editor/body/CodeBodyView.svelte";
  import ProseBodyView from "@/components/editor/body/ProseBodyView.svelte";
  import BodySections from "@/components/editor/body/BodySections.svelte";
  import ChatBodyView from "@/components/editor/body/ChatBodyView.svelte";
  import ViewBodyView from "@/components/editor/body/ViewBodyView.svelte";
  import ReferenceListTab from "@/components/editor/body/ReferenceListTab.svelte";
  import type { SearchReveal } from "@/lib/editor-core/searchMatchHighlight";
  import type { SectionRegistry } from "@/lib/editor-core/sectionKeyboardBridge";
  import type { ViewSaveState } from "@/lib/editor-core/editorPaneModel";
  import { keyedListKeyMember, keyedShapeFor } from "@/lib/editor-core/keyedList";
  import { proseRendersAfterSections } from "@/lib/editor-core/bodySections";
  import { asItemList } from "@/lib/editor-core/mutationListEdit";
  import { rewriteUnitFromItems } from "@/lib/editor-core/mutationStopEdit";
  import type { MutationUnitGroup } from "@/lib/editor-core/mutationUnits";
  import { LoreScrubController } from "@/lib/stores/loreScrub.svelte";
  import { SnapshotStripController } from "@/lib/stores/snapshotStrip.svelte";
  import { EntryProposalController } from "@/lib/stores/entryProposal.svelte";
  import { PromptInputDraftsController } from "@/lib/stores/promptInputDrafts.svelte";
  import { tagTitleById } from "@/lib/stores/tagNodes";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { api } from "@/lib/api";
  import { effectiveFieldLabel } from "@/lib/utils/schemaTypeHelpers";
  import { fieldsInTab } from "@/lib/editor-core/bodyTabs";
  import type {
    AssistantEntrySummary,
    BodyShape,
    DocumentKind,
    EditableDocument,
    EntryBodyLanguage,
    EntryMetadata,
    LoreEntrySummary,
    MetadataSchema,
    MetadataValue,
    NavigateTarget,
    PromptContextStrategy,
    PromptEntrySummary,
  } from "@/lib/types";

  // Grouped per the RailFieldRow `{ model, deps, on }` pattern (#2022): `model`
  // is this pane's document-shaped state, `deps` are read-only collections and
  // shared collaborators, `on` are the outbound events.
  interface BodyHostModel {
    scene: EditableDocument | null;
    documentKind: DocumentKind;
    bodyShape: BodyShape;
    rawBodyLanguage: EntryBodyLanguage;
    loadedSceneId: string | null;
    entryType: string;
    metadata: EntryMetadata;
    metadataSchema: MetadataSchema | null;
    editorReadOnly: boolean;
    inheritedReadOnly: boolean;
    reviewing: boolean;
    scrubbed: boolean;
    snapshotParked: boolean;
    overlayBodyHtml: string;
    snapshotRibbon: string;
    scrub: LoreScrubController;
    // #2074 (ADR-0042 §5): the scrub stop's own unit — the stop IS the unit,
    // so editing the lore card at a stop edits this. `null` off the lore axis
    // or at base (stop 0, editable already).
    stopUnit: MutationUnitGroup | null;
    snapshots: SnapshotStripController;
    entryReview: EntryProposalController;
    detailsDetached: boolean;
    // Defined in NodeEditor (owns title/handleTitleInput state + the
    // `.title-*` CSS) and rendered here bare on ChatBodyView's title row and
    // inside the none-shape `metaContent` is NOT part of this — see below.
    chatTitleField: import("svelte").Snippet;
    // The rail/backlinks/conversations content, defined in NodeEditor. Only
    // the none-shape branch (the rail-is-pane case) renders it here.
    metaContent: import("svelte").Snippet;
    // #2054 front matter: the rail's facts / trailing material as document
    // blocks while the rail is collapsed on a prose body; absent with the rail
    // open (never both — one editor per value). Rendered INSIDE the prose
    // frame and the read-only overlay, never as siblings (the grid, #2030).
    frontMatter?: import("svelte").Snippet;
    appendix?: import("svelte").Snippet;
    // #2010: the body tab strip's current selection, owned by NodeEditor. A
    // `list:<fieldId>` value renders ReferenceListTab for that field, hiding
    // (never unmounting — TipTap state/undo must survive a tab switch) the
    // shape's own body view underneath.
    activeBodyTab: string;
    // #2043: forwarded to BodySections' list-section item rows — the same
    // layer a metadata-rail picker targets for `create_missing` (ADR-0082 §2).
    createLayerId: string | null;
  }

  interface BodyHostDeps {
    loreEntries: LoreEntrySummary[];
    promptEntries: PromptEntrySummary[];
    assistantEntries: AssistantEntrySummary[];
    availableScenes: { id: string; title: string }[];
    structure: import("@/lib/types").StructureDocument | null;
    researchStructure: import("@/lib/types").StructureDocument | null;
    implicitContextMatcher: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    defaultAssistantId: string;
    documentLabel: string;
    hostPaneId: string | null;
    sectionRegistry: SectionRegistry;
    promptDrafts: PromptInputDraftsController;
  }

  interface BodyHostCallbacks {
    change: () => void;
    focus: () => void;
    openChat: (payload: { entry: PromptEntrySummary; inputs: Record<string, unknown>; sceneId: string | null; assistantId: string }) => void;
    requestInputsDialog: (payload: {
      entry: PromptEntrySummary;
      prefilledDrafts?: Record<string, string>;
      unresolved?: Array<{ name: string; label: string; token: string }>;
    }) => void;
    metadataChange: (next: EntryMetadata) => void;
    viewSaveState: (state: ViewSaveState) => void;
    // #2010: a ReferenceListTab row's double-click / navigate intent.
    navigate: (target: NavigateTarget) => void;
  }

  interface Props {
    model: BodyHostModel;
    deps: BodyHostDeps;
    on: BodyHostCallbacks;
    rawBody?: string;
    offerOnDraft?: string[];
    contextStrategyDraft?: PromptContextStrategy | null;
    liveWordCount?: number;
    editorEmpty?: boolean;
    hasInteriorityBeats?: boolean;
    interiorityRevealed?: boolean;
    lastInvocationCostUsd?: number | null;
    sceneSessionCostUsd?: number;
    characterCostUsd?: Record<string, number>;
  }

  let {
    model,
    deps,
    on,
    rawBody = $bindable(""),
    offerOnDraft = $bindable([]),
    contextStrategyDraft = $bindable(null),
    liveWordCount = $bindable(0),
    editorEmpty = $bindable(true),
    hasInteriorityBeats = $bindable(false),
    interiorityRevealed = $bindable(false),
    lastInvocationCostUsd = $bindable(null),
    sceneSessionCostUsd = $bindable(0),
    characterCostUsd = $bindable({}),
  }: Props = $props();

  // #2010/#2100: the active tab's list field ids — plural since ADR-0089
  // Amendment 1's group-keyed tabs can merge several list fields into one
  // tab (`tabIdForField`, shared with `buildBodyTabs`) — or [] on the
  // "body"/"details" tab. Guarded against a non-string/absent `activeBodyTab`
  // (a test double, or a host mid-migration) rather than assuming the prop is
  // always well-formed.
  let activeListFieldIds = $derived(fieldsInTab(model.metadataSchema, model.entryType, model.activeBodyTab));
  // Kept for the simple "is a list tab open" boolean gates below (which body
  // view to hide) — any member of the active tab does, since every field in
  // one tab shows/hides together.
  let listFieldId = $derived(activeListFieldIds[0] ?? null);
  // #2072/ADR-0089 §1: a list field's items may be plain id strings (a
  // today's `entity_ref_list`) or member records (a reference-keyed list) —
  // pass them through as-is; stringifying an object here would turn a keyed
  // item into "[object Object]".
  function toItemList(v: unknown): MetadataValue[] {
    if (Array.isArray(v)) return v as MetadataValue[];
    if (typeof v === "string" && v) return [v];
    return [];
  }

  // #2074 (ADR-0042 §5): a list field is editable AT THIS SCRUB STOP when it's
  // a reference-keyed list AND the stop's own unit touches the open node — the
  // unit's own rows are exactly what the rewrite below replaces. Per-field
  // (#2100): a merged tab's fields aren't necessarily all keyed alike, so this
  // is a function of the field rather than a single tab-wide flag.
  function stopEditableFor(fieldId: string): boolean {
    return (
      model.scrubbed &&
      model.metadataSchema != null &&
      keyedListKeyMember(model.metadataSchema.fields[fieldId]) !== null &&
      (model.stopUnit?.records.some((r) => r.entity_id === (model.scene?.id ?? "")) ?? false)
    );
  }

  // Route a list-tab change through the scrub-stop rewrite when the field is
  // editable there; otherwise the ordinary whole-field metadataChange. On
  // failure, log and leave the tab as it was — the reload isn't called, so the
  // displayed effective items stay whatever they were before the edit.
  async function handleListChange(fieldId: string, items: MetadataValue[]): Promise<void> {
    if (stopEditableFor(fieldId) && model.stopUnit && model.metadataSchema) {
      try {
        await rewriteUnitFromItems({
          unit: model.stopUnit,
          entityId: model.scene?.id ?? "",
          field: fieldId,
          keyed: keyedShapeFor(model.metadataSchema.fields[fieldId]),
          baseItems: asItemList(model.metadata[fieldId]),
          editedItems: asItemList(items),
          deps: {
            getEntityEffectiveState: api.getEntityEffectiveState,
            rewriteMutationUnit: api.rewriteMutationUnit,
            flushSceneIfDirty: (sceneId) => editorPanes.flushSceneIfDirty(sceneId),
            reconcileSceneFromServer: (scene, mode) => editorPanes.reconcileSceneFromServer(scene, mode),
          },
        });
        await model.scrub.reload();
      } catch (err) {
        console.error(err);
      }
      return;
    }
    on.metadataChange({ ...model.metadata, [fieldId]: items });
  }

  let proseBodyView: ProseBodyView | null = $state(null);
  let codeBodyView: CodeBodyView | null = $state(null);
  let chatBodyView: ChatBodyView | null = $state(null);
  let viewBodyView: ViewBodyView | null = $state(null);

  // ADR-0089 Amendment 1 (#2099): whether the prose body renders after its
  // long_text sections (a scene's brief→draft order) instead of before them
  // (a lore/reference entry, unchanged) — derived from `body`'s position in
  // the resolved field order, never a hardcoded "if scene" branch.
  let proseAfterSections = $derived(proseRendersAfterSections(model.metadataSchema, model.entryType));

  // Effective intrinsics at the scrub point, needed by the prose branch's
  // "mutated" ribbon below. Title/body may be mutated too (ADR-0009
  // amendment) — scope is total, the whole card travels. (Moved verbatim from
  // NodeEditor; the title-side twin of this derivation — `titleMutated` /
  // `effectiveTitle` — stays in NodeEditor, which owns `chatTitleField`.)
  let bodyMutated = $derived(model.scrubbed && model.scrub.overrides != null && "body" in model.scrub.overrides);

  // ---------- Public methods (called via bind:this from NodeEditor) ----------
  // Editor-pane handle exports — forwarded to whichever body view the shape
  // mounts. reloadScene re-seeds the TipTap buffer from a server scene (a
  // reconcile after an out-of-band write, e.g. embedded-TODO/ADR-0085
  // replace); highlightEmbeddedTodo scrolls to a marker.
  // `undefined` when this shape mounts no prose view (chat / view / none):
  // the shell's callers fall back to the stored `scene.body` in that case
  // (snapshot capture, the scrub overlay, the review's current-body read) —
  // coalescing to "" here would silently capture an empty body for them.
  export function getBody(): string | undefined {
    return proseBodyView?.getBody();
  }

  export async function adoptBody(markdown: string): Promise<void> {
    await proseBodyView?.adoptBody(markdown);
  }

  export function loadScene(nextScene: EditableDocument, mode: "boundary" | "reconcile" = "boundary"): Promise<void> | undefined {
    return proseBodyView?.loadScene(nextScene, mode);
  }

  export function highlightEmbeddedTodo(todoId: string): void {
    proseBodyView?.highlightEmbeddedTodo(todoId);
  }

  // A search hit's reveal (#1925) goes to whichever body the shape mounts.
  export function revealSearchMatch(reveal: SearchReveal): void {
    if (model.bodyShape === "code") codeBodyView?.revealSearchMatch(reveal);
    else proseBodyView?.revealSearchMatch(reveal);
  }

  // Rung 2 of the reconcile ladder (ADR-0077): forward the prose three-way merge
  // to the body view. Absent body view (chat/view) → null, i.e. non-prose, so the
  // 409 handler falls to the dialog.
  export function tryMergeProse(baseBody: string, remoteBody: string): Promise<string | null> {
    return proseBodyView?.tryMergeProse?.(baseBody, remoteBody) ?? Promise.resolve(null);
  }

  // Shell toggle entry point: reveal-all / collapse-all (ADR-0070 S2). Called
  // from EditorHeader's interiority button via NodeEditor's `on.toggleInteriority`.
  export function toggleInteriority(): void {
    proseBodyView?.toggleInteriority();
  }

  // Called from NodeEditor.submitInputsDialog after the user fills inputs.
  export async function runPromptEntryWithInputsExternal(
    entry: PromptEntrySummary,
    inputs: Record<string, unknown>,
    assistantId: string = "",
  ): Promise<void> {
    await proseBodyView?.runPromptEntryWithInputsExternal(entry, inputs, assistantId);
  }

  // Title input handler's chat/view branch (NodeEditor's handleTitleInput calls
  // this after emitChange). For chats, feed the new title into ChatBodyView,
  // which owns the chat's title state and persists it (saveEditorPane is a
  // no-op for chats). The view designer's own title state mirrors it.
  export function setTitleFromPane(next: string): void {
    if (model.documentKind === "chat") chatBodyView?.setTitleFromPane(next);
    if (model.documentKind === "view") viewBodyView?.setTitleFromPane(next);
  }
</script>

{#if model.bodyShape === "none"}
  <!-- `!detailsDetached`: if the shape flips to none while Details is detached,
       the fold-back effect reattaches next tick — this gate keeps metaContent
       single-mounted through that one tick (not inline + detached pane, #1258).
       #2010: wrapped in a `display: contents` host so a list tab can HIDE it
       (never unmount — this content has its own live edit state) instead of
       replacing it; `.none-body-host` is the same pattern as `.prose-body-host`. -->
  {#if model.scene && model.metadataSchema && !model.detailsDetached}
    <div class="none-body-host" class:hidden={listFieldId !== null}>
      <div class="editor-pane-meta">
        {@render model.metaContent()}
      </div>
    </div>
  {:else if !model.scene || !model.metadataSchema}
    <FieldsOnlyView />
  {/if}
{/if}
{#if model.bodyShape === "code"}
  {#if model.entryReview.hasReview && model.entryReview.proposal}
    <!-- A commit brainstorm reviewed on a code-bodied node (a prompt template —
         #711). Same overlay as prose; the raw body stays mounted and hidden
         beneath (frozen diff base), thawing to the adopted text on commit. -->
    <EntryReviewOverlay review={model.entryReview} />
  {/if}
  <div class="code-body-host" class:hidden={model.reviewing || listFieldId !== null}>
    <CodeBodyView
      bind:this={codeBodyView}
      bind:rawBody
      bind:entryInputDrafts={deps.promptDrafts.drafts}
      hostPaneId={deps.hostPaneId}
      scene={model.scene}
      documentKind={model.documentKind}
      structure={deps.structure}
      researchStructure={deps.researchStructure}
      loreEntries={deps.loreEntries}
      promptEntries={deps.promptEntries}
      availableScenes={deps.availableScenes}
      rawBodyLanguage={model.rawBodyLanguage}
      loadedSceneId={model.loadedSceneId}
      nextInputDraftId={deps.promptDrafts.nextDraftId}
      entrySlugify={deps.promptDrafts.slugify}
      readOnly={model.inheritedReadOnly}
      onInputsChange={on.change}
      bind:offerOn={offerOnDraft}
      onOfferOnChange={on.change}
      bind:contextStrategy={contextStrategyDraft}
      onContextStrategyChange={on.change}
    />
  </div>
{/if}
{#if model.bodyShape === "prose"}
  {#if model.scrubbed}
    <!-- The effective body as of the scrub point (§4.4). -->
    <ReadOnlyBodyOverlay
      html={model.overlayBodyHtml}
      label="Effective body (read-only)"
      ribbon={bodyMutated ? `Body as of ${model.scrub.units[model.scrub.index - 1]?.records[0]?.scene_path || "scene"} — mutated` : ""}
      ribbonMark="⤳"
      frontMatter={model.frontMatter}
      appendix={model.appendix}
    />
  {:else if model.snapshotParked}
    <!-- The parked snapshot, on the same overlay: the live buffer stays
         mounted and hidden underneath (ADR-0044 §G). -->
    <ReadOnlyBodyOverlay
      html={model.snapshots.bodyHtml}
      label="Snapshot body (read-only)"
      ribbon={model.snapshotRibbon}
      tone="snapshot"
      onRunClick={(regionId, kind) => model.snapshots.adopt(regionId, kind)}
      frontMatter={model.frontMatter}
      appendix={model.appendix}
    />
  {:else if model.entryReview.hasReview && model.entryReview.proposal}
    <EntryReviewOverlay review={model.entryReview} />
  {/if}
  <div
    class="prose-body-host"
    class:hidden={model.scrubbed || model.snapshotParked || model.reviewing || listFieldId !== null}
  >
    <ProseBodyView
      bind:this={proseBodyView}
    bind:liveWordCount
    bind:editorEmpty
    bind:hasInteriorityBeats
    bind:interiorityRevealed
    bind:lastInvocationCostUsd
    bind:sceneSessionCostUsd
    bind:characterCostUsd
    scene={model.scene}
    documentKind={model.documentKind}
    loreEntries={deps.loreEntries}
    promptEntries={deps.promptEntries}
    availableScenes={deps.availableScenes}
    implicitContextMatcher={deps.implicitContextMatcher}
    documentLabel={deps.documentLabel}
    onBodyChange={on.change}
    onFocus={() => on.focus()}
    onOpenChat={(payload) => on.openChat(payload)}
    onRequestInputsDialog={(payload) => on.requestInputsDialog(payload)}
    neighbours={() => deps.sectionRegistry.neighboursFor(0)}
    onEditorReady={(editor, phase) => phase === "ready" ? deps.sectionRegistry.register(0, null, editor) : deps.sectionRegistry.unregister(editor)}
    frontMatter={model.frontMatter}
    appendix={model.appendix}
    {proseAfterSections}
    >
      <!-- The long_text sections (#2009) render inside the prose view's own
           scroll frame, never as siblings: the panel grid places direct
           children by position (#2030). -->
      {#snippet sections()}
        <BodySections
          schema={model.metadataSchema}
          entryType={model.entryType}
          metadata={model.metadata}
          readOnly={model.editorReadOnly}
          onMetadataChange={(next) => on.metadataChange(next)}
          implicitContextMatcher={deps.implicitContextMatcher}
          register={deps.sectionRegistry}
          documentKind={model.documentKind}
          loreEntries={deps.loreEntries}
          promptEntries={deps.promptEntries}
          structure={deps.structure}
          researchStructure={deps.researchStructure}
          excludeId={model.scene?.id ?? null}
          createLayerId={model.createLayerId}
          tagTitleById={$tagTitleById}
          onNavigate={(payload) => on.navigate(payload)}
        />
      {/snippet}
    </ProseBodyView>
  </div>
{/if}
{#if model.bodyShape === "chat"}
  <ChatBodyView
    bind:this={chatBodyView}
    scene={model.scene}
    promptEntries={deps.promptEntries}
    assistantEntries={deps.assistantEntries}
    loreEntries={deps.loreEntries}
    structure={deps.structure}
    researchStructure={deps.researchStructure}
    defaultAssistantId={deps.defaultAssistantId}
    implicitContextMatcher={deps.implicitContextMatcher}
    titleField={model.chatTitleField}
    onBodyChange={on.change}
    onFocus={() => on.focus()}
  />
{/if}
{#if model.bodyShape === "view"}
  <!-- #2010: same hidden-host pattern as prose/code/none — a view pane is a
     lightweight component (no undo buffer to preserve), but hiding rather
     than conditionally mounting keeps ALL five shapes on one rule. -->
  <div class="view-body-host" class:hidden={listFieldId !== null}>
    <ViewBodyView
      bind:this={viewBodyView}
      scene={model.scene}
      loreEntries={deps.loreEntries}
      promptEntries={deps.promptEntries}
      assistantEntries={deps.assistantEntries}
      structure={deps.structure}
      researchStructure={deps.researchStructure}
      onBodyChange={on.change}
      onFocus={() => on.focus()}
      onSaveState={(state) => on.viewSaveState(state)}
    />
  </div>
{/if}
{#if activeListFieldIds.length > 0 && model.metadataSchema}
  <!-- #2010/#2100: the active tab is a list tab — render its full editor(s)
       as direct grid child(ren), alongside the (hidden, still-mounted) shape
       body. `.list-tab-host` is `display: contents` for the common one-field
       tab (byte-identical to before this stayed a single grid child); a
       merged Section tab (ADR-0089 Amendment 1, several `fieldIds`) instead
       stacks its fields, each already carrying its own field-label heading
       (ReferenceListTab's `.ref-list-head`), inside one scroll container.
       #2072/ADR-0089 §6: `keyMember` widens a tab's field to a
       reference-keyed `list`; `effectiveItems` threads the scrub overlay so
       the tab reads the Chapter-N items, not the base, while scrubbed. -->
  <div class="list-tab-host" class:list-tab-host-stacked={activeListFieldIds.length > 1}>
    {#each activeListFieldIds as fieldId (fieldId)}
      <ReferenceListTab
        model={{
          field: model.metadataSchema.fields[fieldId],
          fieldId,
          entryType: model.entryType,
          fieldLabel: effectiveFieldLabel(model.metadataSchema, model.entryType, fieldId),
          items: toItemList(model.metadata[fieldId]),
          keyMember: keyedListKeyMember(model.metadataSchema.fields[fieldId]),
          effectiveItems: model.scrubbed ? ((model.scrub.overrides?.[fieldId] as MetadataValue[] | undefined) ?? null) : null,
          readOnly: model.editorReadOnly && !stopEditableFor(fieldId),
          schema: model.metadataSchema,
          nodeId: model.scene?.id ?? "",
        }}
        deps={{
          loreEntries: deps.loreEntries,
          promptEntries: deps.promptEntries,
          assistantEntries: deps.assistantEntries,
          structure: deps.structure,
          researchStructure: deps.researchStructure,
          tagTitleById: $tagTitleById,
          implicitContextMatcher: deps.implicitContextMatcher,
          excludeId: model.scene?.id ?? null,
          createLayerId: model.createLayerId,
        }}
        on={{
          change: (items) => void handleListChange(fieldId, items),
          navigate: (payload) => on.navigate(payload),
        }}
      />
    {/each}
  </div>
{/if}

<style>
  /* none-shape: the rail IS the pane (assistant / project / structure_node). */
  .editor-pane-meta {
    flex: 1 1 auto;
    min-height: 0;
    overflow: auto;
    overscroll-behavior: contain;
    padding: 18px 0;
  }

  /* ---- Time-travel overlay chrome (#64) ---------------------------------- */
  /* Keeps ProseBodyView a direct grid child of .editor-panel when visible;
     display:none while scrubbed preserves the mounted TipTap buffer. #2010
     reuses the same pattern for `.none-body-host`/`.view-body-host` so a body
     tab strip's list tab can HIDE a shape's own body instead of unmounting
     it — the none-shape metaContent and the view designer carry live edit
     state exactly like prose/code do. */
  .prose-body-host,
  .code-body-host,
  .none-body-host,
  .view-body-host {
    display: contents;
  }
  .prose-body-host.hidden,
  .code-body-host.hidden,
  .none-body-host.hidden,
  .view-body-host.hidden {
    display: none;
  }

  /* #2100/ADR-0089 Amendment 1: `display: contents` for the common one-field
     tab keeps ReferenceListTab a direct grid child exactly as before this
     wrapper existed. A merged Section tab (2+ fieldIds) instead becomes the
     scroll container itself, stacking each field's own full-height editor at
     its natural size rather than every one fighting for the whole row. */
  .list-tab-host {
    display: contents;
  }
  .list-tab-host.list-tab-host-stacked {
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-height: 0;
    height: 100%;
    overflow: auto;
  }
  .list-tab-host.list-tab-host-stacked > :global(.ref-list-tab) {
    flex: 0 0 auto;
    height: auto;
  }
</style>
