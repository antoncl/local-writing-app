<!--
  CodeBodyView — body region for entry types with body_shape === "code"
  (today: prompts and snippets). Owns the CodeMirror editor and, for
  prompts, the help button + cheatsheet popover + declared-inputs
  editor + the inline preview pane. Sibling of ProseBodyView (still
  inline in NodeEditor today; will extract in 2d). See
  decisions-node-editor-modularization (Phase 2).

  State owned here is presentational only — cheatsheet open/closed,
  preview pane open/closed and height, input drag indices, the
  preview render result + debounce timer. The two persisted pieces
  (rawBody, entryInputDrafts) are bind:'d to the parent so the
  parent's save logic owns serialization.
-->
<script lang="ts">
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import CodeEditor from "@/components/widgets/CodeEditor.svelte";
  import EntryInputsEditor from "@/components/editor/body/EntryInputsEditor.svelte";
  import PromptInputField from "@/components/widgets/PromptInputField.svelte";
  import { api } from "@/lib/api";
  import { formatCostEur, formatTokens } from "@/lib/utils/money";
  import { coerceInputValue, type EntryInputDraft } from "@/lib/utils/promptInputs";
  import type {
    AIPreviewResponse,
    DocumentKind,
    EditableDocument,
    EntryBodyLanguage,
    LoreEntrySummary,
    MetadataSchema,
    PreviewErrorInfo,
    PromptEntrySummary,
    PromptInputDefinition,
    StructureDocument,
  } from "@/lib/types";

  interface Props {
    // --- Inputs the parent owns (state lifted up; bind:'d by NodeEditor) ---
    rawBody?: string;
    entryInputDrafts?: EntryInputDraft[];
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
    // Outbound: declared-inputs changed (#14 — replaces inputsChange dispatch).
    onInputsChange?: () => void;
  }

  let {
    rawBody = $bindable(""),
    entryInputDrafts = $bindable([]),
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
    onInputsChange,
  }: Props = $props();

  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  const metadataSchema = $derived($metadataSchemaStore);

  const isPrompt = (): boolean => documentKind === "prompt" && !!scene;

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

  // --- Inline prompt preview (prompts only) ---
  let promptPreviewSceneId = $state("");
  let promptPreviewInputDrafts: Record<string, string> = $state({});
  let promptPreviewResult: AIPreviewResponse | null = $state(null);
  let promptPreviewRunning = $state(false);
  let promptPreviewError: string | null = $state(null);
  let promptPreviewPaneHeight = $state(280); // px; persisted only in memory for now.
  let promptPreviewCollapsed = $state(true);
  let promptPreviewDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let promptPreviewLastRenderKey = "";
  // Diagnostics pinned in the CodeEditor gutter — driven by render errors.
  // Internal state (NodeEditor doesn't bind it) — was a write-only export.
  let promptPreviewDiagnostics: {
    line: number;
    col?: number;
    severity: "error" | "warning";
    message: string;
  }[] = $state([]);

  // Inputs are per-entry. Read scene.inputs directly so this reactive
  // re-fires when the entry's inputs change via the editor section below.
  const promptPreviewDeclaredInputs = $derived(
    isPrompt() ? ((scene as unknown as PromptEntrySummary).inputs ?? []) : [],
  );

  // Reset preview when the underlying entry changes. The default-filler
  // reactive below idempotently seeds any input that's still missing — needed
  // because the schema (which carries the input definitions) can arrive in a
  // different tick from the entry itself.
  let promptPreviewSeededEntryId: string | null = null;
  $effect(() => {
    if (loadedSceneId && loadedSceneId !== promptPreviewSeededEntryId) {
      promptPreviewResult = null;
      promptPreviewError = null;
      promptPreviewLastRenderKey = "";
      promptPreviewDiagnostics = [];
      promptPreviewInputDrafts = seedInputDrafts(promptPreviewDeclaredInputs);
      promptPreviewSeededEntryId = loadedSceneId;
    }
  });
  $effect(() => {
    let changed = false;
    const next: Record<string, string> = { ...promptPreviewInputDrafts };
    for (const input of promptPreviewDeclaredInputs) {
      if (next[input.name] === undefined) {
        // No boolean→"false" fallback: an input with no declared default
        // seeds empty (unset), so the preview render fails fast on its
        // reference instead of silently treating it as false (#24).
        next[input.name] =
          input.default !== undefined && input.default !== null
            ? String(input.default)
            : "";
        changed = true;
      }
    }
    if (changed) promptPreviewInputDrafts = next;
  });

  const promptPreviewMissingRequired = $derived(
    promptPreviewDeclaredInputs.filter((i) => {
      if (!i.required) return false;
      const v = promptPreviewInputDrafts[i.name];
      return v === undefined || v === null || (typeof v === "string" && !v.trim());
    }),
  );

  /** Render PreviewErrorInfo into a user-facing message for the inline
   * preview pane. Always returns a string — silent suppression hides the
   * fact that the render stopped at the first undefined and tricked the
   * author into thinking later refs were OK.
   *
   * Three undefined-name cases worth distinguishing:
   *   - declared & currently empty (required)  → "fill it in" (render blocked here)
   *   - declared & currently empty (optional)  → "fill in or guard with `is defined`"
   *   - undeclared                             → "no such input" — real authoring bug
   */
  function friendlyTemplateError(
    err: PreviewErrorInfo,
    declared: PromptInputDefinition[],
    drafts: Record<string, string>,
  ): string {
    if (err.kind === "undefined") {
      const missing = err.undefined_name;
      if (missing) {
        const decl = declared.find((d) => d.name === missing);
        if (decl) {
          const draft = drafts[missing];
          const isEmpty =
            draft === undefined || draft === null || (typeof draft === "string" && !draft.trim());
          if (isEmpty) {
            if (decl.required) {
              return `Preview blocked: required input \`${decl.label || missing}\` isn't set. Fill it in above to render the rest of the template.`;
            }
            return `Template references \`input.${missing}\`, but the input is optional and no value is set. Either fill it in above, or guard with \`{% if input.${missing} is defined %}…{% endif %}\`.`;
          }
          // Declared and filled — shouldn't normally happen; fall through.
        } else {
          const declaredNames = declared.map((d) => d.name);
          const inputsList = declaredNames.length
            ? ` Available inputs: ${declaredNames.map((n) => "input." + n).join(", ")}.`
            : " No inputs are declared on this prompt — add one in the Detail Type editor first.";
          return `Your template references \`input.${missing}\` but there's no input named "${missing}".${inputsList}`;
        }
      }
    }
    if (err.kind === "scene_not_found") {
      return `${err.message} Pick a different target scene in the preview controls above.`;
    }
    return err.message;
  }

  function seedInputDrafts(declared: PromptInputDefinition[]): Record<string, string> {
    const drafts: Record<string, string> = {};
    for (const input of declared) {
      // Unset stays empty regardless of type (no boolean→"false") so an
      // undefined default surfaces as a fail-fast undefined reference (#24).
      drafts[input.name] =
        input.default !== undefined && input.default !== null ? String(input.default) : "";
    }
    return drafts;
  }

  // Fallback scene binding for the preview's `scene` variable. The user
  // controls the explicit binding by marking a scene ★ in any context_pick
  // input — that wins backend-side (preview.py:_find_marked_target_scene_id).
  $effect(() => {
    if (isPrompt() && !promptPreviewSceneId && availableScenes.length > 0) {
      promptPreviewSceneId = availableScenes[0].id;
    }
  });

  // Auto re-render on any preview-relevant change. Debounced.
  $effect(() => {
    schedulePromptPreviewRender(rawBody, promptPreviewSceneId, JSON.stringify(promptPreviewInputDrafts));
  });

  function schedulePromptPreviewRender(_body: string, _scene: string, _inputs: string): void {
    if (!isPrompt()) return;
    if (promptPreviewDebounceTimer) clearTimeout(promptPreviewDebounceTimer);
    promptPreviewDebounceTimer = setTimeout(() => {
      promptPreviewDebounceTimer = null;
      void runPromptPreview();
    }, 800);
  }

  async function runPromptPreview(): Promise<void> {
    if (!isPrompt()) return;
    if (!rawBody.trim()) {
      promptPreviewResult = null;
      promptPreviewError = null;
      promptPreviewLastRenderKey = "";
      return;
    }
    const inputs: Record<string, unknown> = {};
    for (const declared of promptPreviewDeclaredInputs) {
      const raw = promptPreviewInputDrafts[declared.name] ?? "";
      const coerced = coerceInputValue(raw, declared.type);
      if (coerced !== null && coerced !== "") inputs[declared.name] = coerced;
    }
    const key = JSON.stringify({ rawBody, promptPreviewSceneId, inputs });
    if (key === promptPreviewLastRenderKey && !promptPreviewError) return;
    promptPreviewLastRenderKey = key;
    promptPreviewRunning = true;
    try {
      const result = await api.aiPreview({
        template_source: rawBody,
        target_scene_id: promptPreviewSceneId || "",
        inputs,
        commit: false,
      });
      promptPreviewResult = result;
      // Render errors come back as 200 + result.error (the endpoint is
      // exploratory; auto-firing it before required inputs are filled
      // would otherwise look like an HTTP failure). HttpError is still
      // possible for non-render failures (project not open, 5xx, etc.).
      if (result.error) {
        promptPreviewError = friendlyTemplateError(
          result.error,
          promptPreviewDeclaredInputs,
          promptPreviewInputDrafts,
        );
        const line = result.error.line;
        promptPreviewDiagnostics = typeof line === "number" && line > 0
          ? [{
              line,
              col: typeof result.error.col === "number" && result.error.col > 0
                ? result.error.col
                : undefined,
              severity: "error",
              message: promptPreviewError ?? result.error.message,
            }]
          : [];
      } else {
        promptPreviewError = null;
        promptPreviewDiagnostics = [];
      }
    } catch (e) {
      // Falls here only for non-render failures (e.g. project closed, 5xx).
      promptPreviewError = (e as Error).message || "Render failed.";
      promptPreviewDiagnostics = [];
    } finally {
      promptPreviewRunning = false;
    }
  }

  function startPromptPreviewResize(event: MouseEvent): void {
    if (event.button !== 0) return;
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = promptPreviewPaneHeight;
    function onMove(e: MouseEvent) {
      // Drag UP shrinks editor / grows preview. Clamp so neither collapses.
      promptPreviewPaneHeight = Math.max(120, Math.min(800, startHeight + (startY - e.clientY)));
    }
    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    }
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  // rawBody change propagation: CodeEditor's bind:value updates our
  // `rawBody`, which (because the parent uses bind:rawBody) updates the
  // parent's rawBody too. The parent has its own `$: if (rawBodyMode &&
  // rawBody !== lastEmittedRawBody) emitChange()` reactive that fires the
  // save event — no extra dispatch needed here.
