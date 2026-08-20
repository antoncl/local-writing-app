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
  import CodeEditor from "@/components/widgets/CodeEditor.svelte";
  import EntryInputsEditor from "@/components/editor/body/EntryInputsEditor.svelte";
  import OfferOnPicker from "@/components/editor/body/OfferOnPicker.svelte";
  import PromptPreviewPane from "@/components/editor/body/PromptPreviewPane.svelte";
  import RegionRegistrar from "@/components/workspace/RegionRegistrar.svelte";
  import { closeSubordinatePane, openSubordinatePane } from "@/lib/utils/subordinatePane";
  import { type EntryInputDraft } from "@/lib/utils/promptInputs";
  import type {
    DocumentKind,
    EditableDocument,
    EntryBodyLanguage,
    LoreEntrySummary,
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
    // This editor's own workspace pane id (ADR-0062 S2) — the key for a detached
    // Preview pane (`preview:<hostPaneId>`) and the parent it's subordinate to.
    hostPaneId?: string | null;
    // The prompt's `offer_on` allow-list (ADR-0054 §4 / S4b), authored via the
    // OfferOnPicker below. Bound to NodeEditor's offerOnDraft; only rendered for
    // a conversation prompt (the surface ＋New lists).
    offerOn?: string[];
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
  }

  let {
    rawBody = $bindable(""),
    entryInputDrafts = $bindable([]),
    hostPaneId = null,
    offerOn = $bindable([]),
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

  // --- Prompt editor sub-tabs (ADR-0062 §1) -------------------------------
  // Edit = the code‖preview loop (side by side); Setup = Inputs + Offered-on,
  // off the main column. Both panels stay MOUNTED across switches (CSS-hidden,
  // not {#if}) so a trip to Setup never tears down CodeMirror's undo history or
  // the live preview. S2 will refine Edit into detachable Template/Preview
  // sub-tabs; S1 ships them as a fixed split (tabs-alone would break the loop).
  type PromptTab = "edit" | "setup";
  let activePromptTab = $state<PromptTab>("edit");
  function selectPromptTab(tab: PromptTab): void {
    activePromptTab = tab;
    cheatsheetPopoverOpen = false; // its trigger lives on the Edit toolbar
  }

  // Code column's share of the split width (preview gets the rest). Persisted
  // globally — a preferred balance is an author habit, not a per-prompt property.
  const SPLIT_PREF_KEY = "lwa.editor.promptSplit";
  function loadSplitRatio(): number {
    try {
      const raw = localStorage.getItem(SPLIT_PREF_KEY);
      const n = raw ? Number.parseFloat(raw) : Number.NaN;
      return Number.isFinite(n) && n >= 0.2 && n <= 0.8 ? n : 0.5;
    } catch {
      return 0.5;
    }
  }
  let codeFlex = $state(loadSplitRatio());
  let splitContainerEl: HTMLDivElement | undefined = $state();

  function startSplitDrag(event: MouseEvent): void {
    if (event.button !== 0) return;
    event.preventDefault();
    const container = splitContainerEl;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    // House pattern (AGENTS.md): document-level move/up, write the fraction live
    // for smooth drag, commit to localStorage on release.
    function onMove(e: MouseEvent): void {
      const frac = (e.clientX - rect.left) / rect.width;
      codeFlex = Math.max(0.2, Math.min(0.8, frac));
    }
    function onUp(): void {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      try {
        localStorage.setItem(SPLIT_PREF_KEY, String(codeFlex));
      } catch {
        // Best-effort — a blocked localStorage just means it won't persist.
      }
    }
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  // --- Preview detach (ADR-0062 S2) ---------------------------------------
  // The Preview is defined once as the `previewPane` snippet below. Docked, it
  // renders inline in the split; detached, the SAME snippet is registered under
  // `preview:<hostPaneId>` and RegionBody renders it in a subordinate workspace
  // pane beside the editor. Svelte 5 carries the snippet's reactive reads across
  // that boundary (the SchemaPanes pattern), so a detached preview stays live
  // as-you-type and its bound-out signals (diagnostics / effective-inputs) keep
  // feeding the docked gutter and Setup tab — no per-document store needed. The
  // pane is subordinate (closes with the editor) and ephemeral (never restored).
  const previewPaneId = $derived(hostPaneId ? `preview:${hostPaneId}` : null);
  let previewDetached = $state(false);

  function detachPreview(): void {
    const id = previewPaneId;
    if (!id || !hostPaneId) return;
    previewDetached = true;
    // Tile it to the right of the editor's own group — full height and width
    // beside the code — and tie its lifetime to this editor pane.
    openSubordinatePane(id, hostPaneId, reattachPreview, { beside: hostPaneId, edge: "right" });
  }

  function reattachPreview(): void {
    previewDetached = false;
    if (previewPaneId) closeSubordinatePane(previewPaneId);
  }

  // Guardrails: if the pane's document is swapped for a non-prompt while the
  // preview is detached, fold it back (the snippet would render nothing). And on
  // teardown, drop the pane + link — the editor-close cascade covers the common
  // case, this covers CodeBodyView unmounting while its pane stays open.
  $effect(() => {
    if (previewDetached && !isPrompt()) reattachPreview();
  });
  onDestroy(() => {
    if (previewPaneId) closeSubordinatePane(previewPaneId);
  });

  // rawBody change propagation: CodeEditor's bind:value updates our
  // `rawBody`, which (because the parent uses bind:rawBody) updates the
  // parent's rawBody too. The parent has its own `$: if (rawBodyMode &&
  // rawBody !== lastEmittedRawBody) emitChange()` reactive that fires the
  // save event — no extra dispatch needed here.
</script>

{#if isPrompt()}
  <!-- ADR-0062 §1: the prompt editor is a sub-tabbed shell. Edit holds the
       code‖preview loop side by side; Setup holds Inputs + Offered-on off the
       main column. One top-level element so it lands in .editor-panel's 1fr
       grid row and drives its own internal split. -->
  <div class="prompt-editor-shell">
    <div class="tab-strip" role="tablist" aria-label="Prompt editor sections">
      <button
        type="button"
        class="tab-strip-tab"
        class:active={activePromptTab === "edit"}
        role="tab"
        aria-selected={activePromptTab === "edit"}
        onclick={() => selectPromptTab("edit")}
      >Edit</button>
      <button
        type="button"
        class="tab-strip-tab"
        class:active={activePromptTab === "setup"}
        role="tab"
        aria-selected={activePromptTab === "setup"}
        onclick={() => selectPromptTab("setup")}
      >Setup</button>
    </div>

    <!-- Edit panel — kept MOUNTED across tab switches (CSS-hidden, not {#if}) so
         CodeMirror's undo history and the live preview survive a trip to Setup. -->
    <div class="prompt-tabpanel" class:hidden={activePromptTab !== "edit"} role="tabpanel" aria-label="Edit">
      <div class="prompt-split" bind:this={splitContainerEl}>
        <div class="prompt-split-code" style="flex-grow: {previewDetached ? 1 : codeFlex};">
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
      {#if previewPaneId}
        <button
          type="button"
          class="prompt-wrap-button"
          class:active={previewDetached}
          title={previewDetached
            ? "Reattach the preview into this editor's split."
            : "Detach the preview into its own pane beside the editor."}
          aria-label={previewDetached ? "Reattach preview" : "Detach preview"}
          onclick={previewDetached ? reattachPreview : detachPreview}
        >{previewDetached ? "Reattach preview" : "Detach preview"}</button>
      {/if}
            </div>
          </div>
        </div>
        {#if !previewDetached}
          <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
          <div
            class="prompt-split-gutter"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize preview"
            onmousedown={startSplitDrag}
          ></div>
          <div class="prompt-split-preview" style="flex-grow: {1 - codeFlex};">
            {@render previewPane(undefined)}
          </div>
        {/if}
      </div>
    </div>

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

    <!-- Setup panel — Inputs + Offered-on, off the main loop (ADR-0062 §1).
         Also kept mounted (CSS-hidden) so its drafts don't re-seed on switch. -->
    <div class="prompt-tabpanel prompt-setup" class:hidden={activePromptTab !== "setup"} role="tabpanel" aria-label="Setup">
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
    </div>
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

<!-- The Preview, defined once (ADR-0062 S2). Rendered inline in the split when
     docked; registered under `preview:<hostPaneId>` and rendered by RegionBody
     in a subordinate pane when detached. `_spec` is the RegionBody view-spec arg
     (unused — this is not an explicit-view pane). -->
{#snippet previewPane(_spec: ViewSpec | undefined)}
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
  />
{/snippet}

{#if isPrompt() && previewPaneId}
  <RegionRegistrar
    regions={{
      [previewPaneId]: { title: "Preview", body: previewPane, closable: true, onClose: reattachPreview },
    }}
  />
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
  /* --- ADR-0062 §1: sub-tabbed shell + code‖preview split --- */
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
  .prompt-split {
    flex: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: row;
  }
  .prompt-split-code,
  .prompt-split-preview {
    flex-basis: 0;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .prompt-split-code > .editor-wrap {
    flex: 1;
    min-height: 0;
  }
  /* The drag handle between code and preview — the shell's gutter vocabulary
     (var(--sp-1) bar, accent on hover), one column-resize cursor. */
  .prompt-split-gutter {
    flex: none;
    width: var(--sp-1);
    cursor: col-resize;
    background: var(--divider);
    transition: background var(--t-fast);
  }
  .prompt-split-gutter:hover {
    background: var(--accent);
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
