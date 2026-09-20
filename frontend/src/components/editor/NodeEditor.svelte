<script lang="ts">

  import { untrack } from "svelte";
  import RegionRegistrar from "@/components/workspace/RegionRegistrar.svelte";
  import { closeSubordinatePane, openSubordinatePane } from "@/lib/utils/subordinatePane";
  import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
  import FootDock from "@/components/editor/FootDock.svelte";
  import EditorRail from "@/components/editor/EditorRail.svelte";
  import { editorRailLayout } from "@/lib/stores/editorRailLayout.svelte";
  import { findNodeBySceneId } from "@/lib/utils/treeHelpers";
  import { LoreScrubController } from "@/lib/stores/loreScrub.svelte";
  import { EntryProposalController } from "@/lib/stores/entryProposal.svelte";
  import { refreshTagNodes, resolveAdoptedTagFields } from "@/lib/stores/tagNodes";
  import { SnapshotStripController } from "@/lib/stores/snapshotStrip.svelte";
  import { implicitContextFor } from "@/lib/stores/implicitContext.svelte";
  import { notchWhen } from "@/lib/utils/snapshotTime";
  import PromptInvocationDialog from "@/components/editor/PromptInvocationDialog.svelte";
  import EditorBodyHost from "@/components/editor/EditorBodyHost.svelte";
  import EditorHeader from "@/components/editor/EditorHeader.svelte";
  import EditorRailContent from "@/components/editor/EditorRailContent.svelte";
  import { createSectionRegistry } from "@/lib/editor-core/sectionKeyboardBridge";
  import { keyedListKeyMember } from "@/lib/editor-core/keyedList";
  import type { SearchReveal } from "@/lib/editor-core/searchMatchHighlight";
  import { PromptInputDraftsController } from "@/lib/stores/promptInputDrafts.svelte";
  import { characterCostRows, rollupCostFor } from "@/lib/editor-core/characterCost";
  import { sceneMarkdownToHtml } from "@/lib/utils/markdown";
  import type { AssistantEntrySummary, Backlink, BodyShape, DocumentKind, EditableDocument, EntryBodyLanguage, EntryMetadata, EntryTypeDefinition, MetadataSchema, NavigateTarget, PromptContextStrategy, PromptEntrySummary, PromptInputDefinition, ViewSpec } from "@/lib/types";
  import type { ViewSaveState } from "@/lib/editor-core/editorPaneModel";
  import { metadataSchemaLayersStore, metadataSchemaStore } from "@/lib/stores/schema";
  import { snapshotLayerId } from "@/lib/utils/layerAuthoring";
  import { readOnlyInPlace } from "@/lib/utils/provenance";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { backlinksFor } from "@/lib/views/backlinks";
  import { effectiveFieldLabel } from "@/lib/utils/schemaTypeHelpers";
  import { mutationsVersion } from "@/lib/stores/mutationsVersion.svelte";
  import { deriveBodyShape, documentLabelFor } from "@/lib/editor-core/documentPresentation";
  import { wireReviewFreeze } from "@/lib/editor-core/reviewFreeze.svelte";
  import { buildBodyTabs } from "@/lib/editor-core/bodyTabs";
  import { restoredBodyTab } from "@/lib/editor-core/bodyTabRestore";
  import { bodyMemory } from "@/lib/stores/bodyMemory.svelte";

  interface Props {
    scene?: EditableDocument | null;
    documentKind?: DocumentKind;
    promptEntries?: PromptEntrySummary[];
    // dialog. Optional — the picker degrades to "no items" when missing.
    structure?: import("@/lib/types").StructureDocument | null;
    // research notes.
    researchStructure?: import("@/lib/types").StructureDocument | null;
    loreEntries?: import("@/lib/types").LoreEntrySummary[];
    // plugin on long-text metadata fields. App.svelte owns the compile.
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    assistantEntries?: AssistantEntrySummary[];
    defaultAssistantId?: string;
    // host-agnostic — App.svelte derives this from its structure tree.
    availableScenes?: { id: string; title: string }[];
    metadataReload?: { token: number; metadata: EntryMetadata; status?: string; entryType: string } | null;
    titleReload?: { token: number; title: string } | null;
    dirty?: boolean;
    // True for ~2s after a save (#314): drives the layer picker's "Saved to …"
    // footer echo — the only per-write signal the silent autosave permits.
    recentlySaved?: boolean;
    // ADR-0042's authoring layer L for an inherited lore entry (#314): the layer
    // id the rail picker targets. `null` = rest (save to the open project / the
    // entry's own file). The pane store owns it; the picker reports changes up
    // via onAuthoringLayerChange.
    authoringLayerId?: string | null;
    todoStatusHint?: string;
    // The workspace pane hosting this editor. Threaded to ConversationsPanel so a
    // launched Brainstorm chat registers as this pane's subordinate (auto-closes
    // with it). Null when the host isn't a tiled pane (e.g. a test mount).
    hostPaneId?: string | null;
    // INTERNAL on: listeners (to still-legacy MetadataPanel/*BodyView) are unchanged.
    onChange?: ((payload: { title: string; body: string; status: string; entryType: string; metadata: EntryMetadata; inputs?: PromptInputDefinition[]; offer_on?: string[]; context_strategy?: PromptContextStrategy | null }) => void) | undefined;
    onFocus?: (() => void) | undefined;
    onCustomData?: ((payload: { entryType: string; kind: DocumentKind }) => void) | undefined;
    onNavigate?: ((target: NavigateTarget) => void) | undefined;
    onOpenChat?: ((payload: { entry: PromptEntrySummary; inputs: Record<string, unknown>; sceneId: string | null; assistantId: string }) => void) | undefined;
    // The view designer self-persists; it reports its save lifecycle up so the
    // pane's tab badge can reflect it (#263).
    onViewSaveState?: ((state: ViewSaveState) => void) | undefined;
    // The rail layer picker chose a new authoring layer L (#314). Fires only
    // after the confirm-on-entry gate for a target beyond the open project.
    onAuthoringLayerChange?: ((layerId: string | null) => void) | undefined;
    // Clear-to-inherit (#517): a field's override was reset to the inherited
    // value from the rail. Lore-only — the host routes it to the store action.
    onResetField?: ((fieldId: string) => void) | undefined;
    // Snapshots (#401). Autosave lags the buffer by up to 6 seconds, and both
    // capture and restore read the FILE — so the strip asks the host to write
    // pending edits first, and hands the restored document back for the host to
    // reload. The pane store owns the document lifecycle; the card does not.
    onFlushScene?: (() => Promise<void>) | undefined;
    onSceneRestored?: ((restored: import("@/lib/types").Scene) => void | Promise<void>) | undefined;
    // A lore snapshot restore (ADR-0088 S1). The node route returns the re-folded
    // entry; the host reloads it by id (reconcileNodeFromServer). Kept distinct
    // from onSceneRestored so the scene path's Scene-typed reload is unchanged.
    onNodeRestored?: ((nodeId: string) => void | Promise<void>) | undefined;
    // Roleplay presence (ADR-0070 S3): fires when this scene's editor gains or
    // loses roleplay beats, so the shell (App → ≡ menu) can enable/disable the
    // "Finalize roleplay…" action. `hasInteriorityBeats` otherwise dead-ends here.
    onInteriorityChange?: ((hasBeats: boolean) => void) | undefined;
    // AI-review freeze (#634 / ADR-0046). A lore brainstorm proposal makes the
    // entry a frozen save-on-Done transaction: the host asks the pane controller
    // to suppress autosave for the review's life (committer non-null) or resume it
    // (null), and to issue the ONE explicit post on commit. The pane store owns
    // the document lifecycle; the card does not (as with onFlushScene).
    onReviewFreeze?: ((entryId: string, committer: import("@/lib/stores/editorPanes.svelte").ReviewCommitter | null) => void) | undefined;
    onFlushReviewCommit?: ((entryId: string) => Promise<boolean>) | undefined;
  }

  let {
    scene = null,
    documentKind = "manuscript",
    promptEntries = [],
    structure = null,
    researchStructure = null,
    loreEntries = [],
    implicitContextMatcher = null,
    assistantEntries = [],
    defaultAssistantId = "",
    availableScenes = [],
    metadataReload = null,
    titleReload = null,
    dirty = false,
    recentlySaved = false,
    authoringLayerId = null,
    todoStatusHint = "",
    hostPaneId = null,
    onChange = undefined,
    onFocus = undefined,
    onCustomData = undefined,
    onNavigate = undefined,
    onOpenChat = undefined,
    onViewSaveState = undefined,
    onAuthoringLayerChange = undefined,
    onResetField = undefined,
    onFlushScene = undefined,
    onSceneRestored = undefined,
    onNodeRestored = undefined,
    onInteriorityChange = undefined,
    onReviewFreeze = undefined,
    onFlushReviewCommit = undefined
  }: Props = $props();

  const sectionRegistry = createSectionRegistry(); // #2009: body-section keyboard bridge + "go to" registry
  let bodyHost: EditorBodyHost | null = $state(null); // #2029: the five body-shape branches + their bind:this view refs live here now
  let loadedSceneId: string | null = $state(null);
  // A memoized PRIMITIVE id. Reading the object prop `scene` inside an effect
  // subscribes that effect to the `scene` prop signal, which Svelte re-fires on
  // every parent re-render — and the pane re-renders on every keystroke (the draft
  // update reassigns the panes array, re-setting this object prop; an object is
  // never `safe_not_equal`-equal, so the signal fires even when the reference is
  // unchanged). Depending on this derived STRING instead gates the id-keyed fetch
  // effects (the lore mutations timeline and the backlinks/reference-resolve) so
  // they re-run only when the id actually changes, not on content edits (#969). Cf.
  // the body-hydration guard below, which sidesteps the same churn with
  // `scene.id !== loadedSceneId`. (The scenes-only snapshot-strip effect reads the
  // object prop too, but its `load()` also resets the parked notch and the strip
  // self-refreshes on its own mutations, so it is left to a separate follow-up.)
  const sceneId = $derived(scene?.id ?? null);
  let rawBody = $state("");
  let lastEmittedRawBody = $state("");
  let title = $state("");
  let status = $state("draft");
  let entryType = $state("scene");
  let metadata: EntryMetadata = $state({});
  // Bound out from ProseBodyView so MetadataPanel's computedFieldString
  // (word_count) + the editor-hint string can read them.
  let liveWordCount = $state(0);
  let editorEmpty = $state(true);
  // Roleplay interiority (ADR-0070 S2): buffer holds ≥1 beat (gates the shell
  // toggle) / any beat currently revealed (drives its adaptive-stateful look).
  let hasInteriorityBeats = $state(false);
  let interiorityRevealed = $state(false);
  // Metadata rail (body-spec Section A). Per body shape: prose/code open,
  // chat collapses to a 34px edge-tab, none turns the rail into the pane.
  // `railOpen` is the user-toggleable state for the side rail; reset per
  // scene load below. `railIsPane` means metadata renders as the main
  // content (none-shape: assistant / project / structure_node).
  let railOpen = $state(true);

  // ---- Time-travel scrub state (#64, ADR-0013; per-unit stops #70) -----------
  // State + fetch + resolve live in LoreScrubController; the card keeps only
  // the reload trigger (entity switch or an index-touching save, #63 — either
  // may have moved/removed stops, so position resets to base).
  const scrub = new LoreScrubController();
  let scrubbed = $derived(documentKind === "lore" && scrub.index > 0);

  $effect(() => {
    const id = documentKind === "lore" ? sceneId : null;
    void mutationsVersion.value;
    return scrub.load(id);
  });

  // ---- Snapshot strip (#401, ADR-0044; lore surface ADR-0088 S1) ------------
  // The same shape as the scrub above, on the real-time axis: `parked` flips
  // the body to a read-only overlay while the TipTap buffer stays mounted and
  // hidden underneath. Scenes use their own routes; a lore card reaches the node
  // routes at the layer its edits write to (ADR-0087 §3b / ADR-0088). The
  // mutation scrubber still lives in the rail here — S2 unifies the two axes into
  // one foot dock with a mode control; S1 only surfaces the snapshot axis.
  const snapshots = new SnapshotStripController();
  let snapshotParked = $derived(
    (documentKind === "manuscript" || documentKind === "lore") && snapshots.parked !== null,
  );

  // The snapshot track's layer scope (ADR-0088 §6): lore reads the node routes at
  // the layer its edits write to (base vs override), mirrored from the same
  // authoringLayerId the save uses; a scene has no layer axis. Kept a STRING so
  // the load effect re-runs on a real layer switch but not on every keystroke —
  // reading `scene` recomputes it, yet the stable value keeps the dep from
  // re-firing (cf. the sceneId memo above).
  let snapshotLayer = $derived(
    documentKind === "lore" && scene
      ? snapshotLayerId(authoringLayerId, scene.source_layer_id)
      : null,
  );
  // The human label for that write layer, for the parked caption (§6): the
  // override layer when overriding, else the entry's owning layer.
  let snapshotWritesLabel = $derived.by(() => {
    if (documentKind !== "lore" || !scene) return null;
    const layerId = snapshotLayer ?? scene.source_layer_id ?? null;
    if (!layerId) return null;
    return (
      $metadataSchemaLayersStore.find((layer) => layer.id === layerId)?.label ??
      scene.source_layer_label ??
      null
    );
  });

  // Forward roleplay-beat presence to the shell (ADR-0070 S3) so App can gate the
  // ≡-menu Finalize action. hasInteriorityBeats is bound out of ProseBodyView.
  $effect(() => {
    onInteriorityChange?.(hasInteriorityBeats);
  });

  $effect(() => {
    snapshots.flushScene = onFlushScene ?? null;
    // A scene restore hands the returned Scene to reconcileSceneFromServer; a lore
    // restore re-fetches by id (the node route returns the re-folded entry, which
    // reconcileNodeFromServer reloads). Dispatching here leaves the scene path's
    // Scene-typed reload untouched (ADR-0088 anti-goal).
    snapshots.onRestored = (restored) =>
      documentKind === "lore"
        ? onNodeRestored?.(sceneId ?? "")
        : onSceneRestored?.(restored as import("@/lib/types").Scene);
    // Adopting a region writes only the prose, through the hidden buffer restore
    // already owns — so it goes straight to the view, not back through the
    // server (ADR-0044 Amendment 4). Evaluated at call time, like `readLive`.
    snapshots.onAdopt = (body) => bodyHost?.adoptBody(body);
    // What the diff compares against: the BUFFER, not the file. Autosave lags
    // by up to six seconds, so the file is not reliably what the author is
    // looking at — and parking is a reading gesture, so flushing to make it
    // current would make reading write (ADR-0044 §G).
    snapshots.readLive = () => ({
      body: bodyHost?.getBody() ?? scene?.body ?? "",
      title,
      status,
      metadata,
      // The *now* side of the witness's dynamic axis (#439) — the same hits
      // the author sees underlined, not a rescan.
      dynamic_context: scene?.id ? implicitContextFor(scene.id) : undefined,
    });
    // Depends only on the primitive id / kind / layer — never the churning
    // `scene` object — so a keystroke does not reload the strip and reset the
    // parked notch (cf. the sceneId memo). A layer switch (authoringLayerId →
    // snapshotLayer) IS a real change and swaps the set (§6). The ternary is the
    // load() argument so each branch is contextually typed to SnapshotTarget.
    const layer = snapshotLayer;
    return snapshots.load(
      !sceneId
        ? null
        : documentKind === "manuscript"
          ? sceneId
          : documentKind === "lore"
            ? { kind: "node", nodeId: sceneId, layer }
            : null,
    );
  });

  // The rail flips with the body (§F). Kept apart from `effectiveOverrides`:
  // that axis draws a glyph, and a snapshot difference must never have one.
  const VIEW_LABEL = { both: "both versions", now: "the scene now", was: "the snapshot" } as const;
  let snapshotRibbon = $derived(
    `Snapshot · ${notchWhen(snapshots.current)} · reading ${VIEW_LABEL[snapshots.view]}`,
  );

  let snapshotCompare = $derived(
    snapshotParked ? { fields: snapshots.fields, side: snapshots.fieldSide() } : null,
  );

  // Effective intrinsics at the scrub point. Title/body may be mutated too
  // (ADR-0009 amendment) — scope is total, the whole card travels.
  let titleMutated = $derived(scrubbed && scrub.overrides != null && "title" in scrub.overrides);
  let effectiveTitle = $derived(titleMutated ? String(scrub.overrides?.title ?? "") : title);
  let bodyMutated = $derived(scrubbed && scrub.overrides != null && "body" in scrub.overrides);

  // The read-only body overlay (§4.4, buffer-safe): rendered-markdown of the
  // effective body. The TipTap buffer underneath is never touched — unsaved
  // base edits survive a scrub round-trip untouched. Base body reads from the
  // LIVE buffer (not the saved baseline) so an unmutated scrub shows exactly
  // what the writer sees at stop 0.
  let overlayBodyHtml = $state("");
  $effect(() => {
    if (!scrubbed || bodyShape !== "prose") {
      overlayBodyHtml = "";
      return;
    }
    const overrideBody = bodyMutated ? String(scrub.overrides?.body ?? "") : null;
    const markdown = overrideBody ?? bodyHost?.getBody() ?? scene?.body ?? "";
    let cancelled = false;
    void sceneMarkdownToHtml(markdown).then((html) => {
      if (!cancelled) overlayBodyHtml = html;
    });
    return () => {
      cancelled = true;
    };
  });

  // Per-scene continuation cost rollup. Bound out from ProseBodyView so the
  // header chip stays in the shell (where the rest of the document header
  // lives). Cost state itself is owned by ProseBodyView since the AI
  // streaming machinery that produces it lives there.
  let lastInvocationCostUsd: number | null = $state(null);
  let sceneSessionCostUsd = $state(0);
  // Per-character cost map for this scene, summed from the persisted
  // ai_invocations log. ProseBodyView owns the state; the footer reads it.
  let characterCostUsd: Record<string, number> = $state({});

  let lastMetadataReloadToken = $state(0);
  let lastTitleReloadToken = $state(0);
  let backlinks: Backlink[] = $state([]);
  let lastBacklinksSceneId: string | null = $state(null);
  // The prompt-invocation modal ("fill inputs, then fire") is a self-contained
  // subsystem (#631): its draft/assistant/estimate state + the InputsDialog
  // render branch live in PromptInvocationDialog, opened imperatively below.
  let promptDialog: PromptInvocationDialog | null = $state(null);

  // Per-entry prompt inputs (declaration side). Inputs live on the entry, not
  // the entry-type. The controller owns the editor-side draft state (bound into
  // CodeBodyView), the reseed-on-scene-change, and the canonical serialization
  // for save; the shell rebuilds the canonical PromptInputDefinition[] via
  // `toCanonical()` inside `emitChange` (#631).
  const promptDrafts = new PromptInputDraftsController();

  // The offer_on targeting draft (ADR-0054 §4 / S4b) — the ＋New subject allow-
  // list authored in CodeBodyView's picker. A plain string[] (unlike the inputs
  // controller), reseeded from the open prompt on a scene switch and emitted in
  // `emitChange` alongside inputs. Guarded by scene id (below) so a picker edit
  // isn't clobbered when the pre-effect re-runs for an unrelated scene mutation.
  let offerOnDraft = $state<string[]>([]);
  let lastOfferOnSceneId: string | null = null;

  // The context_strategy.output draft (ADR-0062 D3) — the mode + headless +
  // commit/on_accept sub-form authored in CodeBodyView's PromptOutputEditor.
  // Mirrors offerOnDraft: reseeded from the open prompt on a scene switch,
  // emitted in `emitChange` alongside it. Round-tripping this on every save is
  // what closes the wipe bug (a save that omits it strips a forked prompt's
  // output config, see api.ts savePromptEntry).
  let contextStrategyDraft = $state<PromptContextStrategy | null>(null);

  let backlinksReq = 0;
  // Backlinks = the open node's referrers (#194): membership from the in-memory
  // reverse index, rows from `resolve_references`. A request token drops out-of-
  // order resolves when the anchor or the index changes mid-flight.
  async function refreshBacklinks(
    anchorId: string,
    referenceIndex: ReadonlyMap<string, ReadonlySet<string>>,
  ) {
    lastBacklinksSceneId = anchorId;
    const req = ++backlinksReq;
    try {
      const next = await backlinksFor(anchorId, referenceIndex);
      if (req === backlinksReq) backlinks = next;
    } catch {
      if (req === backlinksReq) backlinks = [];
    }
  }

  // Compose the save event from the parent's title/status/metadata plus
  // whichever body view owns the current body content. ProseBodyView
  // dispatches `body-change` (or other reactives mutate `rawBody`) and
  // that fires the rawBodyMode reactive above which calls emitChange.
  // Title input handler. For chats, feed the new title into ChatBodyView,
  // which owns the chat's title state and persists it (saveEditorPane is a
  // no-op for chats). Other kinds persist via the pane draft → saveEditorPane.
  function handleTitleInput() {
    emitChange();
    bodyHost?.setTitleFromPane(title);
  }

  function emitChange() {
    if (!scene) return;
    onChange?.({
      title,
      body: rawBodyMode ? rawBody : (bodyHost?.getBody() ?? ""),
      status,
      entryType,
      metadata: cloneMetadata(metadata),
      inputs: documentKind === "prompt" ? promptDrafts.toCanonical() : undefined,
      offer_on: documentKind === "prompt" ? [...offerOnDraft] : undefined,
      context_strategy: documentKind === "prompt" ? contextStrategyDraft : undefined,
    });
  }

  function cloneMetadata(value: EntryMetadata) {
    return JSON.parse(JSON.stringify(value ?? {})) as EntryMetadata;
  }

  function updateStatus(value: string) {
    status = value;
    emitChange();
  }

  function updateEntryType(value: string) {
    entryType = value;
    emitChange();
  }

  function defaultEntryType() {
    if (documentKind === "lore") return "lore:note";
    if (documentKind === "chat") return "chat:chat_session";
    return "manuscript:scene";
  }

  function defaultStatus() {
    return documentKind === "manuscript" ? "draft" : "";
  }

  function documentStatus(document: EditableDocument) {
    return "status" in document ? document.status || "draft" : "";
  }

  function computedFieldString(fieldId: string) {
    if (fieldId === "word_count") return String(liveWordCount);
    const value = scene?.computed_metadata?.[fieldId];
    if (Array.isArray(value)) return value.join(", ");
    if (value === null || value === undefined) return "";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  // metadataSchema is global per-project — read from the store, not a prop (#14
  // Step 2). Declared HERE, above the first pre-effect that reads it: a
  // pre-effect's first run can execute synchronously at creation (a lazy mount
  // into an already-running flush — every doc open), and a `$derived` declared
  // below it is still in its temporal dead zone then (#684 — the editor body
  // silently never mounted).
  let metadataSchema = $derived($metadataSchemaStore);

  // ADR-0046 slice 2/3 — the entry-patch brainstorm review, generalized to any
  // schema-typed node (ADR-0048 §5). A `revise:entry` chat commits an EntryPatch
  // (launched via ConversationsPanel's ＋New menu); the controller derives the proposed-vs-
  // current flips off the live buffer fed below, and the adopt write stays here
  // (owns `metadata` + prose buffer, so both land in one PUT — ADR-0046 §1). The
  // controller is kind-agnostic, and so is participation (#711): a node reviews iff
  // a commit prompt patched it (keyed on the node id), never by a host kind list.
  const entryReview = new EntryProposalController();
  $effect.pre(() => {
    entryReview.nodeId = scene?.id ?? null;
    entryReview.schema = metadataSchema;
    // `title`/`status` live off `metadata` in their own shell state, but a patch
    // can flip them (a rename / a status change), so fold them into the metadata
    // view the controller diffs against — else their flip's "current" side reads
    // as unset. Adoption routes them back out (onAdoptFields below).
    entryReview.metadata = { ...metadata, title, status };
  });
  entryReview.onAdoptFields = async (fields) => {
    // `title`/`status` are proposable but stored off `metadata` (saved via the
    // top-level payload fields, and the backend applies a rename on post), so
    // route an adopted flip to the matching shell state and keep it out of the
    // metadata merge — else the merge would set a phantom key the save ignores.
    // emitChange (below) packages title + status + metadata into the one PUT.
    const next = { ...fields };
    if ("title" in next) {
      title = String(next.title ?? "");
      delete next.title;
    }
    if ("status" in next) {
      status = String(next.status ?? "");
      delete next.status;
    }
    // ADR-0082 §2 / #1797: an ADOPTED tag-vocabulary flip may still carry
    // unresolved titles (the validator never mints — see entryProposal's
    // module note). Resolve/mint them now, only because the author accepted
    // this field — the same `createLayerId` the metadata panel's own picker
    // threads for its "Create ‹x›" (P5), so an AI-accepted tag lands at the
    // identical layer a hand-typed one would. A rejection here is left to
    // propagate — deliberately not caught: `EntryProposalController.commit()`
    // (round 2, Y1) is what turns it into `commitError` + an aborted commit
    // that keeps the review open, so there's nothing to handle at this layer.
    // Shared with treeActions' create-from-draft accept moment (#1821) —
    // see `resolveAdoptedTagFields`'s doc comment.
    await resolveAdoptedTagFields(next, metadataSchema, createLayerId ?? null);
    metadata = { ...metadata, ...next };
  };
  // Body adopt/read route to the ACTIVE body view: the raw editor for a code body
  // (a prompt template — #711), TipTap otherwise. Both sides are plain strings, so
  // the run-diff review reads a template exactly as it reads prose. `rawBody` feeds
  // the save the same way a keystroke does (the rawBodyMode effect → emitChange).
  entryReview.onAdoptBody = (body) => {
    if (rawBodyMode) rawBody = body;
    else bodyHost?.adoptBody(body);
  };
  entryReview.onEmitChange = emitChange;
  entryReview.readCurrentBody = () =>
    rawBodyMode ? rawBody : (bodyHost?.getBody() ?? scene?.body ?? "");
  // The one explicit post that ends a commit — the pane controller cancels the
  // (frozen) timer and PUTs once (body + metadata together).
  entryReview.onFlush = () => {
    if (scene?.id) return onFlushReviewCommit?.(scene.id);
  };

  // A node under an open brainstorm review is a frozen transaction (#634): the
  // rail/title go read-only and the host suppresses autosave, so the diff's
  // "current" side cannot move under the review. Participation is DATA-DRIVEN, not
  // a per-kind allow-list (#711): a review exists iff a commit-carrying prompt
  // (ADR-0054 §2) patched THIS node — `entryReview.proposal` is keyed on the node
  // id alone (see EntryProposalController), and the only writer is a commit chat's
  // extraction, itself gated by the prompt's `offer_on` + commit disposition. So
  // review-mode follows the launching PROMPT, never the host kind; the freeze and
  // the review overlay (rendered for prose AND code bodies below) read this same
  // `hasReview`, so they can't drift.
  const reviewing = $derived(entryReview.hasReview);
  // An INHERITED prompt is read-only in place: the backend refuses any save
  // (409) whether it is a built-in Library node (ADR-0049) or an ancestor
  // project's prompt (#676). Lock the whole editor — title, fields and the code
  // body — and let the ancestor banner offer "Clone to edit" instead of letting
  // the author type into a dead-end.
  //
  // Keyed on the backend's own `editable` verdict via `readOnlyInPlace`
  // (the same helper the banner uses), not re-derived from the async schema
  // layers. The flag rides on the document, so there is no load gap and the lock
  // cannot drift from the backend's 409 (#689). Kind-agnostic across ADR-0049
  // Library tenants (prompts + plot templates — ADR-0048 S4c): every such read-
  // model stamps `editable` and no other does. Fails closed. Own clones are
  // editable, and lore (which forks in place) carries no flag, so it is untouched.
  const inheritedReadOnly = $derived(readOnlyInPlace(scene));
  // The interactive flip lens the rail renders during a lore review (slice 3b):
  // the proposed structured fields as click-to-adopt flips, wired to the
  // controller's per-field resolution. Same `compare` shape snapshot compare
  // feeds MetadataPanel, plus the `resolve` callbacks that make it interactive.
  // Mutually exclusive with `snapshotCompare` (scenes park; lore reviews) —
  // hence the `??` at the call site.
  //
  // The rail follows the judge toggle (#710), reusing MetadataPanel's two lenses:
  // `both` is the interactive adopt lens (`resolve` present → shows the proposed
  // side, click-to-adopt); a single-version view drops `resolve` and reads that
  // whole side passively, exactly like the snapshot compare — so "read the current
  // version whole" switches the fields too, not just the prose.
  const entryCompare = $derived.by(() => {
    if (!reviewing || entryReview.structuredFlips.length === 0) return null;
    const fields = entryReview.structuredCompareFields;
    if (entryReview.view === "both") {
      return {
        fields,
        side: "was" as const,
        resolve: {
          adopted: (fieldId: string) => entryReview.isStructuredAdopted(fieldId),
          onToggle: (fieldId: string) => entryReview.toggleStructured(fieldId),
        },
      };
    }
    return { fields, side: entryReview.fieldSide() };
  });
  // The hooks the pane's close path uses to commit or discard the review.
  const reviewCommitter = {
    hasChanges: () => entryReview.hasPendingChanges,
    commit: () => entryReview.commit(),
    discard: () => entryReview.abandon(),
  };
  // Freeze while reviewing, thaw (null) the instant the review ends or the pane
  // unmounts. Fires only on a genuine transition (entry id / `reviewing`) — never on
  // App recreating the inline `onReviewFreeze` arrow each render, which used to
  // thrash begin/endReviewLock into an unbounded flush loop (#1965). The wiring lives
  // in editor-core so the reactivity contract is unit-testable off the mega-component.
  wireReviewFreeze({
    entryId: () => scene?.id ?? null,
    reviewing: () => reviewing,
    committer: () => reviewCommitter,
    signal: () => onReviewFreeze,
  });
  // Reset accumulated review resolution whenever the proposal identity changes,
  // so a superseding commit starts clean instead of inheriting prior adoptions.
  $effect(() => {
    entryReview.proposal;
    entryReview.resetResolution();
  });
  // A patch touching a tag-vocabulary field (#1797/#1799) may name a tag that
  // was created elsewhere since this pane last refreshed its roster — pull it
  // so a title the backend DID resolve to a real id (`tagTitleById` just
  // stale) renders as that tag's title, not a false "new tag" candidate
  // (`MetadataPanel`'s flip-chip strip tells the two apart by roster
  // membership alone). Never mints anything itself — only ACCEPT does that.
  $effect(() => {
    if (entryReview.proposesTagField) refreshTagNodes();
  });

  // Editor-pane handle exports — forwarded to EditorBodyHost (#2029) and called
  // by the editorPanes controller via `editorPaneComponents[pane.id].xxx(...)`.
  // reloadScene re-seeds whichever body the shape mounts — TipTap for prose,
  // `rawBody` for code — from a server scene, so a reconcile after an
  // out-of-band write (embedded-TODO, ADR-0085 replace) redraws both;
  // highlightEmbeddedTodo scrolls to a marker.
  export function reloadScene(nextScene: EditableDocument, mode: "boundary" | "reconcile" = "boundary") {
    if (rawBodyMode) {
      rawBody = nextScene.body ?? "";
      lastEmittedRawBody = rawBody;
      return;
    }
    return bodyHost?.loadScene(nextScene, mode);
  }

  export function highlightEmbeddedTodo(todoId: string) {
    bodyHost?.highlightEmbeddedTodo(todoId);
  }

  // A search hit's reveal (#1925) goes to whichever body the shape mounts.
  export function revealSearchMatch(reveal: SearchReveal) {
    bodyHost?.revealSearchMatch(reveal);
  }

  // Rung 2 of the reconcile ladder (ADR-0077): forward the prose three-way merge
  // to the body view. Absent body view (chat/view) → null, i.e. non-prose, so the
  // 409 handler falls to the dialog.
  export function tryMergeProse(baseBody: string, remoteBody: string): Promise<string | null> {
    return bodyHost?.tryMergeProse(baseBody, remoteBody) ?? Promise.resolve(null);
  }

  $effect.pre(() => {
    if (metadataReload && metadataReload.token !== lastMetadataReloadToken) {
      lastMetadataReloadToken = metadataReload.token;
      status = metadataReload.status || defaultStatus();
      entryType = metadataReload.entryType || defaultEntryType();
      metadata = cloneMetadata(metadataReload.metadata);
    }
  });
  // When a NEW entry opens (different id), sync the shell-owned fields
  // synchronously. ProseBodyView's own scene reactive handles the editor
  // body load. Setting entryType / title / metadata here (not inside an
  // async function) is essential: an `await` would break Svelte 5's
  // legacy reactive batching and metadataFieldIds would freeze on the
  // previous entry-type's fields ([[feedback-svelte5-reactivity-traps]]).
  $effect.pre(() => {
    if (scene && scene.id !== loadedSceneId) {
      const nextEntryType = scene.entry_type || defaultEntryType();
      title = scene.title;
      status = documentStatus(scene);
      entryType = nextEntryType;
      metadata = cloneMetadata(scene.metadata ?? {});
      // Read body shape from the FRESHLY-resolved entry-type (not the
      // `bodyShape` reactive, which hasn't recomputed yet — and reading
      // it would introduce a cyclical reactive dependency, since
      // `bodyShape` depends on `entryType`).
      const nextBodyShape = deriveBodyShape(metadataSchema?.entry_types[nextEntryType]);
      if (nextBodyShape === "code") {
        // Code body: hydrate rawBody directly. ProseBodyView is unmounted
        // in this branch so no editor-side load runs.
        rawBody = scene.body ?? "";
        lastEmittedRawBody = rawBody;
      }
      loadedSceneId = scene.id;
      // Chat and the view designer start with the rail collapsed to its
      // edge-tab so the body owns full width; every other shape uses the
      // author's persisted per-project preference (#1246).
      railOpen =
        nextBodyShape === "chat" || nextBodyShape === "view" ? false : !editorRailLayout.collapsed;
    }
  });
  $effect.pre(() => {
    if (!scene && loadedSceneId !== null) {
      loadedSceneId = null;
      title = "";
      status = defaultStatus();
      entryType = defaultEntryType();
      metadata = {};
      liveWordCount = 0;
    }
  });
  let entryTypeDef = $derived(metadataSchema?.entry_types[entryType] ?? null);
  let bodyShape = $derived(deriveBodyShape(entryTypeDef));
  let rawBodyMode = $derived(bodyShape === "code");
  let rawBodyLanguage = $derived((entryTypeDef?.body_language ?? "markdown") satisfies EntryBodyLanguage);

  // ---- Body tab strip (#2010, reopen memory #2013) -----------------------
  // One "Body"/"Details" tab plus one per `entity_ref_list` field; empty when
  // the entry type declares no list fields (no strip). The active tab is
  // remembered per node for the session (bodyMemory) so returning to a node
  // restores the tab the writer left it on, rather than always resetting to
  // "Body".
  let bodyTabs = $derived(buildBodyTabs(metadataSchema, entryType, bodyShape, metadata));
  let activeBodyTab = $state("body");
  $effect(() => {
    // On a genuine node switch (keyed on the primitive id, like the rail
    // reconcile — never a keystroke, which would fight a tab the author is
    // actively looking at) restore this node's remembered tab, validated
    // against the CURRENT bodyTabs in the SAME effect (restoredBodyTab) —
    // so a stale list tab from a different entry type can never flicker in
    // for one render before the fallback effect below catches it.
    activeBodyTab = restoredBodyTab(sceneId ? bodyMemory.tabFor(sceneId) : undefined, bodyTabs);
  });
  // Every deliberate tab change goes through here so the memory and the
  // strip can never disagree (the restore effect above is the only other
  // writer, and it reads the memory rather than writing it).
  function setBodyTab(id: string): void {
    activeBodyTab = id;
    if (sceneId) bodyMemory.rememberTab(sceneId, id);
  }
  $effect(() => {
    // A schema change (or the field itself being removed) can make the active
    // tab's field disappear — fall back to "body" rather than stranding the
    // strip on a tab that no longer exists.
    if (activeBodyTab !== "body" && !bodyTabs.some((tab) => tab.id === activeBodyTab)) {
      setBodyTab("body");
    }
  });
  $effect.pre(() => {
    if (rawBodyMode && rawBody !== lastEmittedRawBody) {
      lastEmittedRawBody = rawBody;
      emitChange();
    }
  });
  let railIsPane = $derived(bodyShape === "none");
  let railSide = $derived(editorRailLayout.side);
  // Persist the collapse toggle per project (#1246) — but only for shapes that
  // honour the stored preference. Chat/view force-collapse on load and the
  // fields-only pane has no rail, so neither should overwrite the preference.
  // The store is read UNTRACKED (#2054): this effect follows THIS pane's
  // toggle only. Tracking the store made two open panes whose rails disagree
  // rewrite the preference in turns (effect_update_depth_exceeded, the pane
  // went dead); the preference is the last toggle and applies on the next
  // node load, as it always did.
  $effect(() => {
    if (!scene || railIsPane || bodyShape === "chat" || bodyShape === "view") return;
    const collapsed = !railOpen;
    if (untrack(() => editorRailLayout.collapsed) !== collapsed) editorRailLayout.setCollapsed(collapsed);
  });

  // ---- Detach Details into a subordinate pane (ADR-0062 reuse, #1258) --------
  // A detached pane copies the prompt sub-tab pattern: register the same
  // `metaContent` snippet under an ephemeral, host-scoped id and tile it beside
  // the editor. It needs no per-document store — every metadata field emits up
  // into `metadata` here, so the pane is a live view, never a second owner.
  const detailsPaneId = $derived(hostPaneId ? `details:${hostPaneId}` : null);
  // Detached-ness is DERIVED from the layout, not held as `$state`: dragging the
  // pane can restructure the tree and remount this editor, which would reset a
  // local flag (snapping the rail back + orphaning the pane). The layout survives
  // that remount, so the husk stays and the new instance re-registers the content.
  const detailsDetached = $derived(!!detailsPaneId && workspaceLayout.isPlaced(detailsPaneId));
  // Front matter (#2054): the rail's existing collapse gains a meaning on a
  // prose body — its facts render at the head of the document and its trailing
  // material as an appendix after it. Never both: the rail is collapsed to its
  // edge tab (the way back) while the blocks show, and a detached rail keeps
  // its pane. Other shapes keep their collapsed rail with nothing shown.
  // Gated on the schema like the rail itself: no schema, no rail, no blocks.
  let frontMatterMode = $derived(
    !!scene && !!metadataSchema && !railIsPane && !railOpen && !detailsDetached && bodyShape === "prose",
  );
  // Offer detach only where there is a host pane AND a rail to tear out.
  let canDetachDetails = $derived(!!hostPaneId && !!scene && !!metadataSchema && !railIsPane);

  function detachDetails(): void {
    if (!detailsPaneId || !hostPaneId || detailsDetached || !canDetachDetails) return;
    openSubordinatePane(detailsPaneId, hostPaneId, reattachDetails, { beside: hostPaneId, edge: "right" });
  }
  function reattachDetails(): void {
    if (detailsPaneId) closeSubordinatePane(detailsPaneId); // idempotent; also the pane's own onClose
  }

  // Fold Details back if the node stops having a rail (a none-shape node renders
  // metadata as the whole pane, which would double-mount the snippet). Teardown
  // on editor close is the subordinatePanes cascade's job, not ours — so a
  // transient remount leaves the pane in place rather than tearing it down.
  $effect(() => {
    if (railIsPane && detailsDetached) reattachDetails();
  });
  let characterCostRowsView = $derived(characterCostRows(characterCostUsd, loreEntries, metadataSchema));
  let rollupCostKind = $derived(rollupCostFor(scene, documentKind));
  $effect.pre(() => {
    promptDrafts.reseed(scene, documentKind);
    if (documentKind !== "prompt" || !scene) {
      lastOfferOnSceneId = null;
    } else if (scene.id !== lastOfferOnSceneId) {
      offerOnDraft = [...((scene as unknown as { offer_on?: string[] }).offer_on ?? [])];
      contextStrategyDraft = (scene as unknown as { context_strategy?: PromptContextStrategy | null }).context_strategy ?? null;
      lastOfferOnSceneId = scene.id;
    }
  });
  let documentLabel = $derived(documentLabelFor(documentKind));

  // ADR-0082 §2/F2: the layer a `create_missing` tag is minted at — "the
  // layer the saved node is written to". The pane's own authoring level
  // (lore/prompt, `authoringLayerId`) when set; else, for an assistant, the
  // open document's own layer; else null (the open project — scenes are
  // always the open project). Always DEFINED here (never left `undefined`) —
  // this is the metadata panel's own host, the one place `create_missing` is
  // offered at all (P5, round 2); every other host passes nothing.
  //
  // The assistant case verified against `save_assistant_entry`
  // (`assistants.py`): it writes straight to `index_entry.path` — the
  // assistant's OWN file, wherever `_build_assistant_index` resolved it from
  // (machine layer, or an ancestor/open project's `assistants/`) — never as
  // an override into the open project the way lore/prompt saves can. So
  // `scene?.source_layer_id` (the assistant's own layer) is the right target
  // for a tag its save introduces, not `null`; `LayerAuthoringBar` itself
  // confirms there's no authoring-level dropdown for an inherited assistant
  // to begin with ("renders only for an inherited lore entry; no-ops
  // otherwise", below) — no override path exists to redirect to.
  let createLayerId = $derived(
    authoringLayerId ?? (documentKind === "assistant" ? (scene?.source_layer_id ?? null) : null),
  );

  // Fields whose value comes from a layer override (#314), passed to the rail so
  // it can lead them with the `ti-versions` mark. The picker itself lives in
  // LayerAuthoringBar (kept out of this shell for the file-size cap).
  let overriddenFieldsForPanel = $derived(
    (documentKind === "lore" || documentKind === "prompt") && scene && "overridden_fields" in scene
      ? ((scene as unknown as { overridden_fields?: string[] }).overridden_fields ?? [])
      : [],
  );
  // The title header's label is the intrinsic `title` field's effective label
  // for this entry type (#116) — schema-driven, so lore reads "Name" (a
  // built-in per-type override) and users can relabel per type. Falls back to
  // "Title" before the schema/entryType resolve.
  let documentNameLabel = $derived(
    metadataSchema && entryType ? effectiveFieldLabel(metadataSchema, entryType, "title") : "Title",
  );
  // structure_node has no schema kind of its own — Acts/Chapters share
  // kind="manuscript" in the metadata schema. Reuse the manuscript entry types so
  // the type selector still lists Act/Chapter/Scene/etc.
  // The entry-type control's options. For most kinds `documentKind` IS the schema
  // kind, so we list that kind's concrete sub-types (a switchable variant set —
  // prompt:base ↔ prompt:roleplay). Two kinds don't line up 1:1: `structure_node`
  // is a scene, and `plot_template`'s schema kind is `plot` — but plot's other
  // entry_types (plotline, board) are DISTINCT node classes, not interchangeable
  // variants, so a template offers only its own type (never a reclassify), and
  // showing it also fixes the otherwise-blank select (S4c finding #2).
  // The plot document kinds are synthetic shapes whose schema `kind` is "plot", not
  // their documentKind — so the kind-filter below finds nothing and the type select
  // falls back to the raw entry_type id ("plot:template_instance") instead of a name.
  // List just the node's own type: the plot classes (card / template / plotline) are
  // distinct, so a cross-class reclassify is never offered (the #720 call, now
  // generalized past plot_template). A plotline is edited on its board node by default,
  // but can also be opened in a full pane (ADR-0053 §3, the escape hatch) — same rule.
  const OWN_TYPE_ONLY = new Set(["plot_template", "plot_card", "plotline"]);
  let documentEntryTypes = $derived(
    OWN_TYPE_ONLY.has(documentKind)
      ? Object.entries(metadataSchema?.entry_types ?? {}).filter(([typeId]) => typeId === entryType)
      : Object.entries(metadataSchema?.entry_types ?? {}).filter(
          ([, definition]) => definition.kind === (documentKind === "structure_node" ? "manuscript" : documentKind) && !definition.abstract,
        ),
  );
  let activeEntryType = $derived(metadataSchema?.entry_types[entryType] ?? metadataSchema?.entry_types[defaultEntryType()]);
  // Svelte 5 reactivity trap ([[feedback-svelte5-reactivity-traps]]):
  // chaining `$: a = ...activeEntryType...` after `$: activeEntryType =
  // ...` doesn't reliably refresh `a` when entryType changes — the
  // effect that writes activeEntryType and the effect that reads it
  // race during legacy_pre_effect scheduling, and `metadataFieldIds`
  // can end up frozen on the entry type the component first mounted
  // with (typically "scene"). Resolving the entry type INLINE from
  // metadataSchema + entryType in one effect avoids the chain.
  // Resolved INLINE from (metadataSchema, entryType) rather than chained
  // through `activeEntryType`. Svelte 5's legacy reactivity raced on the
  // chained derivation and metadataFieldIds could end up frozen on the
  // entry-type the component first mounted with. The single derivation
  // tracks both deps explicitly.
  //
  // `color` is no longer filtered (ADR-0029 §G): the color-row hoist is gone,
  // so color flows through the generic rail loop like any field and renders at
  // its display_order slot via MetadataPanel's `type === "color"` branch.
  let metadataFieldIds = $derived((metadataSchema?.entry_types[entryType] ?? metadataSchema?.entry_types[defaultEntryType()])?.fields ?? []);
  // ADR-0079: this node's resolved narration cascade, looked up client-side from
  // the manuscript tree the rail already holds (no read_scene change). A manuscript
  // node's backing-file id IS its scene_id, so one lookup serves scenes and
  // act/chapter containers alike.
  let resolvedCascade = $derived(
    scene?.id && structure ? (findNodeBySceneId(structure.root, scene.id)?.resolved_cascade ?? null) : null,
  );
  let hasBody = $derived(bodyShape !== "none");
  // Shared by the rail and Body Sections (#2009) — one node, one read-only verdict.
  let editorReadOnly = $derived(scrubbed || snapshotParked || reviewing || (inheritedReadOnly && documentKind !== "prompt"));
  // #2074 (ADR-0042 §5): the scrub stop's own unit — the stop IS the unit, so
  // editing the lore card at a stop edits this. Threaded into EditorBodyHost's
  // model; `null` off the lore axis or at base (stop 0, editable already).
  let stopUnit = $derived(scrubbed ? (scrub.units[scrub.index - 1] ?? null) : null);
  // The foot dock's caption reads "editing this stop" when the OPEN list tab
  // is a reference-keyed list AND this stop's unit touches the open node —
  // the same predicate EditorBodyHost's list-tab block applies to its own
  // readOnly/change routing (no shared model between the two renderers).
  let stopListFieldId = $derived(activeBodyTab.startsWith("list:") ? activeBodyTab.slice(5) : null);
  let stopEditable = $derived(
    scrubbed &&
      stopListFieldId !== null &&
      keyedListKeyMember(metadataSchema?.fields[stopListFieldId]) !== null &&
      (stopUnit?.records.some((r) => r.entity_id === scene?.id) ?? false),
  );
  $effect.pre(() => {
    if (titleReload && titleReload.token !== lastTitleReloadToken) {
      lastTitleReloadToken = titleReload.token;
      title = titleReload.title;
    }
  });
  // Re-source backlinks when the open node changes or the reverse index rebuilds
  // (a referrer was saved/deleted) — reading the index also closes the open-during
  // -initial-load race the old one-shot fetch had.
  $effect.pre(() => {
    const anchorId = sceneId;
    const referenceIndex = $referenceIndexStore;
    if (anchorId) {
      void refreshBacklinks(anchorId, referenceIndex);
    } else if (lastBacklinksSceneId !== null) {
      lastBacklinksSceneId = null;
      backlinks = [];
    }
  });
</script>

<!-- Metadata + backlinks, rendered into either the side rail (prose/code/
     chat), the whole pane (none-shape), or — as front matter + appendix
     (#2054) — the document. Defined once as a snippet so the long prop list
     isn't duplicated across the host slots; `part` picks the slice. -->
{#snippet metaContent(part: "rail" | "facts" | "trailing" = "rail")}
  <EditorRailContent
    {part}
    model={{
      metadataSchema, entryType, status, metadata, documentKind, documentLabel,
      documentEntryTypes, metadataFieldIds, scene, createLayerId, overriddenFieldsForPanel,
      scrubbed, scrub, compare: snapshotCompare ?? entryCompare, editorReadOnly, bodyShape,
      resolvedCascade, backlinks, title, hostPaneId,
    }}
    deps={{ loreEntries, promptEntries, structure, researchStructure, implicitContextMatcher, sectionRegistry, computedFieldString }}
    on={{
      entryTypeChange: (next) => updateEntryType(next),
      statusChange: (next) => updateStatus(next),
      metadataChange: (next) => { metadata = next; emitChange(); },
      customData: () => onCustomData?.({ entryType, kind: documentKind }),
      navigate: (payload) => onNavigate?.(payload),
      resetField: (fieldId) => onResetField?.(fieldId),
      goToSection: (fieldId) => sectionRegistry.focus(fieldId),
      goToList: (fieldId) => setBodyTab(`list:${fieldId}`),
      park: () => { void snapshots.park(null); },
    }}
  />
{/snippet}

<!-- The detached Details pane renders the SAME `metaContent`; this thin wrapper
     adapts its signature to the region body contract (`ViewSpec` arg, which
     metadata ignores) and supplies the scroll container the docked rail's
     `.rail-scroll` gives it — without it the pane clips tall metadata with no
     scrollbar (#1258 follow-up). -->
{#snippet detailsPaneBody(_spec: ViewSpec | undefined)}
  <div class="details-pane-scroll">{@render metaContent()}</div>
{/snippet}

<!-- The document blocks (#2054): the rail's facts above the body, its trailing
     material after it. EditorBodyHost mounts them inside the prose frame and
     the read-only overlay; null while the rail is open. -->
{#snippet frontMatter()}{@render metaContent("facts")}{/snippet}
{#snippet appendix()}{@render metaContent("trailing")}{/snippet}

<!-- Register the detached pane's content while Details is torn out (#1258). A
     fresh registrar mounts on detach and tears down on reattach — same shape as
     CodeBodyView's sub-tab registration. -->
{#if detailsDetached && detailsPaneId}
  <RegionRegistrar
    regions={{
      [detailsPaneId]: {
        title: "Details",
        body: detailsPaneBody,
        closable: true,
        onClose: reattachDetails,
      },
    }}
  />
{/if}

<!-- The five title-input variants, in ONE place. Two renderers: the non-chat
     header wraps this in the `.title-label` (with the eyebrow); the chat body
     renders it bare on its one row (ADR-0076 S6 — the chat title sits with the
     setup chips, no eyebrow). Each input carries its own `aria-label`, so it
     needs no label wrapper. State/persistence stay entirely in NodeEditor. -->
{#snippet chatTitleField()}
  {#if scrubbed}
    <!-- Effective title as of the scrub point — read-only; the draft
         title stays untouched underneath (stop 0 restores it). -->
    <input class="title-input" class:mutated={titleMutated} readonly aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()} (effective, read-only)`} value={effectiveTitle} />
  {:else if snapshotParked}
    <!-- Parked: the title flips with the body and the rail, and is
         read-only like them. Leaving it editable let an author type
         into a document they were not looking at. -->
    <input
      class="title-input"
      class:flipped={snapshots.titleDiffers}
      class:flip-was={snapshots.titleDiffers && snapshots.view === "was"}
      readonly
      aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()} (snapshot, read-only)`}
      value={snapshots.titleForView}
    />
  {:else if reviewing}
    <!-- Frozen for AI review (#634): read-only like the parked/scrubbed
         title, so the author can't edit an entry mid-review — the review
         is a transaction that writes once, not a co-editing surface. -->
    <input class="title-input" readonly aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()} (under review, read-only)`} value={title} />
  {:else if inheritedReadOnly}
    <!-- Inherited prompt (ADR-0049 Library or an ancestor project, #676):
         read-only in place. The title cannot be renamed here; clone it
         to edit. -->
    <input class="title-input" readonly aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()} (inherited, read-only)`} value={title} />
  {:else}
    <input class="title-input" aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()}`} placeholder={documentNameLabel} bind:value={title} oninput={handleTitleInput} />
  {/if}
{/snippet}

<div
  class="editor-panel"
  class:body-hidden={bodyShape === "none"}
  class:waiting={snapshots.slow}
  class:has-rail={scene && !railIsPane}
  class:rail-right={scene && !railIsPane && railSide === "right"}
  class:rail-bottom={scene && !railIsPane && railSide === "bottom"}
>
  <!-- Header + body regions (#2029 split); `{ model, deps, on }` per RailFieldRow. -->
  <EditorHeader
    model={{
      scene, documentKind, bodyShape, documentNameLabel, titleMutated, hasInteriorityBeats,
      interiorityRevealed, liveWordCount, characterCostRowsView, lastInvocationCostUsd,
      sceneSessionCostUsd, rollupCostKind, todoStatusHint, authoringLayerId, recentlySaved, chatTitleField,
      tabs: bodyTabs, activeBodyTab,
    }}
    on={{
      toggleInteriority: () => bodyHost?.toggleInteriority(), authoringLayerChange: onAuthoringLayerChange,
      selectBodyTab: setBodyTab,
    }}
  />
  <EditorBodyHost
    bind:this={bodyHost}
    model={{
      scene, documentKind, bodyShape, rawBodyLanguage, loadedSceneId, entryType, metadata,
      metadataSchema, editorReadOnly, inheritedReadOnly, reviewing, scrubbed, snapshotParked,
      overlayBodyHtml, snapshotRibbon, scrub, snapshots, entryReview, detailsDetached, chatTitleField, metaContent,
      stopUnit,
      frontMatter: frontMatterMode ? frontMatter : undefined, appendix: frontMatterMode ? appendix : undefined,
      activeBodyTab, createLayerId,
    }}
    deps={{
      loreEntries, promptEntries, assistantEntries, availableScenes, structure, researchStructure,
      implicitContextMatcher, defaultAssistantId, documentLabel, hostPaneId, sectionRegistry, promptDrafts,
    }}
    on={{
      change: emitChange, focus: () => onFocus?.(), openChat: (payload) => onOpenChat?.(payload),
      requestInputsDialog: (payload) => promptDialog?.open(payload),
      metadataChange: (next) => { metadata = next; emitChange(); }, viewSaveState: (state) => onViewSaveState?.(state),
      navigate: (payload) => onNavigate?.(payload),
    }}
    bind:rawBody bind:offerOnDraft bind:contextStrategyDraft bind:liveWordCount bind:editorEmpty
    bind:hasInteriorityBeats bind:interiorityRevealed bind:lastInvocationCostUsd bind:sceneSessionCostUsd bind:characterCostUsd
  />

  {#if scene && metadataSchema && !railIsPane}
    <EditorRail
      bind:open={railOpen}
      label={`${documentLabel} details`}
      content={metaContent}
      detached={detailsDetached}
      onDetach={canDetachDetails ? detachDetails : undefined}
      onReattach={reattachDetails}
    />
  {/if}

  <!-- Foot-docked: the lore card's two time-axes share ONE dock (ADR-0088 S2).
       For a scene, or a lore entry with no mutations, FootDock degrades to
       exactly ADR-0044's snapshot strip with no mode control. Gated on a prose
       body: the read-only compare overlay is prose. -->
  {#if (documentKind === "manuscript" || documentKind === "lore") && scene && bodyShape === "prose"}
    <FootDock {snapshots} {scrub} {documentKind} writesLabel={snapshotWritesLabel} {stopEditable} />
  {/if}

  <footer class="status">
    {#if scene}
      {dirty ? "Unsaved changes" : `Loaded ${scene.title}`}
    {:else}
      No scene open
    {/if}
  </footer>
</div>

<!-- The prompt-invocation modal (#631). Rendered unconditionally: it shows
     nothing until the host opens it via `promptDialog.open(...)` (routed from
     ProseBodyView's request-inputs-dialog). Submit forwards to ProseBodyView,
     which owns the AI streaming machinery. -->
<PromptInvocationDialog
  bind:this={promptDialog}
  {scene}
  {assistantEntries}
  {defaultAssistantId}
  {structure}
  {researchStructure}
  {loreEntries}
  {promptEntries}
  {implicitContextMatcher}
  onRun={async (entry, values, assistantId) => {
    await bodyHost?.runPromptEntryWithInputsExternal(entry, values, assistantId);
  }}
/>

<style>
  /* NodeEditor shell UI (metadata RAIL, editor header/title, cost-chip hint
     row), co-located from styles.css (#14). Own Svelte-template DOM → scoped,
     no :global. The shared editor-content layer (.editor-body* prose/table +
     marks) and pane chrome (.editor-pane/.pane*) stay global. */

  /* Editor-panel grid + rail placement (body-spec Section A). When the rail is
     present the panel is a two-column grid: header/body/footer stack in column
     1, the recessed rail spans all rows in column 2. `> :global(*)` pins EVERY
     direct child to column 1 — the body views (CodeBodyView/ProseBodyView/…)
     are child components, so a scoped `> *` would miss them; the own
     `.editor-rail`/`.rail-tab` overrides (scoped, higher specificity) reclaim
     column 2. */
  .editor-panel {
    display: grid;
    /* A prompt-preview pane adds auto-sized rows (resize handle + preview)
       between the 1fr editor row and the auto footer. */
    grid-template-rows: auto 1fr auto;
    grid-auto-rows: auto;
    min-width: 0;
    min-height: 0;
    background: var(--surface);
  }

  .editor-panel.body-hidden {
    display: flex;
    flex-direction: column;
  }

  /* The pointer is as likely to be over the prose as over the strip, so the
     wait cursor covers the whole pane (SnapshotStrip owns the threshold). */
  .editor-panel.waiting,
  .editor-panel.waiting * {
    cursor: progress;
  }

  /* Right dock: two columns. Header/body/footer stack in column 1; the recessed
     rail spans all rows in column 2. `> :global(*)` pins EVERY direct child to
     column 1 (body views are child components, so a scoped `> *` would miss
     them); the `.editor-rail`/`.rail-tab` overrides reclaim column 2. `:global()`
     adds no specificity, so those still outrank the `> *` rule. */
  .editor-panel.has-rail.rail-right {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .editor-panel.has-rail.rail-right > :global(*) {
    grid-column: 1;
    min-width: 0;
  }
  .editor-panel.has-rail.rail-right > :global(.editor-rail),
  .editor-panel.has-rail.rail-right > :global(.rail-tab) {
    grid-column: 2;
    grid-row: 1 / -1;
  }

  /* Bottom dock (#1246): a single column. The rail flows as a full-width row in
     its DOM position (after the body views, above the footer), so long-text
     fields get the whole editor width. No column pinning needed. */
  .editor-panel.has-rail.rail-bottom {
    grid-template-columns: minmax(0, 1fr);
  }
  .editor-panel.has-rail.rail-bottom > :global(*) {
    min-width: 0;
  }

  /* Detached Details pane (#1258): the scroll container the docked rail's
     `.rail-scroll` supplies, so tall metadata scrolls instead of clipping. */
  .details-pane-scroll {
    height: 100%;
    overflow: auto;
    overscroll-behavior: contain;
  }

  .title-input[readonly] {
    background: var(--inset);
    cursor: default;
  }
  /* The same two colours as the body and the rail — one vocabulary, and never a
     glyph (§J). Two rules rather than one with a variable, so a state class
     cannot silently outrank an identity class for a single property. */
  .title-input.flipped {
    color: var(--diff-now);
    font-weight: 600;
    box-shadow: inset 0 -2px 0 var(--diff-now-edge);
  }
  /* Dotted, matching the body and the rail — the greyscale channel is shape. */
  .title-input.flipped.flip-was {
    color: var(--diff-was);
    box-shadow: none;
    background-image: repeating-linear-gradient(
      to right,
      var(--diff-was-edge) 0 3px,
      transparent 3px 6px
    );
    background-repeat: no-repeat;
    background-position: 0 100%;
    background-size: 100% 2px;
  }
  .title-input.mutated {
    color: var(--mutation-color);
    font-weight: 600;
  }

  .title-input {
    border: 0;
    border-bottom: 1px solid var(--divider);
    border-radius: 0;
    font-family: var(--serif);
    font-size: var(--fs-2xl);
    font-weight: 700;
    padding-left: 0;
  }

  .title-input:focus {
    border-bottom-color: var(--accent);
    outline: none;
  }
</style>