</script>

<div class="editor-wrap raw-body-wrap">
  <div class="raw-body-editor">
    <CodeEditor bind:value={rawBody} language={rawBodyLanguage} lineWrapping={lineWrapEnabled} diagnostics={isPrompt() ? promptPreviewDiagnostics : []} />
  </div>

  {#if isPrompt()}
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
      {#if canRestoreDefaultBody}
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
  {/if}
</div>

{#if isPrompt()}
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
            <dt><code>project</code> / <code>novel</code></dt>
            <dd>Project info (title, root path, AI policy). Both names point to the same value.</dd>
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
            <dt><code>relevant_lore(scene, mode="implicit", partition="all")</code></dt>
            <dd>XML <code>&lt;lore&gt;</code> block of entries in scope for the scene. Modes: <code>implicit</code>, <code>explicit</code>, <code>pinned_only</code>. Partitions (session-bound): <code>all</code>, <code>stable</code>, <code>volatile</code>.</dd>
            <dt><code>scenes_before(scene)</code></dt>
            <dd>XML <code>&lt;story_so_far&gt;</code> of prior scenes' summaries in manuscript order.</dd>
            <dt><code>last_words(text, n)</code></dt>
            <dd>Trailing <code>n</code> words of a string. Pure helper — useful for continuation prompts.</dd>
            <dt><code>full_outline()</code></dt>
            <dd>Nested list of outline nodes (<code>.title</code>, <code>.summary</code>, <code>.children</code>) — the whole book's shape.</dd>
            <dt><code>full_text()</code></dt>
            <dd>Every scene's prose in manuscript order (<code>.title</code>, <code>.body</code>). Heavy.</dd>
            <dt><code>entry(id_or_ref)</code></dt>
            <dd>Wrap a raw entry id as an EntryRef so you can walk its fields: <code>&lbrace;&lbrace; entry(scene.metadata.pov).title &rbrace;&rbrace;</code>. Also accepts the value of a <code>context_pick</code> input (first picked ref wins) — <code>&lbrace;&lbrace; entry(input.character).title &rbrace;&rbrace;</code>.</dd>
            <dt><code>character_thread(scene, character)</code></dt>
            <dd>Per-character chat thread for the Roleplay sub-type. Walks the scene body's <code>data-character</code> spans: focus character → <code>assistant</code> turns, others → <code>user</code> prefixed <code>[Name]:</code>, untagged narration → plain <code>user</code>. No markers yet → whole body as one user message. <strong>Use OUTSIDE any <code>&lbrace;% role %&rbrace;</code> block</strong> — emits its own role boundaries. See <code>docs/roleplay.md</code>.</dd>
          </dl>
        </section>
      </div>
    </div>
  {/if}

  <EntryInputsEditor
    bind:entryInputDrafts
    {nextInputDraftId}
    {entrySlugify}
    {onInputsChange}
  />

  <!-- Vertical split: editor above gets the remaining space when the
       preview is expanded; collapsed by default so the body editor is
       the primary focus. The header toggles open/closed; the handle
       between editor and preview resizes the preview when expanded. -->
  {#if !promptPreviewCollapsed}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div
      class="prompt-preview-resize"
      role="separator"
      aria-orientation="horizontal"
      aria-label="Resize prompt preview"
      onmousedown={startPromptPreviewResize}
    ></div>
  {/if}
  <section
    class="prompt-preview-pane"
    class:collapsed={promptPreviewCollapsed}
    style={promptPreviewCollapsed ? "" : `height: ${promptPreviewPaneHeight}px;`}
  >
    <header class="prompt-preview-pane-header">
      <button
        type="button"
        class="prompt-preview-toggle"
        aria-expanded={!promptPreviewCollapsed}
        onclick={() => (promptPreviewCollapsed = !promptPreviewCollapsed)}
      >
        <span class="prompt-preview-caret" aria-hidden="true">{promptPreviewCollapsed ? "▸" : "▾"}</span>
        <strong>Preview</strong>
      </button>
      <div class="prompt-preview-pane-meta">
        {#if promptPreviewRunning}
          <span class="prompt-preview-status">rendering…</span>
        {:else if promptPreviewResult}
          <span class="prompt-preview-status">{promptPreviewResult.messages.length} msg · {promptPreviewResult.char_count} chars</span>
          {#if promptPreviewResult.estimated_tokens}
            <span class="prompt-preview-cost" title="Estimated tokens (universal tokenizer; provider-specific counts may vary slightly).">
              · {formatTokens(promptPreviewResult.estimated_tokens)} tok
            </span>
          {/if}
          {#if promptPreviewResult.estimated_cost_usd != null}
            <span class="prompt-preview-cost" title="Estimated input cost (output cost depends on the response; not included).">
              · {formatCostEur(promptPreviewResult.estimated_cost_usd)}
            </span>
          {/if}
        {/if}
        {#if !promptPreviewCollapsed}
          <button type="button" disabled={promptPreviewRunning || !rawBody.trim()} onclick={runPromptPreview}>
            {promptPreviewRunning ? "Rendering…" : "Render now"}
          </button>
        {/if}
      </div>
    </header>

    {#if !promptPreviewCollapsed}
      <div class="prompt-preview-pane-controls">
        {#if promptPreviewDeclaredInputs.length > 0}
          <div class="prompt-preview-inputs">
            <div class="prompt-preview-inputs-heading">
              Inputs
              <small>{promptPreviewDeclaredInputs.length}</small>
              <small class="prompt-preview-inputs-hint">use in template as <code>&lbrace;&lbrace; input.&lt;name&gt; &rbrace;&rbrace;</code></small>
            </div>
            {#each promptPreviewDeclaredInputs as inputDef (inputDef.name)}
              {@const draft = promptPreviewInputDrafts[inputDef.name]}
              {@const isMissing = inputDef.required && (draft === undefined || draft === null || (typeof draft === "string" && !draft.trim()))}
              <label class="prompt-preview-field" class:missing-required={isMissing}>
                <span class="prompt-preview-field-label">
                  <span class="prompt-preview-field-name">
                    {inputDef.label || inputDef.name}{#if inputDef.required}<span class="required-marker"> *</span>{/if}
                  </span>
                  <button
                    type="button"
                    class="prompt-preview-field-accessor"
                    title="Click to copy"
                    onclick={(e) => { e.preventDefault(); navigator.clipboard?.writeText(`{{ input.${inputDef.name} }}`).catch(() => {}); }}
                  ><code>&lbrace;&lbrace; input.{inputDef.name} &rbrace;&rbrace;</code></button>
                </span>
                <PromptInputField
                  input={inputDef}
                  value={draft ?? ""}
                  excludeId={scene?.id ?? null}
                  ariaLabel={inputDef.label || inputDef.name}
                  structure={structure}
                  researchStructure={researchStructure}
                  loreEntries={loreEntries}
                  promptEntries={promptEntries}
                  on:change={(event) => promptPreviewInputDrafts = {...promptPreviewInputDrafts, [inputDef.name]: event.detail.value}}
                />
              </label>
            {/each}
          </div>
        {/if}
      </div>

      {#if promptPreviewResult && promptPreviewResult.cache_blocks && promptPreviewResult.cache_blocks.length > 1 && promptPreviewResult.caching_style === "explicit"}
        <div class="prompt-preview-cache-strip" title="Per-cache-block token sizes. The first segment is the cacheable prefix.">
          {#each promptPreviewResult.cache_blocks as block, i}
            <span class="prompt-preview-cache-chip" class:cache-strip-break={block.cache_break_after}>
              {block.label} {formatTokens(block.tokens)}
            </span>
            {#if i < promptPreviewResult.cache_blocks.length - 1}<span class="prompt-preview-cache-sep">·</span>{/if}
          {/each}
        </div>
      {/if}

      <div class="prompt-preview-pane-body">
        {#if promptPreviewError}
          <p class="prompt-preview-error">{promptPreviewError}</p>
        {/if}
        {#if promptPreviewMissingRequired.length > 0}
          <p class="prompt-preview-required-notice">
            {promptPreviewMissingRequired.length} required input{promptPreviewMissingRequired.length === 1 ? "" : "s"} empty:
            {promptPreviewMissingRequired.map((i) => i.label || i.name).join(", ")} — fill them in above to render the preview.
          </p>
        {/if}

        {#if !rawBody.trim()}
          <p class="prompt-preview-empty muted">Type a template above to see the rendered output here.</p>
        {:else if promptPreviewResult}
          {#if promptPreviewResult.warnings.length > 0}
            <div class="prompt-preview-warnings">
              <strong>Warnings</strong>
              {#each promptPreviewResult.warnings as warning}
                <p>{warning}</p>
              {/each}
            </div>
          {/if}
          {#each promptPreviewResult.messages as message}
            <div class="prompt-preview-message prompt-preview-message-{message.role}">
              <header class="prompt-preview-message-role">{message.role}</header>
              {#each message.blocks as block}
                <pre class="prompt-preview-block">{block.text}</pre>
                {#if block.cache_break_after}
                  <div class="prompt-preview-cache-break" aria-label="cache breakpoint">cache_break</div>
                {/if}
              {/each}
            </div>
          {/each}
        {:else if !promptPreviewRunning && !promptPreviewError}
          <p class="prompt-preview-empty muted">Waiting for first render…</p>
        {/if}
      </div>
    {/if}
  </section>
{/if}

<style>
  /* --- Inline prompt-author preview pane, co-located from styles.css (#14).
     Form controls under .prompt-preview-field are rendered by the
     PromptInputField child → :global reach. --- */
  .prompt-preview-resize {
    height: 6px;
    cursor: ns-resize;
    background: var(--panel);
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .prompt-preview-resize:hover {
    background: var(--tier2);
  }
  .prompt-preview-pane {
    display: grid;
    grid-template-rows: auto auto 1fr;
    min-height: 120px;
    background: var(--inset);
    font-size: 13px;
    border-top: 1px solid var(--border);
    overflow: hidden;
  }
  .prompt-preview-pane.collapsed {
    grid-template-rows: auto;
    min-height: 0;
    height: auto;
  }
  .prompt-preview-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    background: transparent;
    border: none;
    padding: 0;
    cursor: pointer;
    color: var(--text);
    font: inherit;
  }
  .prompt-preview-toggle:hover {
    color: var(--accent-deep);
  }
  .prompt-preview-toggle > strong {
    font-size: 13px;
    color: inherit;
  }
  .prompt-preview-caret {
    display: inline-block;
    width: 12px;
    text-align: center;
    font-size: 10px;
    color: var(--text-3);
  }
  .prompt-preview-pane-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 6px 12px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
  }
  .prompt-preview-pane-meta {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .prompt-preview-status {
    font-size: 11px;
    color: var(--text-3);
  }
  .prompt-preview-pane-controls {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 8px;
    padding: 6px 12px;
    border-bottom: 1px solid var(--border);
  }
  .prompt-preview-field {
    display: grid;
    gap: 2px;
    font-size: 11px;
    color: var(--text-2);
  }
  .prompt-preview-field > span {
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 10px;
    color: var(--text-3);
  }
  .prompt-preview-field > :global(input),
  .prompt-preview-field > :global(select),
  .prompt-preview-field > :global(textarea) {
    padding: 3px 6px;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 12px;
    background: var(--surface);
  }
  .prompt-preview-field > :global(textarea) {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    resize: vertical;
  }
  .prompt-preview-inputs {
    flex-basis: 100%;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 6px 10px;
    padding: 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
  }
  .prompt-preview-inputs-heading {
    grid-column: 1 / -1;
    display: flex;
    align-items: baseline;
    gap: 6px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3);
  }
  .prompt-preview-inputs-heading > small {
    color: var(--text-3);
    font-weight: 400;
  }
  .prompt-preview-inputs-hint {
    margin-left: auto;
    text-transform: none;
    letter-spacing: 0;
    font-size: 11px;
    color: var(--text-3);
  }
  .prompt-preview-inputs-hint > code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 0 4px;
  }
  .prompt-preview-field-label {
    display: flex;
    align-items: baseline;
    gap: 6px;
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3);
  }
  .prompt-preview-field-name {
    text-transform: uppercase;
  }
  .prompt-preview-field-accessor {
    margin-left: auto;
    background: transparent;
    border: 1px solid transparent;
    color: var(--text-2);
    cursor: pointer;
    padding: 0;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11px;
    font-weight: 400;
    text-transform: none;
    letter-spacing: 0;
  }
  .prompt-preview-field-accessor > code {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 0 4px;
    white-space: nowrap;
  }
  .prompt-preview-field-accessor:hover > code {
    background: var(--accent-soft);
    border-color: var(--accent);
  }
  .prompt-preview-field.missing-required > :global(input),
  .prompt-preview-field.missing-required > :global(select),
  .prompt-preview-field.missing-required > :global(textarea) {
    border-color: var(--danger-border);
    background: var(--danger-soft);
  }
  .prompt-preview-field .required-marker {
    color: var(--danger);
  }
  .prompt-preview-required-notice {
    margin: 0;
    padding: 6px 10px;
    background: var(--star-soft);
    border: 1px solid var(--star-border);
    border-radius: 4px;
    color: var(--star);
    font-size: 12px;
    line-height: 1.45;
  }
  .prompt-preview-pane-body {
    overflow: auto;
    padding: 8px 12px;
    display: grid;
    gap: 8px;
    align-content: start;
    background: var(--surface);
  }
  .prompt-preview-empty {
    margin: 0;
    font-size: 12px;
  }
  .prompt-preview-error {
    margin: 8px 0 0;
    padding: 6px 10px;
    background: var(--danger-soft);
    border: 1px solid var(--danger-border);
    border-radius: 4px;
    color: var(--danger);
    font-size: 12px;
    line-height: 1.45;
  }
  .prompt-preview-warnings {
    padding: 6px 10px;
    background: var(--star-soft);
    border: 1px solid var(--star-border);
    border-radius: 4px;
    color: var(--star);
    font-size: 12px;
  }
  .prompt-preview-warnings > p {
    margin: 4px 0 0;
  }
  .prompt-preview-message {
    display: grid;
    gap: 4px;
    padding: 6px 10px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
  }
  .prompt-preview-message-role {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-3);
  }
  /* Role accent — dynamic suffix class (prompt-preview-message-{role}); the
     suffix isn't statically visible to Svelte, so :global avoids pruning. */
  :global(.prompt-preview-message-system) {
    border-left: 3px solid var(--k-system);
  }
  :global(.prompt-preview-message-user) {
    border-left: 3px solid var(--accent);
  }
  :global(.prompt-preview-message-assistant) {
    border-left: 3px solid var(--k-assistant);
  }
  .prompt-preview-block {
    margin: 0;
    padding: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    line-height: 1.45;
    color: var(--text);
  }
  .prompt-preview-cache-break {
    align-self: start;
    padding: 1px 6px;
    background: var(--star-soft);
    border: 1px dashed var(--star-border);
    border-radius: 4px;
    color: var(--star);
    font-size: 10px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .prompt-preview-cache-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 6px;
    padding: 2px 8px 6px;
    font-size: 0.78em;
    color: var(--text-3);
  }
  .prompt-preview-cache-chip {
    font-variant-numeric: tabular-nums;
  }
  .prompt-preview-cache-sep {
    opacity: 0.6;
  }
  .prompt-preview-cost {
    font-variant-numeric: tabular-nums;
  }

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
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    padding: 0;
    line-height: 1;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
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
    font-size: 11px;
    font-weight: 500;
    cursor: pointer;
    line-height: 1;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
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
    font-size: 13px;
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
    font-size: 13px;
  }
  .prompt-help-popover-header > small {
    color: var(--text-3);
    font-size: 11px;
    flex: 1;
  }
  .prompt-help-popover-header > small > code {
    background: var(--inset);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 0 4px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .prompt-help-popover-close {
    width: 22px;
    height: 22px;
    border-radius: 4px;
    border: none;
    background: transparent;
    cursor: pointer;
    font-size: 16px;
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
    font-size: 12px;
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
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    color: var(--accent-deep);
  }
  .prompt-cheatsheet-body dd {
    margin: 0 0 6px;
    color: var(--text-2);
    font-size: 12px;
    line-height: 1.45;
  }
  .prompt-cheatsheet-body dd > code {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 0 3px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11px;
    color: var(--accent-deep);
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
