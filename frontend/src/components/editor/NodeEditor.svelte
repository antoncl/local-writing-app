<script lang="ts">

  import BacklinksPanel from "@/components/editor/BacklinksPanel.svelte";
  import MutationTimeline from "@/components/editor/MutationTimeline.svelte";
  import MutationScrubber from "@/components/editor/MutationScrubber.svelte";
  import { LoreScrubController } from "@/lib/stores/loreScrub.svelte";
  import MetadataPanel from "@/components/editor/MetadataPanel.svelte";
  import InputsDialog from "@/components/editor/InputsDialog.svelte";
  import FieldsOnlyView from "@/components/editor/body/FieldsOnlyView.svelte";
  import CodeBodyView from "@/components/editor/body/CodeBodyView.svelte";
  import ProseBodyView from "@/components/editor/body/ProseBodyView.svelte";
  import ChatBodyView from "@/components/editor/body/ChatBodyView.svelte";
  import ViewBodyView from "@/components/editor/body/ViewBodyView.svelte";
  import { coerceInputValue, type EntryInputDraft } from "@/lib/utils/promptInputs";
  import { resolutionSceneIdFromInputs } from "@/lib/editor-core/promptResolution";
  import { api } from "@/lib/api";
  import { formatCostEur } from "@/lib/utils/money";
  import { sceneMarkdownToHtml } from "@/lib/utils/markdown";
  import { resolveColor } from "@/lib/utils/colors";
  import type { AssistantEntrySummary, Backlink, BodyShape, DocumentKind, EditableDocument, EntryBodyLanguage, EntryMetadata, EntryTypeDefinition, MetadataFieldDefinition, MetadataSchema, PromptEntrySummary, PromptInputDefinition } from "@/lib/types";
  import { metadataSchemaStore } from "@/lib/stores/schema";
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
    // plugin on long-text metadata fields. App.svelte owns the compile.
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    assistantEntries?: AssistantEntrySummary[];
    defaultAssistantId?: string;
    // host-agnostic — App.svelte derives this from its structure tree.
    availableScenes?: { id: string; title: string }[];
    metadataReload?: { token: number; metadata: EntryMetadata; status?: string; entryType: string } | null;
    titleReload?: { token: number; title: string } | null;
    dirty?: boolean;
    todoStatusHint?: string;
    // INTERNAL on: listeners (to still-legacy MetadataPanel/*BodyView) are unchanged.
    onChange?: ((payload: { title: string; body: string; status: string; entryType: string; metadata: EntryMetadata; inputs?: PromptInputDefinition[] }) => void) | undefined;
    onFocus?: (() => void) | undefined;
    onCustomData?: ((payload: { entryType: string; kind: DocumentKind }) => void) | undefined;
    onNavigate?: ((payload: { id: string; kind: string }) => void) | undefined;
    onOpenChat?: ((payload: { entry: PromptEntrySummary; inputs: Record<string, unknown>; sceneId: string | null; assistantId: string }) => void) | undefined;
  }

  let {
    scene = null,
    documentKind = "scene",
    promptEntries = [],
    structure = null,
    researchStructure = null,
    loreEntries = [],
    knownTags = [],
    implicitContextMatcher = null,
    assistantEntries = [],
    defaultAssistantId = "",
    availableScenes = [],
    metadataReload = null,
    titleReload = null,
    dirty = false,
    todoStatusHint = "",
    onChange = undefined,
    onFocus = undefined,
    onCustomData = undefined,
    onNavigate = undefined,
    onOpenChat = undefined
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

  // Rail width is user-resizable via the left-edge drag handle, persisted
  // across sessions. Clamped so the rail can be made slimmer or wider but
  // never collapses the body.
  const RAIL_MIN = 220;
  const RAIL_MAX = 560;
  function loadRailWidth(): number {
    const stored = Number(localStorage.getItem("editorRailWidth"));
    return Number.isFinite(stored) && stored >= RAIL_MIN && stored <= RAIL_MAX ? stored : 280;
  }
  let railWidth = $state(loadRailWidth());
  let railEl: HTMLElement | undefined = $state();
  let railResizing = $state(false);
  let railRightEdge = 0;
  function startRailResize(event: MouseEvent) {
    event.preventDefault();
    railResizing = true;
    railRightEdge = railEl ? railEl.getBoundingClientRect().right : event.clientX + railWidth;
  }
  function onRailResizeMove(event: MouseEvent) {
    if (!railResizing) return;
    // Rail sits on the right edge; dragging its left handle leftward widens it.
    const next = Math.min(RAIL_MAX, Math.max(RAIL_MIN, railRightEdge - event.clientX));
    railWidth = next;
  }
  function endRailResize() {
    if (!railResizing) return;
    railResizing = false;
    localStorage.setItem("editorRailWidth", String(railWidth));
  }
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
  let inputsDialogEntry: PromptEntrySummary | null = $state(null);
  // Inline error inside the inputs dialog — populated when a positional
  // arg (e.g. from `/roleplay Irene`) failed to resolve so the user can
  // see WHY the dialog opened instead of firing directly.
  let inputsDialogError: string | null = $state(null);
  let inputsDialogDrafts: Record<string, string> = $state({});
  // "" means: use the user's default assistant (resolved server-side).
  let inputsDialogAssistantId: string = $state("");
  // Tracked so the inputs-dialog "previously used" path can pre-fill drafts.
  let lastInvokedEntryId: string | null = null;
  let lastInvokedInputs: Record<string, unknown> = {};
  // V2: token + cost estimate for the about-to-fire continuation. Mirrors
  // App.svelte's `chatEstimate`. Recomputed when the dialog's prompt /
  // drafts / assistant change. Null when the dialog is closed.
  let inputsDialogEstimate: {
    tokens: number;
    cost_usd: number | null;
    caching_style: "none" | "auto" | "explicit" | null;
    cache_blocks: { label: string; tokens: number; cache_break_after: boolean }[];
  } | null = $state(null);
  // Monotonic token guarding async preview races — bumps on every fetch;
  // late responses with a stale token drop their result.
  let inputsDialogEstimateToken = 0;

  // --- Per-entry prompt inputs (declaration side) ---
  // Inputs live on the entry now, not the entry-type. The drafts here are
  // the editor-side form state; on every edit we rebuild the canonical
  // PromptInputDefinition[] and emit it as part of the change event.
  // App.svelte stores it on the pane and persists on save. The actual
  // editor UI lives in CodeBodyView; this file owns the drafts state +
  // reseed-on-scene-change + canonical serialization for save.
  let entryInputDrafts: EntryInputDraft[] = $state([]);
  let entryInputDraftCounter = 0;
  function nextInputDraftId(): string {
    entryInputDraftCounter += 1;
    return `__input_${entryInputDraftCounter}`;
  }
  // Seed drafts from the scene prop. scene only changes when a different entry
  // is opened or after a save; the user's typing updates entryInputDrafts
  // locally without touching scene, so this won't fight in-flight edits.
  // Reactive identity key: when scene reference changes (different entry),
  // re-seed. We compare via scene id rather than reference because Svelte may
  // pass the same object reference between renders.
  let lastSeededSceneId: string | null = null;

  function maybeReseedInputs(currentScene: typeof scene, currentKind: typeof documentKind): void {
    if (currentKind !== "prompt" || !currentScene) {
      lastSeededSceneId = null;
      return;
    }
    if (currentScene.id === lastSeededSceneId) return;
    const sceneInputs = ((currentScene as unknown as PromptEntrySummary).inputs ?? []);
    entryInputDrafts = sceneInputs.map(inputDefinitionToDraft);
    lastSeededSceneId = currentScene.id;
  }

  function inputDefinitionToDraft(input: PromptInputDefinition): EntryInputDraft {
    // entity_ref / entity_ref_list / context_pick all carry their picker
    // constraint as a NodePickerConfig under `target` (post-#40). For other
    // types, target is unused — start with an empty config.
    const usesPicker =
      input.type === "context_pick" || input.type === "entity_ref" || input.type === "entity_ref_list";
    const nodePickerConfig =
      usesPicker && input.target && typeof input.target === "object"
        ? (input.target as unknown as import("@/lib/types").NodePickerConfig)
        : ({ kinds: [], presets: [] } as import("@/lib/types").NodePickerConfig);
    return {
      clientId: nextInputDraftId(),
      name: input.name,
      type: input.type,
      label: input.label ?? "",
      defaultValue: input.default === undefined || input.default === null ? undefined : String(input.default),
      // Structured option drafts (value / label / color). Mirrors the field-side
      // editor — see SelectOptionsEditor + decisions-inputs-fields-uniformity.
      options: (input.options ?? []).map((o) => ({
        value: o.value,
        label: o.label ?? "",
        color: o.color ?? null,
        originalValue: o.value,
      })),
      required: Boolean(input.required),
      nodePickerConfig,
      nameDerived: false,
    };
  }

  function entrySlugify(value: string): string {
    return value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^[0-9]/, "input_$&");
  }

  // Map an editor-side default string onto its stored, type-matched value.
  // boolean → real bool, number → real number (falls back to the raw string
  // if unparseable), everything else (text / long_text / select / refs) →
  // string. Callers only invoke this for a defined, non-empty default (#24).
  function defaultValueForStorage(raw: string, type: EntryInputDraft["type"]): import("@/lib/types").MetadataValue {
    if (type === "boolean") return raw === "true";
    if (type === "number") {
      const n = Number(raw);
      return Number.isFinite(n) ? n : raw;
    }
    return raw;
  }

  function entryInputDraftsToCanonical(drafts: EntryInputDraft[]): PromptInputDefinition[] {
    return drafts
      .filter((d) => d.name)
      .map((d) => {
        const out: PromptInputDefinition = {
          name: d.name,
          type: d.type,
        };
        if (d.label) out.label = d.label;
        if (d.required) out.required = true;
        if (d.type === "context_pick" || d.type === "entity_ref" || d.type === "entity_ref_list") {
          // All three ref-shaped types serialize their picker constraint as
          // a NodePickerConfig under `target` (per #40 — same wire shape on
          // both surfaces). `multiple` is derived from the type literal at
          // runtime (entity_ref → false, entity_ref_list → true), so any
          // value the editor wrote is non-load-bearing for entity_ref types.
          // Skip default / options for these types — they don't apply.
          out.target = d.nodePickerConfig as unknown as Record<string, import("@/lib/types").MetadataValue>;
          return out;
        }
        // Persist a type-matched default so the stored YAML carries a real
        // boolean / number rather than a stringly value. `undefined` (and a
        // stray "") means unset → omit `default` entirely (#24).
        if (d.defaultValue !== undefined && d.defaultValue !== "") {
          out.default = defaultValueForStorage(d.defaultValue, d.type);
        }
        if (d.type === "select") {
          // Emit SelectOption objects from the draft list, preserving the
          // author's label + color picks (used to round-trip-lose them via
          // the comma-string shape — see decisions-inputs-fields-uniformity).
          out.options = d.options
            .filter((o) => o.value.trim() !== "")
            .map((o) => {
              const item: import("@/lib/types").SelectOption = { value: o.value.trim() };
              if (o.label) item.label = o.label;
              if (o.color) item.color = o.color;
              return item;
            });
        }
        return out;
      });
  }

  function emitInputsChange(): void {
    if (!scene) return;
    const canonical = entryInputDraftsToCanonical(entryInputDrafts);
    onChange?.({
      title,
      body: rawBodyMode ? rawBody : (proseBodyView?.getBody() ?? ""),
      status,
      entryType,
      metadata: cloneMetadata(metadata),
      inputs: canonical,
    });
  }





  async function refreshBacklinks(sceneId: string) {
    lastBacklinksSceneId = sceneId;
    try {
      const response = await api.listBacklinks(sceneId);
      if (lastBacklinksSceneId === sceneId) {
        backlinks = response.backlinks;
      }
    } catch (error) {
      if (lastBacklinksSceneId === sceneId) backlinks = [];
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
      inputs: documentKind === "prompt" ? entryInputDraftsToCanonical(entryInputDrafts) : undefined,
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

  function effectiveOutputKind(entry: PromptEntrySummary): string | null {
    const definition = metadataSchema?.entry_types[entry.entry_type];
    const output = definition?.prompt?.context_strategy?.output;
    if (!output || typeof output.kind !== "string") return null;
    return output.kind;
  }

  function promptEntriesForSurface(surface: "append_to_body" | "replace_selection" | "chat_panel"): PromptEntrySummary[] {
    if (!metadataSchema) return [];
    return promptEntries
      .filter((entry) => effectiveOutputKind(entry) === surface)
      .sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
  }

  function promptEntryDescription(entry: PromptEntrySummary): string {
    const typeName = metadataSchema?.entry_types[entry.entry_type]?.name ?? entry.entry_type;
    return typeName;
  }

  function effectivePromptInputs(entry: PromptEntrySummary) {
    // Inputs now live on the entry itself (not the entry-type) — the
    // declaration and the template that uses it are coupled.
    return entry.inputs ?? [];
  }

  function openInputsDialog(entry: PromptEntrySummary) {
    const declared = effectivePromptInputs(entry);
    const prior = lastInvokedEntryId === entry.id ? lastInvokedInputs : {};
    const drafts: Record<string, string> = {};
    for (const input of declared) {
      const previous = prior[input.name];
      if (previous !== undefined && previous !== null) {
        drafts[input.name] = String(previous);
      } else if (input.default !== undefined && input.default !== null) {
        drafts[input.name] = String(input.default);
      } else {
        // Seed everything to "" — the runtime's unset state, consistent
        // with the preview (#42). Previously boolean was special-cased to
        // "false", which silently sent the model `false` for an
        // untouched checkbox while the preview surfaced an unset/undefined
        // error. The runtime is now tri-state (Unset/True/False) so the
        // user explicitly picks True or False or leaves it unset.
        drafts[input.name] = "";
      }
    }
    inputsDialogDrafts = drafts;
    // Seed with the user's default; the picker shows it as "Default (Name)".
    inputsDialogAssistantId = "";
    inputsDialogError = null;
    inputsDialogEntry = entry;
  }

  function cancelInputsDialog() {
    inputsDialogEntry = null;
    inputsDialogDrafts = {};
    inputsDialogAssistantId = "";
    inputsDialogError = null;
  }

  function updateInputsDialogDraft(name: string, value: string) {
    inputsDialogDrafts = { ...inputsDialogDrafts, [name]: value };
  }

  async function fetchInputsDialogEstimate(): Promise<void> {
    const entry = inputsDialogEntry;
    if (!entry) {
      inputsDialogEstimate = null;
      return;
    }
    const ourToken = ++inputsDialogEstimateToken;
    const declared = effectivePromptInputs(entry);
    const inputs: Record<string, unknown> = {};
    for (const input of declared) {
      const raw = inputsDialogDrafts[input.name] ?? "";
      const coerced = coerceInputValue(raw, input.type);
      if (coerced !== null && coerced !== "") inputs[input.name] = coerced;
    }
    try {
      const preview = await api.aiPreview({
        template_source: entry.body,
        target_scene_id: scene?.id ?? "",
        inputs,
        resolution_scene_id: resolutionSceneIdFromInputs(entry, inputs),
        commit: false,
        assistant_id: inputsDialogAssistantId || null,
      });
      if (ourToken !== inputsDialogEstimateToken) return;
      // Render errors come back as 200 + preview.error (the endpoint is
      // exploratory). Errors surface when the user runs, so keep the
      // estimate strip quiet — null out instead of flickering a stale value.
      if (preview.error) {
        inputsDialogEstimate = null;
        return;
      }
      inputsDialogEstimate = {
        tokens: preview.estimated_tokens ?? 0,
        cost_usd: preview.estimated_cost_usd ?? null,
        caching_style: preview.caching_style ?? null,
        cache_blocks: (preview.cache_blocks ?? []).map((b) => ({
          label: b.label,
          tokens: b.tokens,
          cache_break_after: b.cache_break_after,
        })),
      };
    } catch {
      // Non-render failure (project closed, 5xx, etc.) — same UX.
    }
  }


  function refInputDraftValue(input: PromptInputDefinition, raw: string | undefined): string | string[] {
    if (input.type === "entity_ref_list") {
      if (!raw) return [];
      try {
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
      } catch {
        return [];
      }
    }
    return raw ?? "";
  }

  function encodeRefInputDraft(value: string | string[]): string {
    return Array.isArray(value) ? JSON.stringify(value) : value;
  }

  function assistantDisplayName(assistantId: string): string {
    if (!assistantId) return "";
    return assistantEntries.find((a) => a.id === assistantId)?.title ?? "";
  }

  function refInputStubField(input: PromptInputDefinition): MetadataFieldDefinition {
    // entity_ref / entity_ref_list inputs persist their picker config as a
    // NodePickerConfig under `target` (post-#40). Surface it as
    // `picker_config` for ReferencePicker, which is the same shape the field
    // side uses.
    const picker =
      input.target && typeof input.target === "object"
        ? (input.target as unknown as import("@/lib/types").NodePickerConfig)
        : null;
    return {
      name: input.label || input.name,
      type: input.type === "entity_ref_list" ? "entity_ref_list" : "entity_ref",
      options: [],
      picker_config: picker,
    };
  }

  async function submitInputsDialog() {
    const entry = inputsDialogEntry;
    if (!entry) return;
    const declared = effectivePromptInputs(entry);
    const missing = declared.filter((input) => {
      if (!input.required) return false;
      const raw = inputsDialogDrafts[input.name];
      if (input.type === "entity_ref_list") {
        const list = refInputDraftValue(input, raw);
        return !Array.isArray(list) || list.length === 0;
      }
      return !raw?.trim();
    });
    if (missing.length > 0) {
      inputsDialogError = `Missing required: ${missing.map((i) => i.label || i.name).join(", ")}.`;
      return;
    }
    const values: Record<string, unknown> = {};
    for (const input of declared) {
      const raw = inputsDialogDrafts[input.name] ?? "";
      const coerced = coerceInputValue(raw, input.type);
      if (coerced !== null && coerced !== "") values[input.name] = coerced;
    }
    const pickedAssistantId = inputsDialogAssistantId;
    lastInvokedEntryId = entry.id;
    lastInvokedInputs = values;
    inputsDialogEntry = null;
    inputsDialogDrafts = {};
    inputsDialogAssistantId = "";
    // Forward to ProseBodyView, which owns the AI streaming machinery.
    await proseBodyView?.runPromptEntryWithInputsExternal(entry, values, pickedAssistantId);
  }

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

  // Handler for ProseBodyView's `request-inputs-dialog` event.
  function handleRequestInputsDialog(payload: {
    entry: PromptEntrySummary;
    prefilledDrafts?: Record<string, string>;
    unresolved?: Array<{ name: string; label: string; token: string }>;
  }) {
    const { entry, prefilledDrafts, unresolved } = payload;
    openInputsDialog(entry);
    if (prefilledDrafts) {
      for (const [name, value] of Object.entries(prefilledDrafts)) {
        updateInputsDialogDraft(name, value);
      }
    }
    if (unresolved && unresolved.length > 0) {
      inputsDialogError = unresolved
        .map((u) => `Couldn't find "${u.token}" for ${u.label}`)
        .join(" · ");
    }
  }

  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  let metadataSchema = $derived($metadataSchemaStore);
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
    maybeReseedInputs(scene, documentKind);
  });
  let documentLabel = $derived(documentKind === "lore" ? "Entry" : documentKind === "structure_node" ? "Node" : documentKind === "chat" ? "Chat" : "Scene");
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
  let documentEntryTypes = $derived(Object.entries(metadataSchema?.entry_types ?? {}).filter(([, definition]) => definition.kind === (documentKind === "structure_node" ? "scene" : documentKind) && !definition.abstract));
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
  // `color` is filtered out because the dedicated SwatchPicker in the
  // metadata-color-row above already edits metadata.color — letting the
  // generic field switch render it too would produce a duplicate
  // (untyped text input) row.
  let metadataFieldIds = $derived(((metadataSchema?.entry_types[entryType] ?? metadataSchema?.entry_types[defaultEntryType()])?.fields ?? []).filter((fieldId) => fieldId !== "color"));
  let hasBody = $derived(bodyShape !== "none");
  $effect.pre(() => {
    if (titleReload && titleReload.token !== lastTitleReloadToken) {
      lastTitleReloadToken = titleReload.token;
      title = titleReload.title;
    }
  });
  $effect.pre(() => {
    if (scene && scene.id !== lastBacklinksSceneId) {
      void refreshBacklinks(scene.id);
    } else if (!scene && lastBacklinksSceneId !== null) {
      lastBacklinksSceneId = null;
      backlinks = [];
    }
  });
  // Reactive trigger: refetch when the dialog's prompt / drafts / assistant
  // change. Per [[feedback-svelte5-reactivity-traps]], read each dep on its
  // own line so Svelte tracks them — a function call alone wouldn't.
  $effect.pre(() => {
    void inputsDialogEntry;
    void inputsDialogDrafts;
    void inputsDialogAssistantId;
    void fetchInputsDialogEstimate();
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
      loreEntries={loreEntries}
      promptEntries={promptEntries}
      structure={structure}
      researchStructure={researchStructure}
      implicitContextMatcher={implicitContextMatcher}
      excludeId={scene?.id ?? null}
      computedFieldString={computedFieldString}
      effectiveOverrides={scrubbed ? scrub.overrides : null}
      readOnly={scrubbed}
      onEntryTypeChange={(next) => updateEntryType(next)}
      onStatusChange={(next) => updateStatus(next)}
      onMetadataChange={(next) => {
        metadata = next;
        emitChange();
      }}
      onCustomData={() => onCustomData?.({ entryType, kind: documentKind })}
      onNavigate={(payload) => onNavigate?.(payload)}
    />
    {#key scene?.id ?? ""}
      <BacklinksPanel
        backlinks={backlinks}
        loreEntries={loreEntries}
        structure={structure}
        on:navigate={(event) => onNavigate?.(event.detail)}
      />
    {/key}
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

<svelte:window onmousemove={onRailResizeMove} onmouseup={endRailResize} />

<div
  class="editor-panel"
  class:body-hidden={bodyShape === "none"}
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
          {:else}
            <input class="title-input" aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()}`} placeholder={documentNameLabel} bind:value={title} oninput={handleTitleInput} />
          {/if}
        </label>
      </div>
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
      bind:entryInputDrafts
      {scene}
      {documentKind}
      {structure}
      {researchStructure}
      {loreEntries}
      {promptEntries}
      {availableScenes}
      {rawBodyLanguage}
      {loadedSceneId}
      {nextInputDraftId}
      {entrySlugify}
      onInputsChange={emitInputsChange}
    />
  {/if}
  {#if bodyShape === "prose"}
    {#if scrubbed}
      <!-- The effective body as of the scrub point (§4.4). An overlay layer:
           the editable TipTap buffer stays mounted (hidden) underneath, so
           unsaved base edits survive the scrub round-trip untouched. -->
      <div class="effective-body" aria-label="Effective body (read-only)">
        {#if bodyMutated}
          <div class="effective-body-ribbon">
            <span aria-hidden="true">⤳</span>
            Body as of {scrub.units[scrub.index - 1]?.records[0]?.scene_path || "scene"} — mutated
          </div>
        {/if}
        <div class="effective-body-content">
          <!-- eslint-disable-next-line svelte/no-at-html-tags — sceneMarkdownToHtml output, same trust level as the editor load path -->
          {@html overlayBodyHtml}
        </div>
      </div>
    {/if}
    <div class="prose-body-host" class:hidden={scrubbed}>
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
      onRequestInputsDialog={handleRequestInputsDialog}
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
    />
  {/if}

  {#if scene && metadataSchema && !railIsPane}
    {#if railOpen}
      <aside class="editor-rail" class:resizing={railResizing} style={`width: ${railWidth}px`} bind:this={railEl} aria-label={`${documentLabel} details`}>
        <button
          class="rail-resize"
          type="button"
          title="Drag to resize details"
          aria-label="Resize details rail"
          onmousedown={startRailResize}
        ></button>
        <div class="rail-head">
          <span class="rail-head-label">Details</span>
          <button
            class="rail-collapse"
            type="button"
            title="Collapse details"
            aria-label="Collapse details"
            onclick={() => (railOpen = false)}
          >
            <i class="ti ti-layout-sidebar-right-collapse" aria-hidden="true"></i>
          </button>
        </div>
        <div class="rail-scroll">
          {@render metaContent()}
        </div>
      </aside>
    {:else}
      <button
        class="rail-tab"
        type="button"
        title="Show details"
        aria-label="Show details"
        onclick={() => (railOpen = true)}
      >
        <i class="ti ti-layout-sidebar-right-expand" aria-hidden="true"></i>
        <span class="rail-tab-label">Details</span>
      </button>
    {/if}
  {/if}

  {#if documentKind === "lore" && scene && scrub.units.length > 0}
    <MutationScrubber units={scrub.units} index={scrub.index} onScrub={(index) => void scrub.scrubTo(index)} />
  {/if}

  <footer class="status">
    {#if scene}
      {dirty ? "Unsaved changes" : `Loaded ${scene.title}`}
    {:else}
      No scene open
    {/if}
  </footer>
</div>

{#if inputsDialogEntry}
  <InputsDialog
    entry={inputsDialogEntry}
    description={promptEntryDescription(inputsDialogEntry)}
    declaredInputs={effectivePromptInputs(inputsDialogEntry)}
    drafts={inputsDialogDrafts}
    assistantId={inputsDialogAssistantId}
    defaultAssistantLabel={assistantDisplayName(defaultAssistantId) || "use machine default"}
    assistantEntries={assistantEntries}
    error={inputsDialogError}
    estimate={inputsDialogEstimate}
    structure={structure}
    researchStructure={researchStructure}
    loreEntries={loreEntries}
    promptEntries={promptEntries}
    excludeId={scene?.id ?? null}
    implicitContextMatcher={implicitContextMatcher}
    on:updateDraft={(event) => updateInputsDialogDraft(event.detail.name, event.detail.value)}
    on:updateAssistant={(event) => (inputsDialogAssistantId = event.detail.assistantId)}
    on:cancel={cancelInputsDialog}
    on:submit={() => void submitInputsDialog()}
  />
{/if}

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

  .editor-panel.has-rail {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .editor-panel.has-rail > :global(*) {
    grid-column: 1;
    min-width: 0;
  }
  .editor-panel.has-rail > .editor-rail,
  .editor-panel.has-rail > .rail-tab {
    grid-column: 2;
    grid-row: 1 / -1;
  }

  .editor-rail {
    display: flex;
    flex-direction: column;
    position: relative;
    width: 280px;
    min-height: 0;
    background: var(--inset, #f1f5f3);
    border-left: 1px solid var(--divider, var(--divider));
  }

  /* Left-edge drag handle to widen/narrow the rail. */
  .rail-resize {
    position: absolute;
    top: 0;
    left: -3px;
    width: 7px;
    height: 100%;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    cursor: col-resize;
    z-index: 5;
  }

  .rail-resize:hover {
    background: linear-gradient(
      to right,
      transparent 0 2px,
      var(--accent, #2f6f5e) 2px 4px,
      transparent 4px
    );
  }

  .editor-rail.resizing {
    user-select: none;
  }

  .editor-rail.resizing .rail-resize {
    background: linear-gradient(
      to right,
      transparent 0 2px,
      var(--accent, #2f6f5e) 2px 4px,
      transparent 4px
    );
  }

  .rail-head {
    display: flex;
    align-items: center;
    gap: 7px;
    flex: 0 0 auto;
    padding: 10px 12px;
    border-bottom: 1px solid var(--divider, var(--divider));
  }

  .rail-head-label {
    flex: 1;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--text-3, var(--text-3));
  }

  .rail-collapse {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    width: 24px;
    height: 24px;
    padding: 0;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: var(--text-3, var(--text-3));
    font-size: 16px;
    cursor: pointer;
  }

  .rail-collapse:hover {
    background: var(--surface, #fff);
    border-color: var(--divider, var(--divider));
    color: var(--text-2, var(--text-2));
  }

  .rail-scroll {
    flex: 1 1 auto;
    min-height: 0;
    overflow: auto;
    overscroll-behavior: contain;
  }

  /* Collapsed: a 34px vertical edge-tab that reopens the rail. */
  .rail-tab {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    width: 34px;
    padding: 12px 0;
    border: 0;
    border-left: 1px solid var(--divider, var(--divider));
    background: var(--inset, #f1f5f3);
    color: var(--text-3, var(--text-3));
    font-size: 15px;
    cursor: pointer;
  }

  .rail-tab:hover {
    color: var(--text, #242424);
    background: var(--panel, var(--panel));
  }

  .rail-tab-label {
    writing-mode: vertical-rl;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.09em;
    text-transform: uppercase;
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
    grid-template-columns: minmax(0, 1fr);
    gap: 4px;
    align-items: start;
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
    color: var(--mutation-color, #7c5cbf);
    font-weight: 700;
  }
  .title-input[readonly] {
    background: var(--inset, #f1f5f3);
    cursor: default;
  }
  .title-input.mutated {
    color: var(--mutation-color, #7c5cbf);
    font-weight: 600;
  }

  .effective-body {
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }
  .effective-body-ribbon {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 24px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--mutation-color, #7c5cbf);
    background: color-mix(in srgb, var(--mutation-color, #7c5cbf) 10%, transparent);
    border-bottom: 1px solid color-mix(in srgb, var(--mutation-color, #7c5cbf) 30%, transparent);
  }
  .effective-body-content {
    padding: 12px 24px 24px;
    max-width: 72ch;
    font-size: 15px;
    line-height: 1.65;
    color: var(--text, #242424);
  }
  .effective-body-content :global(p) {
    margin: 0 0 0.9em;
  }

  .title-label {
    display: grid;
    gap: 3px;
    color: var(--text-3);
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
  }

  .title-input {
    border: 0;
    border-bottom: 1px solid var(--divider);
    border-radius: 0;
    font-family:
      Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI",
      sans-serif;
    font-size: 26px;
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
    color: var(--color-muted, #888);
    font-size: 11px;
    white-space: nowrap;
    cursor: default;
    flex: 0 0 auto;
  }

  /* Single-value rollup chip for character_cost / project_cost (lore
     character entries and the project node respectively). Same muted
     tone as the scene cost chips so the editor hint row stays calm. */
  .node-rollup-cost-chip {
    color: var(--color-muted, #888);
    font-size: 11px;
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
    font-size: 11px;
    color: var(--color-muted, #888);
    white-space: nowrap;
    cursor: default;
  }

  .character-cost-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--character-color, #888);
    flex: 0 0 auto;
  }

  .character-cost-name {
    color: var(--color-text, #1a1a1a);
  }

  .character-cost-amount {
    font-variant-numeric: tabular-nums;
  }
</style>
