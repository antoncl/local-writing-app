<script lang="ts">

  import BacklinksPanel from "@/components/editor/BacklinksPanel.svelte";
  import MutationTimeline from "@/components/editor/MutationTimeline.svelte";
  import MutationScrubber from "@/components/editor/MutationScrubber.svelte";
  import SnapshotStrip from "@/components/editor/SnapshotStrip.svelte";
  import EditorRail from "@/components/editor/EditorRail.svelte";
  import ReadOnlyBodyOverlay from "@/components/editor/body/ReadOnlyBodyOverlay.svelte";
  import EntryRevisionReview from "@/components/editor/body/EntryRevisionReview.svelte";
  import ReplaceReviewCard from "@/components/editor/body/ReplaceReviewCard.svelte";
  import ConversationsPanel from "@/components/editor/ConversationsPanel.svelte";
  import { LoreScrubController } from "@/lib/stores/loreScrub.svelte";
  import { EntryProposalController } from "@/lib/stores/entryProposal.svelte";
  import { SnapshotStripController } from "@/lib/stores/snapshotStrip.svelte";
  import { implicitContextFor } from "@/lib/stores/implicitContext.svelte";
  import { notchWhen } from "@/lib/utils/snapshotTime";
  import MetadataPanel from "@/components/editor/MetadataPanel.svelte";
  import PromptInvocationDialog from "@/components/editor/PromptInvocationDialog.svelte";
  import FieldsOnlyView from "@/components/editor/body/FieldsOnlyView.svelte";
  import CodeBodyView from "@/components/editor/body/CodeBodyView.svelte";
  import ProseBodyView from "@/components/editor/body/ProseBodyView.svelte";
  import ChatBodyView from "@/components/editor/body/ChatBodyView.svelte";
  import ViewBodyView from "@/components/editor/body/ViewBodyView.svelte";
  import { PromptInputDraftsController } from "@/lib/stores/promptInputDrafts.svelte";
  import { formatCostEur } from "@/lib/utils/money";
  import { sceneMarkdownToHtml } from "@/lib/utils/markdown";
  import { resolveColor } from "@/lib/utils/colors";
  import type { AssistantEntrySummary, Backlink, BodyShape, DocumentKind, EditableDocument, EntryBodyLanguage, EntryMetadata, EntryTypeDefinition, MetadataSchema, PromptEntrySummary, PromptInputDefinition } from "@/lib/types";
  import type { ViewSaveState } from "@/lib/editor-core/editorPaneModel";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { readOnlyInPlace } from "@/lib/utils/provenance";
  import LayerAuthoringBar from "@/components/editor/LayerAuthoringBar.svelte";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { backlinksFor } from "@/lib/views/backlinks";
  import { effectiveFieldLabel } from "@/lib/utils/schemaTypeHelpers";
  import { mutationsVersion } from "@/lib/stores/mutationsVersion.svelte";

  // Effective body shape for an entry type. Falls back through the
  // legacy has_body / body_editor pair when body_shape is absent
  // (existing on-disk schemas don't carry it). See
  // decisions-node-editor-modularization + decisions-node-editor-body-spec.
  export function deriveBodyShape(def: EntryTypeDefinition | null | undefined): BodyShape {
    if (def?.body_shape) return def.body_shape;
    if (def?.has_body === false) return "none";
    if (def?.body_editor === "code") return "code";
    return "prose";
  }

  // Data sources for context_pick inputs in the prompt preview / inputs
  
  // Research tree, sibling to manuscript `structure`. Threaded through to
  // the context picker so context_pick / entity_ref fields can target
  
  // Optional matcher pass-through for the implicit-context highlight
  
  // Scenes available for the inline prompt-preview scene picker. The pane is
  

  // Outbound events as callback props (#14: App is now runes — components can't
  // use on:event). NodeEditor stays legacy; these replace its dispatcher. Its
  
  interface Props {
    scene?: EditableDocument | null;
    documentKind?: DocumentKind;
    promptEntries?: PromptEntrySummary[];
    // dialog. Optional — the picker degrades to "no items" when missing.
    structure?: import("@/lib/types").StructureDocument | null;
    // research notes.
    researchStructure?: import("@/lib/types").StructureDocument | null;
    loreEntries?: import("@/lib/types").LoreEntrySummary[];
    knownTags?: import("@/lib/types").ScopedTag[];
    tagOrigin?: "project" | "assistant";
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
    onChange?: ((payload: { title: string; body: string; status: string; entryType: string; metadata: EntryMetadata; inputs?: PromptInputDefinition[] }) => void) | undefined;
    onFocus?: (() => void) | undefined;
    onCustomData?: ((payload: { entryType: string; kind: DocumentKind }) => void) | undefined;
    onNavigate?: ((payload: { id: string; kind: string }) => void) | undefined;
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
    documentKind = "scene",
    promptEntries = [],
    structure = null,
    researchStructure = null,
    loreEntries = [],
    knownTags = [],
    tagOrigin = "project",
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
    onReviewFreeze = undefined,
    onFlushReviewCommit = undefined
  }: Props = $props();


  let proseBodyView: ProseBodyView | null = $state(null);
  let chatBodyView: ChatBodyView | null = $state(null);
  let viewBodyView: ViewBodyView | null = $state(null);
  let loadedSceneId: string | null = $state(null);
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
    const id = documentKind === "lore" ? (scene?.id ?? null) : null;
    void mutationsVersion.value;
    return scrub.load(id);
  });

  // ---- Snapshot strip (#401, ADR-0044) --------------------------------------
  // The same shape as the scrub above, on the real-time axis: `parked` flips
  // the body to a read-only overlay while the TipTap buffer stays mounted and
  // hidden underneath. Scenes only — ADR-0043's v1 is scenes, and putting a
  // third axis on a lore card is exactly the L-not-a-grid problem ADR-0042 had
  // to settle.
  const snapshots = new SnapshotStripController();
  let snapshotParked = $derived(documentKind === "scene" && snapshots.parked !== null);

  $effect(() => {
    snapshots.flushScene = onFlushScene ?? null;
    snapshots.onRestored = onSceneRestored ?? null;
    // Adopting a region writes only the prose, through the hidden buffer restore
    // already owns — so it goes straight to the view, not back through the
    // server (ADR-0044 Amendment 4). Evaluated at call time, like `readLive`.
    snapshots.onAdopt = (body) => proseBodyView?.adoptBody(body);
    // What the diff compares against: the BUFFER, not the file. Autosave lags
    // by up to six seconds, so the file is not reliably what the author is
    // looking at — and parking is a reading gesture, so flushing to make it
    // current would make reading write (ADR-0044 §G).
    snapshots.readLive = () => ({
      body: proseBodyView?.getBody() ?? scene?.body ?? "",
      title,
      status,
      metadata,
      // The *now* side of the witness's dynamic axis (#439) — the same hits
      // the author sees underlined, not a rescan.
      dynamic_context: scene?.id ? implicitContextFor(scene.id) : undefined,
    });
    return snapshots.load(documentKind === "scene" ? (scene?.id ?? null) : null);
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
    const markdown = overrideBody ?? proseBodyView?.getBody() ?? scene?.body ?? "";
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

  type CharacterCostRow = { id: string; title: string; cost: number; color: string };

  function characterCostRows(
    map: Record<string, number>,
    lore: typeof loreEntries,
    schema: MetadataSchema | null,
  ): CharacterCostRow[] {
    const rows: CharacterCostRow[] = [];
    for (const [id, cost] of Object.entries(map)) {
      if (typeof cost !== "number" || cost <= 0) continue;
      const entry = lore.find((e) => e.id === id);
      const title = entry?.title || id;
      const instance =
        entry && typeof entry.metadata?.color === "string"
          ? (entry.metadata.color as string)
          : null;
      const swatch = resolveColor(instance, entry?.entry_type, "lore", schema);
      let color: string;
      if (swatch) {
        color = swatch.hex;
      } else {
        let hash = 0;
        for (let i = 0; i < id.length; i++) {
          hash = (hash * 31 + id.charCodeAt(i)) | 0;
        }
        const hue = ((hash % 360) + 360) % 360;
        color = `hsl(${hue}, 62%, 48%)`;
      }
      rows.push({ id, title, cost, color });
    }
    rows.sort((a, b) => b.cost - a.cost);
    return rows;
  }

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
    if (documentKind === "chat") chatBodyView?.setTitleFromPane(title);
    if (documentKind === "view") viewBodyView?.setTitleFromPane(title);
  }

  function emitChange() {
    if (!scene) return;
    onChange?.({
      title,
      body: rawBodyMode ? rawBody : (proseBodyView?.getBody() ?? ""),
      status,
      entryType,
      metadata: cloneMetadata(metadata),
      inputs: documentKind === "prompt" ? promptDrafts.toCanonical() : undefined,
    });
  }

  function cloneMetadata(value: EntryMetadata) {
    return JSON.parse(JSON.stringify(value ?? {})) as EntryMetadata;
  }

  function metadataEqual(left: EntryMetadata, right: EntryMetadata) {
    return JSON.stringify(left ?? {}) === JSON.stringify(right ?? {});
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
    if (documentKind === "lore") return "lore:lore_note";
    if (documentKind === "chat") return "chat:chat_session";
    return "scene:scene";
  }

  function defaultStatus() {
    return documentKind === "scene" ? "draft" : "";
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
  // controller is kind-agnostic; the host's participation policy is `patchLoopKind`.
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
  entryReview.onAdoptFields = (fields) => {
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
    metadata = { ...metadata, ...next };
  };
  entryReview.onAdoptBody = (body) => proseBodyView?.adoptBody(body);
  entryReview.onEmitChange = emitChange;
  entryReview.readCurrentBody = () => proseBodyView?.getBody() ?? scene?.body ?? "";
  // The one explicit post that ends a commit — the pane controller cancels the
  // (frozen) timer and PUTs once (body + metadata together).
  entryReview.onFlush = () => {
    if (scene?.id) return onFlushReviewCommit?.(scene.id);
  };

  // ADR-0048 §5 — the host's SINGLE gate for which kinds take part in the
  // entry-patch loop: the freeze, launcher, and review overlay below all read it,
  // so they can't drift (a review over an un-frozen pane moves the diff base,
  // #634). Controller/store are kind-agnostic; widen per-kind here. Lore, plot
  // cards (ADR-0048 S8b), and scenes (ADR-0051 S5-next) all run the entry-patch
  // loop: a card brainstorm patches its `plot:card`, a scene's "Summarize scene"
  // patches its `summary` field (review in `replace` mode; see the overlay). The
  // Conversations ＋New menu filters to the prompts each kind's node admits (see
  // ConversationsPanel).
  const patchLoopKind = $derived(
    documentKind === "lore" || documentKind === "scene" || documentKind === "plot_card",
  );
  // ADR-0051 S3/S5 — which kinds show the Conversations surface, and which prompt
  // surface the ＋New menu offers. A chat's `subject` is kind-neutral, so a scene
  // lists its chats (subject → scene) the same way a lore entry or plot card does.
  // All three now offer the `entry_patch` brainstorm surface (S5-next flipped
  // scenes off the empty `chat_panel` placeholder S5 shipped). The panel hides ＋New
  // when no prompt resolves to the surface AND admits this node's kind.
  const conversationsKind = $derived(
    documentKind === "lore" || documentKind === "scene" || documentKind === "plot_card",
  );
  const conversationsSurface = "entry_patch";
  // A node under an open brainstorm review is a frozen transaction (#634): the
  // rail/title go read-only and the host suppresses autosave, so the diff's
  // "current" side cannot move under the review.
  const reviewing = $derived(patchLoopKind && entryReview.hasReview);
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
  // unmounts. Idempotent on the host side; the flush-on-enter runs once.
  $effect(() => {
    const entryId = scene?.id;
    if (!entryId) return;
    onReviewFreeze?.(entryId, reviewing ? reviewCommitter : null);
    return () => onReviewFreeze?.(entryId, null);
  });
  // Reset accumulated review resolution whenever the proposal identity changes,
  // so a superseding commit starts clean instead of inheriting prior adoptions.
  $effect(() => {
    entryReview.proposal;
    entryReview.resetResolution();
  });

  // Editor-pane handle exports — forwarded to ProseBodyView and called by the
  // editorPanes controller via `editorPaneComponents[pane.id].xxx(...)`.
  // reloadScene re-seeds the TipTap doc from a server scene (the controller
  // calls it to reconcile an open pane after an out-of-band embedded-TODO
  // mutation, GH #45); highlightEmbeddedTodo scrolls to a marker.
  export function reloadScene(nextScene: EditableDocument) {
    return proseBodyView?.loadScene(nextScene);
  }

  export function highlightEmbeddedTodo(todoId: string) {
    proseBodyView?.highlightEmbeddedTodo(todoId);
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
      // edge-tab so the body owns full width; every other shape opens it.
      railOpen = nextBodyShape !== "chat" && nextBodyShape !== "view";
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
  $effect.pre(() => {
    if (rawBodyMode && rawBody !== lastEmittedRawBody) {
      lastEmittedRawBody = rawBody;
      emitChange();
    }
  });
  let railIsPane = $derived(bodyShape === "none");
  let characterCostRowsView = $derived(characterCostRows(characterCostUsd, loreEntries, metadataSchema));
  // All-time rollup costs surfaced as a single chip in the header hint.
  // character_cost lives on lore character entries, project_cost on the
  // project node — backend populates both via `computed_metadata`.
  // Trust the computed field as the surface contract; render only when
  // the kind matches and the number is non-zero.
  let rollupCostKind = $derived((() => {
    if (!scene) return null;
    const computed = scene.computed_metadata as Record<string, unknown> | undefined;
    if (documentKind === "lore" && typeof computed?.character_cost === "number" && computed.character_cost > 0) {
      return { kind: "character" as const, value: computed.character_cost as number };
    }
    if (documentKind === "project" && typeof computed?.project_cost === "number" && computed.project_cost > 0) {
      return { kind: "project" as const, value: computed.project_cost as number };
    }
    return null;
  })());
  $effect.pre(() => {
    promptDrafts.reseed(scene, documentKind);
  });
  // Friendly noun for this document kind — the type-header label ("<label> type"), the
  // rail's aria-label, the title aria-labels. A map, not a scene-defaulting ternary, so
  // every kind reads correctly: the plot kinds (card / plotline / arc / template) were
  // all mislabelled "Scene type" (#737 follow-on).
  const DOCUMENT_LABELS: Record<string, string> = {
    scene: "Scene",
    lore: "Entry",
    structure_node: "Node",
    chat: "Chat",
    research: "Note",
    prompt: "Prompt",
    assistant: "Assistant",
    view: "View",
    project: "Project",
    snippet: "Snippet",
    plot_card: "Card",
    plotline: "Plotline",
    plot_template: "Template",
  };
  let documentLabel = $derived(DOCUMENT_LABELS[documentKind] ?? "Scene");

  // Fields whose value comes from a layer override (#314), passed to the rail so
  // it can lead them with the `ti-versions` mark. The picker itself lives in
  // LayerAuthoringBar (kept out of this shell for the file-size cap).
  let overriddenFieldsForPanel = $derived(
    documentKind === "lore" && scene && "overridden_fields" in scene
      ? ((scene as import("@/lib/types").LoreEntry).overridden_fields ?? [])
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
  // kind="scene" in the metadata schema. Reuse the scene entry types so
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
  // List just the node's own type: the plot classes (card / template) are distinct, so
  // a cross-class reclassify is never offered (the #720 call, now generalized past
  // plot_template). Plotlines are edited on the board node, not in a pane (ADR-0053 §3).
  const OWN_TYPE_ONLY = new Set(["plot_template", "plot_card"]);
  let documentEntryTypes = $derived(
    OWN_TYPE_ONLY.has(documentKind)
      ? Object.entries(metadataSchema?.entry_types ?? {}).filter(([typeId]) => typeId === entryType)
      : Object.entries(metadataSchema?.entry_types ?? {}).filter(
          ([, definition]) => definition.kind === (documentKind === "structure_node" ? "scene" : documentKind) && !definition.abstract,
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
  let hasBody = $derived(bodyShape !== "none");
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
    const anchorId = scene?.id ?? null;
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
     chat) or the whole pane (none-shape). Defined once as a snippet so the
     long prop list isn't duplicated across the two host slots. -->
{#snippet metaContent()}
  {#if metadataSchema}
    <MetadataPanel
      entryType={entryType}
      status={status}
      metadata={metadata}
      documentKind={documentKind}
      documentLabel={documentLabel}
      documentEntryTypes={documentEntryTypes}
      metadataFieldIds={metadataFieldIds}
      knownTags={knownTags}
      tagOrigin={tagOrigin}
      loreEntries={loreEntries}
      promptEntries={promptEntries}
      structure={structure}
      researchStructure={researchStructure}
      implicitContextMatcher={implicitContextMatcher}
      excludeId={scene?.id ?? null}
      sourceLayerId={scene?.source_layer_id ?? null}
      sourceLayerLabel={scene?.source_layer_label ?? null}
      overriddenFields={overriddenFieldsForPanel}
      computedFieldString={computedFieldString}
      effectiveOverrides={scrubbed ? scrub.overrides : null}
      compare={snapshotCompare ?? entryCompare}
      readOnly={scrubbed || snapshotParked || reviewing || inheritedReadOnly}
      onEntryTypeChange={(next) => updateEntryType(next)}
      onStatusChange={(next) => updateStatus(next)}
      onMetadataChange={(next) => {
        metadata = next;
        emitChange();
      }}
      onCustomData={() => onCustomData?.({ entryType, kind: documentKind })}
      onNavigate={(payload) => onNavigate?.(payload)}
      onResetField={documentKind === "lore" ? onResetField : undefined}
    />
    {#key scene?.id ?? ""}
      <BacklinksPanel
        backlinks={backlinks}
        loreEntries={loreEntries}
        structure={structure}
        on:navigate={(event) => onNavigate?.(event.detail)}
      />
    {/key}
    {#if conversationsKind && scene?.id}
      <!-- The Conversations surface (ADR-0051 S3/S5): the chats about this node,
           resume-first, + a ＋New menu — the launcher that replaced the
           silent-spawn brainstorm verb. Mounted for lore entries and scenes
           alike (a scene lists chats whose subject → it). Keyed on the node id
           so its expand / menu state resets when the open node changes. -->
      {#key scene.id}
        <ConversationsPanel
          subjectId={scene.id}
          subjectTitle={title}
          subjectEntryType={entryType}
          newSurface={conversationsSurface}
          {promptEntries}
          {metadataSchema}
          {hostPaneId}
        />
      {/key}
    {/if}
    {#if documentKind === "lore" && scene?.id}
      <MutationTimeline
        units={scrub.units}
        activeIndex={scrub.index}
        onSelect={(index) => void scrub.scrubTo(index)}
        onNavigate={(payload) => onNavigate?.(payload)}
      />
    {/if}
  {/if}
{/snippet}


<div
  class="editor-panel"
  class:body-hidden={bodyShape === "none"}
  class:waiting={snapshots.slow}
  class:has-rail={scene && !railIsPane}
  class:rail-collapsed={scene && !railIsPane && !railOpen}
  class:rail-pane={scene && railIsPane}
>
  <section class="editor-header">
    {#if scene}
      <div class="scene-title-row">
        <label class="title-label">
          {documentNameLabel}{#if titleMutated}<span class="title-mutated-marker" title="Changed by here">⤳</span>{/if}
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
        </label>
      </div>
      <!-- Layer override authoring (#314 / ADR-0042): choose which level this
           inherited entry's edits write to. Renders only for an inherited lore
           entry; no-ops otherwise. -->
      <LayerAuthoringBar
        {scene}
        {documentKind}
        {authoringLayerId}
        {recentlySaved}
        {onAuthoringLayerChange}
      />
      {#if todoStatusHint || (documentKind === "scene" && (lastInvocationCostUsd != null || characterCostRowsView.length > 0)) || rollupCostKind}
        <div class="editor-hint">
          {#if todoStatusHint}
            <span class="editor-hint-text">{todoStatusHint}</span>
          {/if}
          {#if documentKind === "scene"}
            <div class="editor-hint-costs">
              {#each characterCostRowsView as row (row.id)}
                <span
                  class="character-cost-chip"
                  title={`Roleplay cost attributed to ${row.title} in this scene (all sessions).`}
                  style={`--character-color: ${row.color}`}
                >
                  <span class="character-cost-dot" aria-hidden="true"></span>
                  <span class="character-cost-name">{row.title}</span>
                  <span class="character-cost-amount">{formatCostEur(row.cost)}</span>
                </span>
              {/each}
              {#if lastInvocationCostUsd != null}
                <span class="continuation-cost-chip" title="Last continuation invocation cost · running total for this scene this session. Resets on reload or scene switch.">
                  last {formatCostEur(lastInvocationCostUsd)} · session {formatCostEur(sceneSessionCostUsd)}
                </span>
              {/if}
            </div>
          {:else if rollupCostKind}
            <div class="editor-hint-costs">
              <span
                class="node-rollup-cost-chip"
                title={rollupCostKind.kind === "character"
                  ? "All-time AI cost attributed to this character across every scene."
                  : "Whole-project AI cost across every invocation."}
              >
                {rollupCostKind.kind === "character" ? "character" : "project"} cost {formatCostEur(rollupCostKind.value)}
              </span>
            </div>
          {/if}
        </div>
      {/if}
    {:else}
      <h2>Select a scene</h2>
    {/if}
  </section>

  {#if bodyShape === "none"}
    {#if scene && metadataSchema}
      <div class="editor-pane-meta">
        {@render metaContent()}
      </div>
    {:else}
      <FieldsOnlyView />
    {/if}
  {/if}
  {#if bodyShape === "code"}
    <CodeBodyView
      bind:rawBody
      bind:entryInputDrafts={promptDrafts.drafts}
      {scene}
      {documentKind}
      {structure}
      {researchStructure}
      {loreEntries}
      {promptEntries}
      {availableScenes}
      {rawBodyLanguage}
      {loadedSceneId}
      nextInputDraftId={promptDrafts.nextDraftId}
      entrySlugify={promptDrafts.slugify}
      readOnly={inheritedReadOnly}
      onInputsChange={emitChange}
    />
  {/if}
  {#if bodyShape === "prose"}
    {#if scrubbed}
      <!-- The effective body as of the scrub point (§4.4). -->
      <ReadOnlyBodyOverlay
        html={overlayBodyHtml}
        label="Effective body (read-only)"
        ribbon={bodyMutated ? `Body as of ${scrub.units[scrub.index - 1]?.records[0]?.scene_path || "scene"} — mutated` : ""}
        ribbonMark="⤳"
      />
    {:else if snapshotParked}
      <!-- The parked snapshot, on the same overlay: the live buffer stays
           mounted and hidden underneath (ADR-0044 §G). -->
      <ReadOnlyBodyOverlay
        html={snapshots.bodyHtml}
        label="Snapshot body (read-only)"
        ribbon={snapshotRibbon}
        tone="snapshot"
        onRunClick={(regionId, kind) => snapshots.adopt(regionId, kind)}
      />
    {:else if patchLoopKind && entryReview.hasReview && entryReview.proposal}
      <!-- The brainstorm commit reviewed on the (frozen) node. Like the snapshot
           overlay, the live buffer stays mounted and hidden beneath; adopting
           writes through the same emitChange autosave (body + metadata in one
           PUT). Two review presentations, chosen by the launching prompt's
           `output.review` carried on the proposal (ADR-0051 S5-next). -->
      {#key entryReview.proposal}
        {#if entryReview.proposal.reviewMode === "replace"}
          <!-- `replace`: a whole-field swap (a scene summary regenerated from the
               body) — a plain current→proposed card, no run-diff (a regenerated
               value has no meaningful per-run diff). Replace adopts ONLY the shown
               long_text fields via `acceptFields` — never the body or a structured
               flip — so the write set equals what the card displays and a scene's
               prose can't be rewritten. -->
          <ReplaceReviewCard
            fields={entryReview.fields}
            onReplace={() => {
              entryReview.acceptFields();
              void entryReview.commit();
            }}
            onDiscard={() => entryReview.abandon()}
          />
        {:else}
          <!-- ADR-0046 slice 3: the per-run adopt flip (body + each long_text
               field), plus the structured rail flips and the A/S/B judge axis. -->
          <EntryRevisionReview
            currentBody={entryReview.currentBody()}
            proposedBody={entryReview.proposal.body}
            fields={entryReview.fields}
            hasChanges={entryReview.hasPendingChanges}
            view={entryReview.view}
            onView={(v) => entryReview.setView(v)}
            onToggleView={(v) => entryReview.toggleView(v)}
            onBodyResolved={(v) => entryReview.setBodyResolution(v)}
            onFieldResolved={(id, v) => entryReview.setFieldResolution(id, v)}
            onAcceptAll={() => {
              entryReview.acceptAll();
              void entryReview.commit();
            }}
            onDone={() => entryReview.commit()}
            onDiscard={() => entryReview.abandon()}
          />
        {/if}
      {/key}
    {/if}
    <div
      class="prose-body-host"
      class:hidden={scrubbed || snapshotParked || reviewing}
    >
      <ProseBodyView
        bind:this={proseBodyView}
      bind:liveWordCount
      bind:editorEmpty
      bind:lastInvocationCostUsd
      bind:sceneSessionCostUsd
      bind:characterCostUsd
      {scene}
      {documentKind}
      {loreEntries}
      {promptEntries}
      {availableScenes}
      {implicitContextMatcher}
      {documentLabel}
      onBodyChange={emitChange}
      onFocus={() => onFocus?.()}
      onOpenChat={(payload) => onOpenChat?.(payload)}
      onRequestInputsDialog={(payload) => promptDialog?.open(payload)}
      />
    </div>
  {/if}
  {#if bodyShape === "chat"}
    <ChatBodyView
      bind:this={chatBodyView}
      {scene}
      {promptEntries}
      {assistantEntries}
      {loreEntries}
      {structure}
      {researchStructure}
      {defaultAssistantId}
      {implicitContextMatcher}
      onBodyChange={emitChange}
      onFocus={() => onFocus?.()}
    />
  {/if}
  {#if bodyShape === "view"}
    <ViewBodyView
      bind:this={viewBodyView}
      {scene}
      {loreEntries}
      {promptEntries}
      {assistantEntries}
      {structure}
      {researchStructure}
      onBodyChange={emitChange}
      onFocus={() => onFocus?.()}
      onSaveState={(state) => onViewSaveState?.(state)}
    />
  {/if}

  {#if scene && metadataSchema && !railIsPane}
    <EditorRail bind:open={railOpen} label={`${documentLabel} details`} content={metaContent} />
  {/if}

  {#if documentKind === "lore" && scene && scrub.units.length > 0}
    <MutationScrubber units={scrub.units} index={scrub.index} onScrub={(index) => void scrub.scrubTo(index)} />
  {/if}

  <!-- Foot-docked, and only on scenes: the scrubber's slot is free here, so
       there is no competition for the dock and no mode to collide with. -->
  {#if documentKind === "scene" && scene && bodyShape === "prose"}
    <SnapshotStrip strip={snapshots} />
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
    await proseBodyView?.runPromptEntryWithInputsExternal(entry, values, assistantId);
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

  .editor-panel.has-rail {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .editor-panel.has-rail > :global(*) {
    grid-column: 1;
    min-width: 0;
  }
  /* `:global` because these elements belong to `EditorRail` now. The placement
     rule stays here, with the grid that defines the columns — the parent owns
     where its children sit. `:global()` adds no specificity, so this still
     outranks the `> *` rule above exactly as it did. */
  .editor-panel.has-rail > :global(.editor-rail),
  .editor-panel.has-rail > :global(.rail-tab) {
    grid-column: 2;
    grid-row: 1 / -1;
  }

  /* none-shape: the rail IS the pane (assistant / project / structure_node). */
  .editor-pane-meta {
    flex: 1 1 auto;
    min-height: 0;
    overflow: auto;
    overscroll-behavior: contain;
    padding: 18px 0;
  }

  .editor-header {
    display: grid;
    gap: 6px;
    padding: 12px 22px 6px;
    border-bottom: 1px solid var(--divider);
    background: var(--surface);
  }

  .scene-title-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 4px 8px;
    align-items: center;
  }

  /* ---- Time-travel overlay chrome (#64) ---------------------------------- */
  /* Keeps ProseBodyView a direct grid child of .editor-panel when visible;
     display:none while scrubbed preserves the mounted TipTap buffer. */
  .prose-body-host {
    display: contents;
  }
  .prose-body-host.hidden {
    display: none;
  }

  .title-mutated-marker {
    margin-left: 4px;
    color: var(--mutation-color);
    font-weight: 700;
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

  .title-label {
    display: grid;
    gap: 3px;
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 700;
    text-transform: uppercase;
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

  .editor-hint-text {
    flex: 1 1 auto;
    min-width: 0;
  }

  /* Per-scene continuation cost rollup. Frontend-only — resets on reload
     / scene switch. Sits in the trailing cost cluster on the footer hint
     row. Phase C added the persisted ai_invocations log; this chip stays
     as the session/last-call view, and `character-cost-chip` carries the
     per-character all-time totals from the log. */
  .continuation-cost-chip {
    color: var(--text-3);
    font-size: var(--fs-xs);
    white-space: nowrap;
    cursor: default;
    flex: 0 0 auto;
  }

  /* Single-value rollup chip for character_cost / project_cost (lore
     character entries and the project node respectively). Same muted
     tone as the scene cost chips so the editor hint row stays calm. */
  .node-rollup-cost-chip {
    color: var(--text-3);
    font-size: var(--fs-xs);
    white-space: nowrap;
    cursor: default;
    flex: 0 0 auto;
    font-variant-numeric: tabular-nums;
  }

  /* Trailing cluster on the editor footer hint row. Holds the
     per-character roleplay-cost chips and the continuation chip. */
  .editor-hint-costs {
    display: flex;
    align-items: baseline;
    gap: 8px;
    flex-wrap: wrap;
    justify-content: flex-end;
    flex: 0 1 auto;
    min-width: 0;
  }

  /* Per-character cost chip — colored dot + character name + cost.
     Backed by the persisted ai_invocations log; character color resolves
     from the lore entry (or a deterministic hue when unset). */
  .character-cost-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: var(--fs-xs);
    color: var(--text-3);
    white-space: nowrap;
    cursor: default;
  }

  .character-cost-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--character-color, var(--text-3));
    flex: 0 0 auto;
  }

  .character-cost-name {
    color: var(--text);
  }

  .character-cost-amount {
    font-variant-numeric: tabular-nums;
  }
</style>
