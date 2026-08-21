<!--
  CodeBodyView — body region for entry types with body_shape === "code"
  (today: prompts and snippets). Owns the CodeMirror editor + the wrap/
  restore-default toolbar + the help button & cheatsheet popover. For
  prompts it composes two sidecars: EntryInputsEditor (declared-inputs
  editor) and PromptPreviewPane (the inline render preview). Sibling of
  ProseBodyView. See decisions-node-editor-modularization (Phase 2).

  State owned here is presentational only — cheatsheet open/closed, the
  soft-wrap preference, and the gutter diagnostics fed to the editor
  (written by PromptPreviewPane). The two persisted pieces (rawBody,
  entryInputDrafts) are bind:'d to the parent so the parent's save logic
  owns serialization.
-->
<script lang="ts">
  import { api } from "@/lib/api";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import {
    dependencyAdvisoryText,
    inheritedInputsFrom,
    isSnippetType,
    surfaceForStrategy,
  } from "@/lib/editor-core/promptResolution";
  import { onDestroy } from "svelte";
  import type { Snippet } from "svelte";
  import CodeEditor from "@/components/widgets/CodeEditor.svelte";
  import EntryInputsEditor from "@/components/editor/body/EntryInputsEditor.svelte";
  import OfferOnPicker from "@/components/editor/body/OfferOnPicker.svelte";
  import PromptOutputEditor from "@/components/editor/body/PromptOutputEditor.svelte";
  import PromptPreviewPane from "@/components/editor/body/PromptPreviewPane.svelte";
  import RegionRegistrar from "@/components/workspace/RegionRegistrar.svelte";
  import { closeSubordinatePane, openSubordinatePane } from "@/lib/utils/subordinatePane";
  import { type EntryInputDraft } from "@/lib/utils/promptInputs";
  import type {
    DocumentKind,
    EditableDocument,
    EntryBodyLanguage,
    LoreEntrySummary,
    PromptContextStrategy,
    PromptEntry,
    PromptEntrySummary,
    PromptInputDefinition,
    SnippetDependents,
    StructureDocument,
    ViewSpec,
  } from "@/lib/types";

  interface Props {
    // --- Inputs the parent owns (state lifted up; bind:'d by NodeEditor) ---
    rawBody?: string;
    entryInputDrafts?: EntryInputDraft[];
    // This editor's own workspace pane id (ADR-0062 D2) — the key for a
    // detached sub-tab pane (`subtab:<tabId>:<hostPaneId>`) and the parent
    // it's subordinate to.
    hostPaneId?: string | null;
    // The prompt's `offer_on` allow-list (ADR-0054 §4 / S4b), authored via the
    // OfferOnPicker below. Bound to NodeEditor's offerOnDraft; only rendered for
    // a conversation prompt (the surface ＋New lists).
    offerOn?: string[];
    // The prompt's instance `context_strategy` (ADR-0065 S3 / ADR-0062 D3),
    // authored via the PromptOutputEditor below. Bound to NodeEditor's
    // contextStrategyDraft; rendered for every non-snippet prompt (unlike
    // offerOn, which only shows for a conversation surface).
    contextStrategy?: PromptContextStrategy | null;
    // --- Read-only context from parent ---
    scene?: EditableDocument | null;
    documentKind?: DocumentKind;
    structure?: StructureDocument | null;
    // Research tree (sibling to manuscript) — threaded to the picker.
    researchStructure?: StructureDocument | null;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    availableScenes?: { id: string; title: string }[];
    rawBodyLanguage?: EntryBodyLanguage;
    loadedSceneId?: string | null;
    // Shared id factory + slug helper — same counters/rules as NodeEditor's
    // reseed path use, so clientIds don't collide and name slugification is
    // consistent across the two creation sites.
    nextInputDraftId: () => string;
    entrySlugify: (value: string) => string;
    // Lock the whole body for a built-in Library prompt (ADR-0049): the buffer
    // goes read-only and the declared-inputs editor is made `inert`, so the
    // author cannot type into a shipped node that the backend would 409 on
    // save. Clone it to edit instead.
    readOnly?: boolean;
    // Outbound: declared-inputs changed (#14 — replaces inputsChange dispatch).
    onInputsChange?: () => void;
    // Outbound: the offer_on allow-list changed (S4b) → parent emits its save.
    onOfferOnChange?: () => void;
    // Outbound: context_strategy.output changed (ADR-0062 D3) → parent emits its save.
    onContextStrategyChange?: () => void;
  }

  let {
    rawBody = $bindable(""),
    entryInputDrafts = $bindable([]),
    hostPaneId = null,
    offerOn = $bindable([]),
    contextStrategy = $bindable(null),
    scene = null,
    documentKind = "prompt",
    structure = null,
    researchStructure = null,
    loreEntries = [],
    promptEntries = [],
    availableScenes = [],
    rawBodyLanguage = "markdown",
    loadedSceneId = null,
    nextInputDraftId,
    entrySlugify,
    readOnly = false,
    onInputsChange,
    onOfferOnChange,
    onContextStrategyChange,
  }: Props = $props();

  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  const metadataSchema = $derived($metadataSchemaStore);

  const isPrompt = (): boolean => documentKind === "prompt" && !!scene;

  // The offer_on picker is gated to CONVERSATION prompts (ADR-0065 S3) — those
  // ＋New launches a conversation for: a handler-less `general` chat OR an
  // `extract_to_node` brainstorm. Reads the OPEN prompt node's own `context_strategy`
  // (never the entry-type's — invocability moved to the instance), gated by
  // `isSnippetType` first (a snippet is always import-only, whatever its config)
  // exactly like `promptSurfaceFor` — so an author never sees a targeting control
  // that provably does nothing on an inline prompt or a snippet.
  const promptStrategy = $derived(
    isPrompt() && scene ? ((scene as unknown as PromptEntry).context_strategy ?? null) : null,
  );
  const showOfferOnPicker = $derived(
    isPrompt() &&
      !!scene &&
      !isSnippetType(scene.entry_type) &&
      (!promptStrategy?.output?.handler || surfaceForStrategy(promptStrategy) === "conversation"),
  );

  // The output editor (ADR-0062 D3) is gated like offerOn's picker — non-snippet
  // prompts only (a snippet is import-only, whatever it carries) — but NOT
  // narrowed to the conversation surface: it's what AUTHORS the handler that
  // decides the surface in the first place.
  const showOutputEditor = $derived(
    isPrompt() && !!scene && !isSnippetType(scene.entry_type),
  );

  // --- Dependency advisory (ADR-0061 §5 / S3a) ---
  // "used by N prompts / M chats — changing these fields may affect them."
  // Fetched per open node: the count depends on OTHER prompts' `{% include %}`s,
  // not on edits to this body, so once per open is enough. Only snippets have
  // includers — a non-snippet prompt returns 0/0, so the note self-hides below
  // and no snippet-vs-prompt gate is needed here.
  //
  // Depends on `loadedSceneId` (+ the stable `documentKind`), NOT `scene`: the id
  // changes only on a node switch, whereas `scene` can be reassigned with the
  // same id on autosave/reactive updates (the case NodeEditor's
  // `scene.id !== loadedSceneId` guard absorbs). Reading `scene` here would
  // re-fire this effect — and its O(chats) backend scan — on every such edit.
  // The loaded id is captured so a slow response for a previous node is discarded.
  let dependents = $state<SnippetDependents | null>(null);
  $effect(() => {
    const id = loadedSceneId;
    dependents = null;
    if (!id || documentKind !== "prompt") return;
    let cancelled = false;
    api
      .getPromptDependents(id)
      .then((result) => {
        if (!cancelled) dependents = result;
      })
      .catch(() => {
        // Advisory only — a failed count degrades to no note, never an error.
        if (!cancelled) dependents = null;
      });
    return () => {
      cancelled = true;
    };
  });
  const dependentsNote = $derived(dependencyAdvisoryText(dependents));

  // --- Restore-default-body (for prompt sub-types with a non-empty
  //     default_body, e.g. roleplay). Visible only when the current body
  //     diverges, so a freshly-created prompt won't see noise. Click
  //     overwrites rawBody — CodeMirror keeps undo history, and the parent
  //     pane doesn't auto-save, so accidents are recoverable.
  const entryTypeDefaultBody = $derived(
    isPrompt() && metadataSchema && scene
      ? metadataSchema.entry_types[scene.entry_type]?.default_body ?? ""
      : "",
  );
  const canRestoreDefaultBody = $derived(
    entryTypeDefaultBody.length > 0 && rawBody !== entryTypeDefaultBody,
  );

  function restoreDefaultBody(): void {
    if (!canRestoreDefaultBody) return;
    rawBody = entryTypeDefaultBody;
  }

  // --- Soft-wrap toggle (editor preference, not stored on the entry) ---
  // Prompts are sentence-oriented markdown → wrap on by default. Snippets /
  // structure files / other code-shaped bodies → wrap off (column-significant).
  // The author can flip it per entry-type; the choice persists in localStorage
  // keyed by kind+entry_type, so the same prompt type remembers the override.
  const WRAP_PREF_KEY = "lwa.editor.lineWrap";

  function loadWrapPrefs(): Record<string, boolean> {
    try {
      const raw = localStorage.getItem(WRAP_PREF_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }

  let wrapPrefs: Record<string, boolean> = $state(loadWrapPrefs());

  const wrapPrefKey = $derived(`${documentKind}:${scene?.entry_type ?? ""}`);
  const wrapDefault = $derived(documentKind === "prompt");
  const lineWrapEnabled = $derived(wrapPrefs[wrapPrefKey] ?? wrapDefault);

  function toggleLineWrap(): void {
    const next = { ...wrapPrefs, [wrapPrefKey]: !lineWrapEnabled };
    wrapPrefs = next;
    try {
      localStorage.setItem(WRAP_PREF_KEY, JSON.stringify(next));
    } catch {
      // Preference is best-effort; a full/blocked localStorage just means the
      // toggle won't persist across reloads.
    }
  }

  // --- Cheatsheet popover ---
  let cheatsheetPopoverOpen = $state(false);
  let helpButtonEl: HTMLButtonElement | undefined = $state();
  let popoverPos = $state({ top: 0, right: 8 });

  function toggleCheatsheetPopover(): void {
    if (!cheatsheetPopoverOpen && helpButtonEl) {
      const r = helpButtonEl.getBoundingClientRect();
      // Match the CSS max-height (70vh) so we don't clip below the viewport;
      // open below the button if it fits, otherwise pin near the top of the
      // viewport with an 8px margin.
      const maxPopHeight = Math.round(window.innerHeight * 0.7);
      const desiredTop = Math.round(r.bottom + 6);
      const safeTop = Math.min(desiredTop, Math.max(8, window.innerHeight - maxPopHeight - 8));
      popoverPos = {
        top: safeTop,
        right: Math.max(8, Math.round(window.innerWidth - r.right)),
      };
    }
    cheatsheetPopoverOpen = !cheatsheetPopoverOpen;
  }

  // Gutter diagnostics for the CodeEditor — written by PromptPreviewPane's
  // render pipeline (bound below) and fed to the editor's `diagnostics` prop.
  let promptPreviewDiagnostics: {
    line: number;
    col?: number;
    severity: "error" | "warning";
    message: string;
  }[] = $state([]);

  // ADR-0061 §3 / S3b: the live effective inputs + provenance, bound out of
  // PromptPreviewPane (which resolves them on every body change, even collapsed),
  // so the Inputs editor's inherited tier tracks the edit buffer. The inherited
  // list is the effective inputs the resolver credited to a snippet, tagged with
  // that snippet's title from the roster.
  let promptEffectiveInputs: PromptInputDefinition[] = $state([]);
  let promptInputProvenance: Record<string, string> = $state({});
  const inheritedInputs = $derived(
    inheritedInputsFrom(promptEffectiveInputs, promptInputProvenance, promptEntries),
  );

  // --- Prompt editor sub-tabs (ADR-0062 §1/S2 Amendment 2 "D2") -----------
  // Three peer tabs — Template / Preview / Setup — each detachable into its
  // own subordinate workspace pane via a header glyph OR a drag-out gesture.
  // Docked tabs stay MOUNTED across switches (CSS-hidden, not {#if}) so a trip
  // to Setup never tears down CodeMirror's undo history or the live preview.
  type PromptTab = "template" | "preview" | "setup";
  const PROMPT_TABS: { id: PromptTab; label: string }[] = [
    { id: "template", label: "Template" },
    { id: "preview", label: "Preview" },
    { id: "setup", label: "Setup" },
  ];
  let detachedTabs = $state<PromptTab[]>([]);
  const isDetached = (tab: PromptTab): boolean => detachedTabs.includes(tab);
  const dockedTabs = $derived(PROMPT_TABS.filter((t) => !isDetached(t.id)));
  // Husk invariant: never detach the last docked tab — the editor pane can't
  // be left empty.
  const canDetach = $derived(dockedTabs.length > 1);

  let activePromptTab = $state<PromptTab>("template");
  // Keep the active tab a DOCKED one: if it detaches, fall to the first docked tab.
  $effect(() => {
    if (isDetached(activePromptTab) && dockedTabs.length > 0) activePromptTab = dockedTabs[0].id;
  });
  function selectPromptTab(tab: PromptTab): void {
    if (isDetached(tab)) return;
    activePromptTab = tab;
    cheatsheetPopoverOpen = false; // its trigger lives on the Template toolbar
  }

  // A detached tab's subordinate-pane id — ephemeral (workspaceLayout.serialize's
  // isEphemeralTab treats any `subtab:` id the same as the old `preview:` one):
  // it's a live view of this editor's draft state, reconstructed only while the
  // editor is mounted, so it's stripped on serialize and dropped on load.
  const subtabPaneId = (tab: PromptTab): string | null =>
    hostPaneId ? `subtab:${tab}:${hostPaneId}` : null;

  function detachTab(tab: PromptTab): void {
    const id = subtabPaneId(tab);
    if (!id || !hostPaneId || !canDetach || isDetached(tab)) return;
    detachedTabs = [...detachedTabs, tab];
    // Tile it beside the editor's own group — full height, to the right — and
    // tie its lifetime to this editor pane.
    openSubordinatePane(id, hostPaneId, () => reattachTab(tab), { beside: hostPaneId, edge: "right" });
  }

  function reattachTab(tab: PromptTab): void {
    detachedTabs = detachedTabs.filter((t) => t !== tab);
    const id = subtabPaneId(tab);
    if (id) closeSubordinatePane(id); // idempotent — also the pane's own onClose
  }

  // Drag a tab OUT of the strip to detach (secondary to the glyph, honors the
  // originally-expected gesture). Detaches only when the drag ends outside the
  // strip's rect, and only when canDetach — a click-without-drag still selects.
  let tabStripEl: HTMLDivElement | undefined = $state();
  let draggingTab: PromptTab | null = null;
  function onTabDragStart(e: DragEvent, tab: PromptTab): void {
    if (!canDetach) {
      e.preventDefault();
      return;
    }
    e.dataTransfer?.setData("text/plain", tab);
    draggingTab = tab;
  }
  function onTabDragEnd(e: DragEvent): void {
    const tab = draggingTab;
    draggingTab = null;
    const r = tabStripEl?.getBoundingClientRect();
    if (!tab || !r) return;
    const outside = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    if (outside) detachTab(tab);
  }

  // Fold every detached tab back if the doc stops being a prompt (the body
  // would render nothing), and drop all detached panes on teardown — the
  // editor-close cascade covers the common case, this covers CodeBodyView
  // unmounting while its pane stays open.
  $effect(() => {
    if (!isPrompt() && detachedTabs.length > 0) for (const tab of [...detachedTabs]) reattachTab(tab);
  });
  onDestroy(() => {
    for (const tab of detachedTabs) {
      const id = subtabPaneId(tab);
      if (id) closeSubordinatePane(id);
    }
  });

  // Resolve a tab id to its body snippet. Referenced here and from the detached
  // RegionRegistrar registrations below; the snippet bindings themselves are
  // declared in the markup, but Svelte hoists them into the component's scope.
  function bodyFor(tab: PromptTab): Snippet<[ViewSpec | undefined]> {
    return tab === "template" ? templateBody : tab === "preview" ? previewBody : setupBody;
  }

  // rawBody change propagation: CodeEditor's bind:value updates our
  // `rawBody`, which (because the parent uses bind:rawBody) updates the
  // parent's rawBody too. The parent has its own `$: if (rawBodyMode &&
  // rawBody !== lastEmittedRawBody) emitChange()` reactive that fires the
  // save event — no extra dispatch needed here.
</script>

{#if isPrompt()}
  <!-- ADR-0062 §1 / D2: the prompt editor is a three-tab shell — Template /
       Preview / Setup — each detachable into its own subordinate pane via the
       header glyph or a drag-out. One top-level element so it lands in
       .editor-panel's 1fr grid row. -->
  <div class="prompt-editor-shell">
    <div class="tab-strip" role="tablist" aria-label="Prompt editor sections" bind:this={tabStripEl}>
      {#each PROMPT_TABS as tab (tab.id)}
        {#if !isDetached(tab.id)}
          <div
            class="tab-strip-tab-wrap"
            role="presentation"
            class:active={activePromptTab === tab.id}
            draggable={canDetach}
            ondragstart={(e) => onTabDragStart(e, tab.id)}
            ondragend={onTabDragEnd}
          >
            <button
              type="button"
              class="tab-strip-tab"
              class:active={activePromptTab === tab.id}
              role="tab"
              aria-selected={activePromptTab === tab.id}
              onclick={() => selectPromptTab(tab.id)}
            >{tab.label}</button>
            {#if canDetach}
              <button
                type="button"
                class="tab-detach-glyph"
                title={`Detach ${tab.label} into its own pane`}
                aria-label={`Detach ${tab.label}`}
                onclick={() => detachTab(tab.id)}
              >
                <i class="ti ti-arrow-bar-to-right" aria-hidden="true"></i>
              </button>
            {/if}
          </div>
        {:else}
          <div class="tab-strip-tab-wrap detached">
            <span class="tab-strip-tab detached-label">{tab.label}</span>
            <button
              type="button"
              class="tab-detach-glyph"
              title={`Reattach ${tab.label}`}
              aria-label={`Reattach ${tab.label}`}
              onclick={() => reattachTab(tab.id)}
            >
              <i class="ti ti-arrow-bar-to-left" aria-hidden="true"></i>
            </button>
          </div>
        {/if}
      {/each}
    </div>

    <!-- Docked tabpanels stay MOUNTED across switches (CSS-hidden, not {#if})
         so CodeMirror's undo history and the live preview survive a trip to
         Setup. A detached tab is NOT rendered here — its body renders in the
         subordinate pane via the RegionRegistrar below. -->
    {#each PROMPT_TABS as tab (tab.id)}
      {#if !isDetached(tab.id)}
        <div
          class="prompt-tabpanel"
          class:hidden={activePromptTab !== tab.id}
          class:prompt-setup={tab.id === "setup"}
          role="tabpanel"
          aria-label={tab.label}
        >
          {@render bodyFor(tab.id)(undefined)}
        </div>
      {/if}
    {/each}

    {#if cheatsheetPopoverOpen}
    <div class="prompt-help-popover" role="dialog" aria-label="Variables and helpers" style="top: {popoverPos.top}px; right: {popoverPos.right}px;">
      <header class="prompt-help-popover-header">
        <strong>Variables &amp; helpers</strong>
        <small>what you can reference in <code>&lbrace;&lbrace; … &rbrace;&rbrace;</code> and <code>&lbrace;% … %&rbrace;</code></small>
        <button type="button" class="prompt-help-popover-close" aria-label="Close" onclick={() => (cheatsheetPopoverOpen = false)}>×</button>
      </header>
      <div class="prompt-cheatsheet-body">
        <section>
          <h4>Variables</h4>
          <dl>
            <dt><code>scene</code></dt>
            <dd>The target scene. <code>scene.title</code>, <code>scene.body</code>, <code>scene.entry_type</code>, <code>scene.&lt;field&gt;</code> for any field on the scene (e.g. <code>scene.summary</code>, <code>scene.pov.title</code>). Entity-ref fields auto-resolve.</dd>
            <dt><code>project</code></dt>
            <dd>Project info. <code>project.title</code>, <code>project.&lt;field&gt;</code> for any authored project field (e.g. <code>project.spelling</code>); <code>project.metadata</code> is the whole map.</dd>
            <dt><code>text_before</code> / <code>text_after</code></dt>
            <dd>Body markdown around the cursor in the current scene. Empty string when not dispatched from an editor.</dd>
            <dt><code>selection</code></dt>
            <dd>The selected text in the editor, or empty string.</dd>
            <dt><code>date</code></dt>
            <dd>Today as an ISO string (e.g. <code>2026-06-20</code>). Also <code>date.today</code> and <code>date.iso</code>.</dd>
            <dt><code>input.&lt;id&gt;</code></dt>
            <dd>The value of an input declared on this prompt (see the Inputs panel below).</dd>
          </dl>
        </section>
        <section>
          <h4>Helpers</h4>
          <dl>
            <dt><code>pov(scene)</code></dt>
            <dd>POV character as an EntryRef, or <code>None</code> when the scene has no <code>pov</code> ref.</dd>
            <dt><code>use(node[, "stable"|"volatile"])</code> / <code>use_lore()</code></dt>
            <dd>Select a node into context — the backend places, dedups, tiers and caches it (emits nothing). The optional hint biases its cache tier. <code>use_lore()</code> just enables the scene's implicit lore. You never paste lore text yourself.</dd>
            <dt><code>story_so_far(scene)</code></dt>
            <dd>XML <code>&lt;story_so_far&gt;</code> of prior scenes' summaries (scenes 1…n-1) in reading order.</dd>
            <dt><code>last_words(text, n)</code></dt>
            <dd>Trailing <code>n</code> words of a string. Pure helper — useful for continuation prompts.</dd>
            <dt><code>full_outline()</code></dt>
            <dd>Nested list of outline nodes (<code>.title</code>, <code>.summary</code>, <code>.children</code>) — the whole book's shape.</dd>
            <dt><code>full_text()</code></dt>
            <dd>Every scene's prose in manuscript order (<code>.title</code>, <code>.body</code>). Heavy.</dd>
            <dt><code>entry(x[, at=scene])</code> / <code>original(x)</code></dt>
            <dd>Resolve a node — <code>entry(x)</code> as of the prompt's scene (or <code>at=</code> another scene), <code>original(x)</code> at book-start. Walk its fields by attribute: <code>&lbrace;&lbrace; entry(scene.pov).allegiance &rbrace;&rbrace;</code>. Accepts an id, a ref, or a <code>context_pick</code> value — <code>&lbrace;&lbrace; entry(inputs.character).title &rbrace;&rbrace;</code>.</dd>
            <dt><code>fields(x)</code> / <code>type_name(x)</code></dt>
            <dd><code>fields(x)</code> is the full field roster of a node or type — each descriptor has <code>id</code>, <code>label</code>, <code>type</code>, <code>options</code>, <code>description</code>, <code>proposable</code>. <code>type_name(x)</code> is a type's human name.</dd>
            <dt><code>character_turns(scene, character)</code></dt>
            <dd>Reconstructs the scene as alternating chat turns for the Roleplay sub-type: focus character → <code>assistant</code> turns, others → <code>user</code> prefixed <code>[Name]:</code>, untagged narration → plain <code>user</code>. No markers yet → whole body as one user message. <strong>Use OUTSIDE any <code>&lbrace;% role %&rbrace;</code> block</strong> — emits its own role boundaries. See <code>docs/roleplay.md</code>.</dd>
          </dl>
        </section>
      </div>
    </div>
    {/if}
  </div>
{:else}
  <!-- Non-prompt code body (e.g. a snippet / structure file): just the editor. -->
  <div class="editor-wrap raw-body-wrap">
    <div class="raw-body-editor">
      {#key scene?.id}
        <CodeEditor bind:value={rawBody} language={rawBodyLanguage} lineWrapping={lineWrapEnabled} {readOnly} diagnostics={[]} />
      {/key}
    </div>
  </div>
{/if}

<!-- The three peer tab bodies, each defined once (ADR-0062 D2). Rendered
     inline (CSS-hidden when not active) while docked; registered under
     `subtab:<tabId>:<hostPaneId>` and rendered by RegionBody in a subordinate
     pane when detached. `_spec` is the RegionBody view-spec arg (unused — none
     of these is an explicit-view pane). -->
{#snippet templateBody(_spec: ViewSpec | undefined)}
  <div class="editor-wrap raw-body-wrap">
    <div class="raw-body-editor">
      <!-- Belt-and-braces (#368): keyed per document id so a CodeMirror
           instance's undo history and mount-fixed language extension can never
           span documents. No in-pane document switch exists today (one tab per
           document; panes are torn down on close), so this only guards a future
           pane-model change. It does NOT cover a same-id external reload (none
           exists for code bodies today) — that would need a state reset, not a
           remount, exactly like ProseBodyView's loadScene boundary. -->
      {#key scene?.id}
        <CodeEditor bind:value={rawBody} language={rawBodyLanguage} lineWrapping={lineWrapEnabled} {readOnly} diagnostics={promptPreviewDiagnostics} />
      {/key}
    </div>
    <div class="raw-body-toolbar">
      <button
        type="button"
        class="prompt-wrap-button"
        class:active={lineWrapEnabled}
        role="switch"
        aria-checked={lineWrapEnabled}
        title={lineWrapEnabled ? "Soft-wrap is on — long lines wrap to fit. Click to turn off." : "Soft-wrap is off — long lines scroll horizontally. Click to turn on."}
        aria-label="Toggle line wrapping"
        onclick={toggleLineWrap}
      >Wrap</button>
      {#if canRestoreDefaultBody && !readOnly}
        <button
          type="button"
          class="prompt-restore-default-button"
          title="Replace this body with the type's default template. Ctrl+Z to undo."
          aria-label="Restore default body"
          onclick={restoreDefaultBody}
        >Restore default body</button>
      {/if}
      <button
        type="button"
        class="prompt-help-button"
        bind:this={helpButtonEl}
        class:active={cheatsheetPopoverOpen}
        title="Variables & helpers — what you can reference in &lbrace;&lbrace; … &rbrace;&rbrace; and &lbrace;% … %&rbrace;"
        aria-label="Show variables and helpers reference"
        aria-expanded={cheatsheetPopoverOpen}
        onclick={toggleCheatsheetPopover}
      >?</button>
    </div>
  </div>
{/snippet}

{#snippet previewBody(_spec: ViewSpec | undefined)}
  <PromptPreviewPane
    fill
    bind:diagnostics={promptPreviewDiagnostics}
    bind:effectiveInputs={promptEffectiveInputs}
    bind:inputProvenance={promptInputProvenance}
    {rawBody}
    {scene}
    {documentKind}
    {structure}
    {researchStructure}
    {loreEntries}
    {promptEntries}
    {availableScenes}
    {loadedSceneId}
    outputHandler={promptStrategy?.output?.handler ?? ""}
  />
{/snippet}

{#snippet setupBody(_spec: ViewSpec | undefined)}
  <!-- Dependency advisory (ADR-0061 §5): a snippet whose fields other prompts /
       chats depend on. Advisory only, never a gate; absent for a prompt nothing
       includes (the count is 0/0). -->
  {#if dependentsNote}
    <p class="entry-inputs-dependents">
      <i class="ti ti-info-circle" aria-hidden="true"></i>
      Used by {dependentsNote} — changing these fields may affect them.
    </p>
  {/if}

  <!-- A Library prompt's declared inputs are shown but locked: `inert` blocks
       every control and drops the subtree from the tab order, so there is no
       edit that could 409 on save. Clone to edit. -->
  <div class="entry-inputs-host" class:read-only={readOnly} inert={readOnly || undefined}>
    <EntryInputsEditor
      bind:entryInputDrafts
      {inheritedInputs}
      {nextInputDraftId}
      {entrySlugify}
      {onInputsChange}
    />
  </div>

  {#if showOutputEditor}
    <!-- Locked (Library prompt) the same way as the inputs host: `inert` blocks
         interaction + drops it from the tab order; clone to edit. -->
    <div class="entry-inputs-host" class:read-only={readOnly} inert={readOnly || undefined}>
      <PromptOutputEditor
        bind:contextStrategy
        {metadataSchema}
        {readOnly}
        onChange={onContextStrategyChange}
      />
    </div>
  {/if}

  {#if showOfferOnPicker}
    <!-- Locked (Library prompt) the same way as the inputs host: `inert` blocks
         interaction + drops it from the tab order; clone to edit. -->
    <div class="entry-inputs-host" class:read-only={readOnly} inert={readOnly || undefined}>
      <OfferOnPicker
        bind:offerOn
        {metadataSchema}
        {readOnly}
        onChange={onOfferOnChange}
      />
    </div>
  {/if}
{/snippet}

<!-- Register each DETACHED tab's body into the panel registry, one
     RegionRegistrar per tab keyed by tab id: RegionRegistrar syncs its whole
     `regions` map once, on mount, so a single long-lived registrar can't pick
     up a later-detached sibling — an `{#each}` over `detachedTabs` mounts a
     fresh registrar exactly when a tab detaches and tears it down exactly when
     it reattaches. -->
{#if isPrompt() && hostPaneId}
  {#each detachedTabs as tab (tab)}
    {@const id = subtabPaneId(tab)}
    {#if id}
      <RegionRegistrar
        regions={{
          [id]: {
            title: PROMPT_TABS.find((t) => t.id === tab)!.label,
            body: bodyFor(tab),
            closable: true,
            onClose: () => reattachTab(tab),
          },
        }}
      />
    {/if}
  {/each}
{/if}

<style>
  /* --- Editor toolbar + help/cheatsheet popover, co-located from styles.css
     (#14). Child-DOM reaches use :global: .code-editor/.cm-editor (CodeEditor).
     The entry-inputs editor moved to EntryInputsEditor.svelte. --- */
  .raw-body-toolbar {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 5;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .prompt-help-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-2);
    font-size: var(--fs-sm);
    font-weight: 600;
    cursor: pointer;
    padding: 0;
    line-height: 1;
    box-shadow: var(--elev-1);
  }
  .prompt-help-button:hover,
  .prompt-help-button.active {
    background: var(--panel);
    border-color: var(--text-2);
    color: var(--text);
  }
  .prompt-restore-default-button,
  .prompt-wrap-button {
    display: inline-flex;
    align-items: center;
    height: 22px;
    padding: 0 10px;
    border-radius: 11px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-2);
    font-size: var(--fs-xs);
    font-weight: 500;
    cursor: pointer;
    line-height: 1;
    box-shadow: var(--elev-1);
  }
  .prompt-restore-default-button:hover,
  .prompt-wrap-button:hover {
    background: var(--panel);
    border-color: var(--text-2);
    color: var(--text);
  }
  .prompt-wrap-button.active {
    background: var(--accent-soft);
    border-color: var(--accent);
    color: var(--accent-deep);
  }
  .prompt-help-popover {
    position: fixed;
    width: min(720px, calc(100vw - 24px));
    max-height: 70vh;
    overflow-y: auto;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
    padding: 12px 16px;
    z-index: 100;
    font-size: var(--fs-md);
  }
  .prompt-help-popover-header {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin: 0 0 10px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--divider);
  }
  .prompt-help-popover-header > strong {
    color: var(--text);
    font-size: var(--fs-md);
  }
  .prompt-help-popover-header > small {
    color: var(--text-3);
    font-size: var(--fs-xs);
    flex: 1;
  }
  .prompt-help-popover-header > small > code {
    background: var(--inset);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 0 4px;
    font-family: var(--mono);
  }
  .prompt-help-popover-close {
    width: 22px;
    height: 22px;
    border-radius: 4px;
    border: none;
    background: transparent;
    cursor: pointer;
    font-size: var(--fs-xl);
    color: var(--text-3);
    padding: 0;
    line-height: 1;
  }
  .prompt-help-popover-close:hover {
    background: var(--panel);
    color: var(--text);
  }
  .prompt-cheatsheet-body {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-top: 8px;
  }
  .prompt-cheatsheet-body h4 {
    margin: 0 0 6px;
    font-size: var(--fs-sm);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-2);
  }
  .prompt-cheatsheet-body dl {
    margin: 0;
    display: grid;
    gap: 4px 8px;
  }
  .prompt-cheatsheet-body dt {
    margin: 0;
  }
  .prompt-cheatsheet-body dt > code {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 0 4px;
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--accent-deep);
  }
  .prompt-cheatsheet-body dd {
    margin: 0 0 6px;
    color: var(--text-2);
    font-size: var(--fs-sm);
    line-height: 1.45;
  }
  .prompt-cheatsheet-body dd > code {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 0 3px;
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--accent-deep);
  }
  @media (max-width: 720px) {
    .prompt-cheatsheet-body {
      grid-template-columns: 1fr;
    }
  }
  /* A locked (Library) prompt's inputs are dimmed to read as non-editable;
     `inert` on the element does the actual interaction blocking. */
  .entry-inputs-host.read-only {
    opacity: 0.6;
  }
  /* A quiet, advisory dependency note (ADR-0061 §5) — a writing-desk aside, not
     an alarm: muted text, small, an unobtrusive info glyph. */
  .entry-inputs-dependents {
    display: flex;
    align-items: baseline;
    gap: 6px;
    margin: 0 0 8px;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .entry-inputs-dependents > .ti {
    flex: none;
    align-self: center;
  }
  /* --- ADR-0062 §1/D2: three-tab shell, each tab detachable --- */
  .prompt-editor-shell {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    background: var(--surface);
  }
  .prompt-editor-shell > .tab-strip {
    flex: none;
    padding: 0 var(--sp-2);
  }
  /* A docked tab + its detach glyph, or a detached tab's muted placeholder +
     reattach glyph. Shares the .tab-strip-tab visual vocabulary; the wrap only
     adds the flex row + glyph-reveal behavior. */
  .tab-strip-tab-wrap {
    display: flex;
    align-items: center;
  }
  .tab-detach-glyph {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    margin-left: -2px;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    padding: 0;
    line-height: 1;
    font-size: var(--fs-xs);
    opacity: 0;
    transition: opacity var(--t-fast);
  }
  .tab-strip-tab-wrap:hover > .tab-detach-glyph,
  .tab-strip-tab-wrap.active > .tab-detach-glyph,
  .tab-strip-tab-wrap.detached > .tab-detach-glyph {
    opacity: 1;
  }
  .tab-detach-glyph:hover {
    background: var(--panel);
    color: var(--text);
  }
  /* A detached tab's placeholder — a muted, non-interactive label (selecting it
     does nothing; use the glyph to bring it back). */
  .tab-strip-tab-wrap.detached {
    opacity: 0.55;
  }
  .tab-strip-tab.detached-label {
    padding: 6px 12px;
    font-size: var(--fs-md);
    color: var(--text-3);
    cursor: default;
  }
  .prompt-tabpanel {
    flex: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .prompt-tabpanel.hidden {
    display: none;
  }
  .prompt-tabpanel > .editor-wrap {
    flex: 1;
    min-height: 0;
  }
  .prompt-setup {
    overflow-y: auto;
    padding: var(--sp-3);
    gap: var(--sp-2);
  }
  .raw-body-editor {
    display: grid;
    flex: 1;
    min-height: 200px;
  }
  .raw-body-editor :global(.code-editor) {
    display: grid;
    height: 100%;
    min-height: 0;
  }
  .raw-body-editor :global(.cm-editor) {
    height: 100%;
    min-height: 0;
  }
</style>
