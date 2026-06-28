<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import BacklinksPanel from "./BacklinksPanel.svelte";
  import MetadataPanel from "./MetadataPanel.svelte";
  import InputsDialog from "./InputsDialog.svelte";
  import FieldsOnlyView from "./FieldsOnlyView.svelte";
  import CodeBodyView from "./CodeBodyView.svelte";
  import ProseBodyView from "./ProseBodyView.svelte";
  import ChatBodyView from "./ChatBodyView.svelte";
  import type { EmbeddedTodo } from "./ProseBodyView.svelte";
  import { coerceInputValue, type EntryInputDraft } from "./promptInputs";
  import { api } from "./api";
  import { formatCostEur } from "./money";
  import { resolveColor } from "./colors";
  import type { AssistantEntrySummary, Backlink, BodyShape, EditableDocument, EntryBodyLanguage, EntryMetadata, EntryTypeDefinition, MetadataFieldDefinition, MetadataSchema, PromptEntrySummary, PromptInputDefinition } from "./types";

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

  export let scene: EditableDocument | null = null;
  export let documentKind: "scene" | "lore" | "prompt" | "snippet" | "assistant" | "project" | "structure_node" | "chat" | "research" = "scene";
  export let metadataSchema: MetadataSchema | null = null;
  export let promptEntries: PromptEntrySummary[] = [];
  // Data sources for context_pick inputs in the prompt preview / inputs
  // dialog. Optional — the picker degrades to "no items" when missing.
  export let structure: import("./types").StructureDocument | null = null;
  // Research tree, sibling to manuscript `structure`. Threaded through to
  // the context picker so context_pick / entity_ref fields can target
  // research notes.
  export let researchStructure: import("./types").StructureDocument | null = null;
  export let loreEntries: import("./types").LoreEntrySummary[] = [];
  export let knownTags: import("./types").ScopedTag[] = [];
  // Optional matcher pass-through for the implicit-context highlight
  // plugin on long-text metadata fields. App.svelte owns the compile.
  export let implicitContextMatcher: import("./implicitContextMatcher").CompiledMatcher | null = null;
  export let assistantEntries: AssistantEntrySummary[] = [];
  export let defaultAssistantId: string = "";
  // Scenes available for the inline prompt-preview scene picker. The pane is
  // host-agnostic — App.svelte derives this from its structure tree.
  export let availableScenes: { id: string; title: string }[] = [];
  export let metadataReload: { token: number; metadata: EntryMetadata; status?: string; entryType: string } | null = null;
  export let titleReload: { token: number; title: string } | null = null;
  export let dirty = false;
  export let todoStatusHint = "";

  const dispatch = createEventDispatcher<{
    change: { title: string; bodyMarkdown: string; status: string; entryType: string; metadata: EntryMetadata; inputs?: PromptInputDefinition[] };
    focus: void;
    "custom-data": { entryType: string; kind: "scene" | "lore" | "prompt" | "assistant" };
    embeddedTodos: { todos: EmbeddedTodo[] };
    navigate: { id: string; kind: string };
    "open-chat": { entry: PromptEntrySummary; inputs: Record<string, unknown>; sceneId: string | null; assistantId: string };
    renamed: void;
    "cost-changed": void;
  }>();


  let proseBodyView: ProseBodyView | null = null;
  let chatBodyView: ChatBodyView | null = null;
  let loadedSceneId: string | null = null;
  let rawBody = "";
  let lastEmittedRawBody = "";
  $: entryTypeDef = metadataSchema?.entry_types[entryType] ?? null;
  $: bodyShape = deriveBodyShape(entryTypeDef);
  $: rawBodyMode = bodyShape === "code";
  $: rawBodyLanguage = (entryTypeDef?.body_language ?? "markdown") satisfies EntryBodyLanguage;
  $: if (rawBodyMode && rawBody !== lastEmittedRawBody) {
    lastEmittedRawBody = rawBody;
    emitChange();
  }
  let title = "";
  let status = "draft";
  let entryType = "scene";
  let metadata: EntryMetadata = {};
  // Bound out from ProseBodyView so MetadataPanel's computedFieldString
  // (word_count) + the editor-hint string can read them.
  let liveWordCount = 0;
  let editorEmpty = true;
  // Metadata rail (body-spec Section A). Per body shape: prose/code open,
  // chat collapses to a 34px edge-tab, none turns the rail into the pane.
  // `railOpen` is the user-toggleable state for the side rail; reset per
  // scene load below. `railIsPane` means metadata renders as the main
  // content (none-shape: assistant / project / structure_node).
  let railOpen = true;
  $: railIsPane = bodyShape === "none";

  // Rail width is user-resizable via the left-edge drag handle, persisted
  // across sessions. Clamped so the rail can be made slimmer or wider but
  // never collapses the body.
  const RAIL_MIN = 220;
  const RAIL_MAX = 560;
  function loadRailWidth(): number {
    const stored = Number(localStorage.getItem("editorRailWidth"));
    return Number.isFinite(stored) && stored >= RAIL_MIN && stored <= RAIL_MAX ? stored : 280;
  }
  let railWidth = loadRailWidth();
  let railEl: HTMLElement | undefined;
  let railResizing = false;
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
  let lastInvocationCostUsd: number | null = null;
  let sceneSessionCostUsd = 0;
  // Per-character cost map for this scene, summed from the persisted
  // ai_invocations log. ProseBodyView owns the state; the footer reads it.
  let characterCostUsd: Record<string, number> = {};

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
  $: characterCostRowsView = characterCostRows(characterCostUsd, loreEntries, metadataSchema);

  // All-time rollup costs surfaced as a single chip in the header hint.
  // character_cost lives on lore character entries, project_cost on the
  // project node — backend populates both via `computed_metadata`.
  // Trust the computed field as the surface contract; render only when
  // the kind matches and the number is non-zero.
  $: rollupCostKind = (() => {
    if (!scene) return null;
    const computed = scene.computed_metadata as Record<string, unknown> | undefined;
    if (documentKind === "lore" && typeof computed?.character_cost === "number" && computed.character_cost > 0) {
      return { kind: "character" as const, value: computed.character_cost as number };
    }
    if (documentKind === "project" && typeof computed?.project_cost === "number" && computed.project_cost > 0) {
      return { kind: "project" as const, value: computed.project_cost as number };
    }
    return null;
  })();
  let lastMetadataReloadToken = 0;
  let lastTitleReloadToken = 0;
  let backlinks: Backlink[] = [];
  let lastBacklinksSceneId: string | null = null;
  let inputsDialogEntry: PromptEntrySummary | null = null;
  // Inline error inside the inputs dialog — populated when a positional
  // arg (e.g. from `/roleplay Irene`) failed to resolve so the user can
  // see WHY the dialog opened instead of firing directly.
  let inputsDialogError: string | null = null;
  let inputsDialogDrafts: Record<string, string> = {};
  // "" means: use the user's default assistant (resolved server-side).
  let inputsDialogAssistantId: string = "";
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
  } | null = null;

  // --- Per-entry prompt inputs (declaration side) ---
  // Inputs live on the entry now, not the entry-type. The drafts here are
  // the editor-side form state; on every edit we rebuild the canonical
  // PromptInputDefinition[] and emit it as part of the change event.
  // App.svelte stores it on the pane and persists on save. The actual
  // editor UI lives in CodeBodyView; this file owns the drafts state +
  // reseed-on-scene-change + canonical serialization for save.
  let entryInputDrafts: EntryInputDraft[] = [];
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
  $: maybeReseedInputs(scene, documentKind);

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
        ? (input.target as unknown as import("./types").NodePickerConfig)
        : ({ kinds: [], presets: [] } as import("./types").NodePickerConfig);
    return {
      clientId: nextInputDraftId(),
      name: input.name,
      type: input.type,
      label: input.label ?? "",
      defaultValue: input.default === undefined || input.default === null ? undefined : String(input.default),
      options: (input.options ?? []).map((o) => o.value).join(", "),
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
  function defaultValueForStorage(raw: string, type: EntryInputDraft["type"]): import("./types").MetadataValue {
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
          out.target = d.nodePickerConfig as unknown as Record<string, import("./types").MetadataValue>;
          return out;
        }
        // Persist a type-matched default so the stored YAML carries a real
        // boolean / number rather than a stringly value. `undefined` (and a
        // stray "") means unset → omit `default` entirely (#24).
        if (d.defaultValue !== undefined && d.defaultValue !== "") {
          out.default = defaultValueForStorage(d.defaultValue, d.type);
        }
        if (d.type === "select") {
          // Emit SelectOption objects; colors aren't editable from the
          // prompt-input draft surface today (Phase 3 adds them to the
          // Detail Field editor for metadata-level selects).
          out.options = d.options
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean)
            .map((value) => ({ value }));
        }
        return out;
      });
  }

  function emitInputsChange(): void {
    if (!scene) return;
    const canonical = entryInputDraftsToCanonical(entryInputDrafts);
    dispatch("change", {
      title,
      bodyMarkdown: rawBodyMode ? rawBody : (proseBodyView?.getBodyMarkdown() ?? ""),
      status,
      entryType,
      metadata: cloneMetadata(metadata),
      inputs: canonical,
    });
  }

  $: documentLabel = documentKind === "lore" ? "Entry" : documentKind === "structure_node" ? "Node" : documentKind === "chat" ? "Chat" : "Scene";
  $: documentNameLabel = documentKind === "lore" ? "Name" : documentKind === "chat" ? "Title" : "Title";
  // structure_node has no schema kind of its own — Acts/Chapters share
  // kind="scene" in the metadata schema. Reuse the scene entry types so
  // the type selector still lists Act/Chapter/Scene/etc.
  $: documentEntryTypes = Object.entries(metadataSchema?.entry_types ?? {}).filter(([, definition]) => definition.kind === (documentKind === "structure_node" ? "scene" : documentKind) && !definition.abstract);
  $: activeEntryType = metadataSchema?.entry_types[entryType] ?? metadataSchema?.entry_types[defaultEntryType()];
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
  $: metadataFieldIds = ((metadataSchema?.entry_types[entryType] ?? metadataSchema?.entry_types[defaultEntryType()])?.fields ?? []).filter((fieldId) => fieldId !== "color");
  $: hasBody = bodyShape !== "none";

  $: if (metadataReload && metadataReload.token !== lastMetadataReloadToken) {
    lastMetadataReloadToken = metadataReload.token;
    status = metadataReload.status || defaultStatus();
    entryType = metadataReload.entryType || defaultEntryType();
    metadata = cloneMetadata(metadataReload.metadata);
  }

  $: if (titleReload && titleReload.token !== lastTitleReloadToken) {
    lastTitleReloadToken = titleReload.token;
    title = titleReload.title;
  }

  $: if (scene && scene.id !== lastBacklinksSceneId) {
    void refreshBacklinks(scene.id);
  } else if (!scene && lastBacklinksSceneId !== null) {
    lastBacklinksSceneId = null;
    backlinks = [];
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

  // When a NEW entry opens (different id), sync the shell-owned fields
  // synchronously. ProseBodyView's own scene reactive handles the editor
  // body load. Setting entryType / title / metadata here (not inside an
  // async function) is essential: an `await` would break Svelte 5's
  // legacy reactive batching and metadataFieldIds would freeze on the
  // previous entry-type's fields ([[feedback-svelte5-reactivity-traps]]).
  $: if (scene && scene.id !== loadedSceneId) {
    const nextEntryType = scene.entry_type || defaultEntryType();
    title = scene.title;
    status = documentStatus(scene);
    entryType = nextEntryType;
    metadata = cloneMetadata(scene.metadata);
    // Read body shape from the FRESHLY-resolved entry-type (not the
    // `bodyShape` reactive, which hasn't recomputed yet — and reading
    // it would introduce a cyclical reactive dependency, since
    // `bodyShape` depends on `entryType`).
    const nextBodyShape = deriveBodyShape(metadataSchema?.entry_types[nextEntryType]);
    if (nextBodyShape === "code") {
      // Code body: hydrate rawBody directly. ProseBodyView is unmounted
      // in this branch so no editor-side load runs.
      rawBody = scene.body_markdown ?? "";
      lastEmittedRawBody = rawBody;
    }
    loadedSceneId = scene.id;
    // Chat starts with the rail collapsed to its edge-tab so the
    // conversation owns full width; every other shape opens it.
    railOpen = nextBodyShape !== "chat";
  }

  $: if (!scene && loadedSceneId !== null) {
    loadedSceneId = null;
    title = "";
    status = defaultStatus();
    entryType = defaultEntryType();
    metadata = {};
    liveWordCount = 0;
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
  }

  function emitChange() {
    if (!scene) return;
    dispatch("change", {
      title,
      bodyMarkdown: rawBodyMode ? rawBody : (proseBodyView?.getBodyMarkdown() ?? ""),
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
    if (documentKind === "lore") return "lore_note";
    if (documentKind === "chat") return "chat_session";
    return "scene";
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
        drafts[input.name] = input.type === "boolean" ? "false" : "";
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
        template_source: entry.body_markdown,
        target_scene_id: scene?.id ?? "",
        inputs,
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

  // Reactive trigger: refetch when the dialog's prompt / drafts / assistant
  // change. Per [[feedback-svelte5-reactivity-traps]], read each dep on its
  // own line so Svelte tracks them — a function call alone wouldn't.
  $: {
    void inputsDialogEntry;
    void inputsDialogDrafts;
    void inputsDialogAssistantId;
    void fetchInputsDialogEstimate();
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
        ? (input.target as unknown as import("./types").NodePickerConfig)
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

  // Embedded-TODO exports — forwarded to ProseBodyView. App.svelte calls
  // these via `editorPaneComponents[pane.id].xxx(...)`; keeping them
  // exported on NodeEditor preserves the existing pane-component
  // contract without an App-side change.
  export function updateEmbeddedTodo(todoId: string, updates: { status?: "open" | "done"; note?: string }) {
    proseBodyView?.updateEmbeddedTodo(todoId, updates);
  }

  export function deleteEmbeddedTodo(todoId: string) {
    proseBodyView?.deleteEmbeddedTodo(todoId);
  }

  export function highlightEmbeddedTodo(todoId: string) {
    proseBodyView?.highlightEmbeddedTodo(todoId);
  }

  // Handler for ProseBodyView's `request-inputs-dialog` event.
  function handleRequestInputsDialog(event: CustomEvent<{
    entry: PromptEntrySummary;
    prefilledDrafts?: Record<string, string>;
    unresolved?: Array<{ name: string; label: string; token: string }>;
  }>) {
    const { entry, prefilledDrafts, unresolved } = event.detail;
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

</script>

<!-- Metadata + backlinks, rendered into either the side rail (prose/code/
     chat) or the whole pane (none-shape). Defined once as a snippet so the
     long prop list isn't duplicated across the two host slots. -->
{#snippet metaContent()}
  {#if metadataSchema}
    <MetadataPanel
      metadataSchema={metadataSchema}
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
      on:entryTypeChange={(event) => updateEntryType(event.detail.entryType)}
      on:statusChange={(event) => updateStatus(event.detail.status)}
      on:metadataChange={(event) => {
        metadata = event.detail.metadata;
        emitChange();
      }}
      on:customData={() => dispatch("custom-data", { entryType, kind: documentKind })}
      on:navigate={(event) => dispatch("navigate", event.detail)}
    />
    {#key scene?.id ?? ""}
      <BacklinksPanel
        backlinks={backlinks}
        metadataSchema={metadataSchema}
        loreEntries={loreEntries}
        structure={structure}
        on:navigate={(event) => dispatch("navigate", event.detail)}
      />
    {/key}
  {/if}
{/snippet}

<svelte:window on:mousemove={onRailResizeMove} on:mouseup={endRailResize} />

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
          {documentNameLabel}
          <input class="title-input" aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()}`} placeholder={documentNameLabel} bind:value={title} on:input={handleTitleInput} />
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
      {metadataSchema}
      {structure}
      {researchStructure}
      {loreEntries}
      {promptEntries}
      {availableScenes}
      {rawBodyLanguage}
      {loadedSceneId}
      {nextInputDraftId}
      {entrySlugify}
      on:inputsChange={emitInputsChange}
    />
  {/if}
  {#if bodyShape === "prose"}
    <ProseBodyView
      bind:this={proseBodyView}
      bind:liveWordCount
      bind:editorEmpty
      bind:lastInvocationCostUsd
      bind:sceneSessionCostUsd
      bind:characterCostUsd
      {scene}
      {documentKind}
      {metadataSchema}
      {loreEntries}
      {promptEntries}
      {availableScenes}
      {implicitContextMatcher}
      {documentLabel}
      on:body-change={emitChange}
      on:focus={() => dispatch("focus")}
      on:embedded-todos={(event) => dispatch("embeddedTodos", event.detail)}
      on:open-chat={(event) => dispatch("open-chat", event.detail)}
      on:request-inputs-dialog={handleRequestInputsDialog}
    />
  {/if}
  {#if bodyShape === "chat"}
    <ChatBodyView
      bind:this={chatBodyView}
      {scene}
      {metadataSchema}
      {promptEntries}
      {assistantEntries}
      {loreEntries}
      {structure}
      {researchStructure}
      {defaultAssistantId}
      {implicitContextMatcher}
      on:body-change={emitChange}
      on:focus={() => dispatch("focus")}
      on:open-chat={(event) => dispatch("open-chat", event.detail)}
      on:renamed={() => dispatch("renamed")}
      on:cost-changed={() => dispatch("cost-changed")}
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
          on:mousedown={startRailResize}
        ></button>
        <div class="rail-head">
          <span class="rail-head-label">Details</span>
          <button
            class="rail-collapse"
            type="button"
            title="Collapse details"
            aria-label="Collapse details"
            on:click={() => (railOpen = false)}
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
        on:click={() => (railOpen = true)}
      >
        <i class="ti ti-layout-sidebar-right-expand" aria-hidden="true"></i>
        <span class="rail-tab-label">Details</span>
      </button>
    {/if}
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
    metadataSchema={metadataSchema}
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
