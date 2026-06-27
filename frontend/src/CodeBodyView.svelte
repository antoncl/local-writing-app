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
  import { createEventDispatcher } from "svelte";
  import CodeEditor from "./CodeEditor.svelte";
  import NodePickerConfigEditor from "./NodePickerConfigEditor.svelte";
  import PromptInputField from "./PromptInputField.svelte";
  import { api, HttpError } from "./api";
  import { formatCostEur, formatTokens } from "./money";
  import { coerceInputValue, type EntryInputDraft } from "./promptInputs";
  import type {
    AIPreviewResponse,
    EditableDocument,
    EntryBodyLanguage,
    LoreEntrySummary,
    MetadataSchema,
    PromptEntrySummary,
    PromptInputDefinition,
    StructureDocument,
  } from "./types";

  // --- Inputs the parent owns (state lifted up) ---
  export let rawBody = "";
  export let entryInputDrafts: EntryInputDraft[] = [];

  // --- Read-only context from parent ---
  export let scene: EditableDocument | null = null;
  export let documentKind:
    | "scene"
    | "lore"
    | "prompt"
    | "snippet"
    | "assistant"
    | "project"
    | "structure_node" = "prompt";
  export let metadataSchema: MetadataSchema | null = null;
  export let structure: StructureDocument | null = null;
  // Research tree (sibling to manuscript) — threaded to the picker.
  export let researchStructure: StructureDocument | null = null;
  export let loreEntries: LoreEntrySummary[] = [];
  export let promptEntries: PromptEntrySummary[] = [];
  export let availableScenes: { id: string; title: string }[] = [];
  export let rawBodyLanguage: EntryBodyLanguage = "markdown";
  export let loadedSceneId: string | null = null;

  // Shared id factory + slug helper — same counters/rules as NodeEditor's
  // reseed path use, so clientIds don't collide and name slugification is
  // consistent across the two creation sites.
  export let nextInputDraftId: () => string;
  export let entrySlugify: (value: string) => string;

  const dispatch = createEventDispatcher<{
    inputsChange: void;
  }>();

  const isPrompt = (): boolean => documentKind === "prompt" && !!scene;

  // --- Restore-default-body (for prompt sub-types with a non-empty
  //     default_body, e.g. roleplay). Visible only when the current body
  //     diverges, so a freshly-created prompt won't see noise. Click
  //     overwrites rawBody — CodeMirror keeps undo history, and the parent
  //     pane doesn't auto-save, so accidents are recoverable.
  $: entryTypeDefaultBody =
    isPrompt() && metadataSchema && scene
      ? metadataSchema.entry_types[scene.entry_type]?.default_body ?? ""
      : "";
  $: canRestoreDefaultBody = entryTypeDefaultBody.length > 0 && rawBody !== entryTypeDefaultBody;

  function restoreDefaultBody(): void {
    if (!canRestoreDefaultBody) return;
    rawBody = entryTypeDefaultBody;
  }

  // --- Cheatsheet popover ---
  let cheatsheetPopoverOpen = false;
  let helpButtonEl: HTMLButtonElement | undefined;
  let popoverPos = { top: 0, right: 8 };

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

  // --- Entry-inputs declaration editor ---
  let entryInputsExpanded = false;

  function addEntryInput(): void {
    entryInputDrafts = [
      ...entryInputDrafts,
      {
        clientId: nextInputDraftId(),
        name: "",
        type: "text",
        label: "",
        defaultValue: "",
        options: "",
        required: false,
        targetKind: "",
        targetEntryType: "",
        nodePickerConfig: { kinds: [], presets: [], multiple: true },
        nameDerived: true,
      },
    ];
    dispatch("inputsChange");
  }

  function removeEntryInput(index: number): void {
    entryInputDrafts = entryInputDrafts.filter((_, i) => i !== index);
    dispatch("inputsChange");
  }

  function updateEntryInputLabel(index: number, label: string): void {
    entryInputDrafts = entryInputDrafts.map((draft, i) => {
      if (i !== index) return draft;
      const next = { ...draft, label };
      if (draft.nameDerived) next.name = entrySlugify(label);
      return next;
    });
    dispatch("inputsChange");
  }

  function updateEntryInputName(index: number, name: string): void {
    entryInputDrafts = entryInputDrafts.map((draft, i) =>
      i !== index ? draft : { ...draft, name: entrySlugify(name), nameDerived: false },
    );
    dispatch("inputsChange");
  }

  function updateEntryInput(
    index: number,
    patch: Partial<EntryInputDraft>,
  ): void {
    entryInputDrafts = entryInputDrafts.map((draft, i) =>
      i !== index ? draft : { ...draft, ...patch },
    );
    dispatch("inputsChange");
  }

  function updateEntryInputNodePickerConfig(
    index: number,
    config: import("./types").NodePickerConfig,
  ): void {
    updateEntryInput(index, { nodePickerConfig: config });
  }

  function moveEntryInput(from: number, to: number): void {
    if (from === to || from < 0 || to < 0) return;
    if (from >= entryInputDrafts.length || to >= entryInputDrafts.length) return;
    const next = entryInputDrafts.slice();
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    entryInputDrafts = next;
    dispatch("inputsChange");
  }

  // Linear before/after reorder for the inputs list. Mirrors the tree's
  // drag-handle UX but without the "into" mode — inputs are a flat list.
  let inputDragFromIndex: number | null = null;
  let inputDragOverIndex: number | null = null;
  let inputDragOverPosition: "before" | "after" | null = null;

  function handleInputDragStart(event: DragEvent, index: number) {
    inputDragFromIndex = index;
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(index));
    }
  }

  function handleInputDragEnd() {
    inputDragFromIndex = null;
    inputDragOverIndex = null;
    inputDragOverPosition = null;
  }

  function handleInputDragOver(event: DragEvent, index: number) {
    if (inputDragFromIndex === null || inputDragFromIndex === index) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    const target = event.currentTarget;
    if (!(target instanceof HTMLElement)) return;
    const rect = target.getBoundingClientRect();
    const position: "before" | "after" = event.clientY - rect.top < rect.height / 2 ? "before" : "after";
    if (inputDragOverIndex !== index || inputDragOverPosition !== position) {
      inputDragOverIndex = index;
      inputDragOverPosition = position;
    }
  }

  function handleInputDrop(event: DragEvent, index: number) {
    event.preventDefault();
    const from = inputDragFromIndex;
    const position = inputDragOverPosition;
    handleInputDragEnd();
    if (from === null || position === null || from === index) return;
    let to = position === "before" ? index : index + 1;
    if (from < to) to -= 1;
    moveEntryInput(from, to);
  }

  // --- Inline prompt preview (prompts only) ---
  let promptPreviewSceneId = "";
  let promptPreviewInputDrafts: Record<string, string> = {};
  let promptPreviewResult: AIPreviewResponse | null = null;
  let promptPreviewRunning = false;
  let promptPreviewError: string | null = null;
  let promptPreviewPaneHeight = 280; // px; persisted only in memory for now.
  let promptPreviewCollapsed = true;
  let promptPreviewDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let promptPreviewLastRenderKey = "";
  // Diagnostics pinned in the CodeEditor gutter — driven by render errors.
  export let promptPreviewDiagnostics: {
    line: number;
    col?: number;
    severity: "error" | "warning";
    message: string;
  }[] = [];

  // Inputs are per-entry. Read scene.inputs directly so this reactive
  // re-fires when the entry's inputs change via the editor section below.
  $: promptPreviewDeclaredInputs =
    isPrompt() ? ((scene as unknown as PromptEntrySummary).inputs ?? []) : [];

  // Reset preview when the underlying entry changes. The default-filler
  // reactive below idempotently seeds any input that's still missing — needed
  // because the schema (which carries the input definitions) can arrive in a
  // different tick from the entry itself.
  let promptPreviewSeededEntryId: string | null = null;
  $: if (loadedSceneId && loadedSceneId !== promptPreviewSeededEntryId) {
    promptPreviewResult = null;
    promptPreviewError = null;
    promptPreviewLastRenderKey = "";
    promptPreviewDiagnostics = [];
    promptPreviewInputDrafts = seedInputDrafts(promptPreviewDeclaredInputs);
    promptPreviewSeededEntryId = loadedSceneId;
  }
  $: {
    let changed = false;
    const next: Record<string, string> = { ...promptPreviewInputDrafts };
    for (const input of promptPreviewDeclaredInputs) {
      if (next[input.name] === undefined) {
        next[input.name] =
          input.default !== undefined && input.default !== null
            ? String(input.default)
            : input.type === "boolean"
              ? "false"
              : "";
        changed = true;
      }
    }
    if (changed) promptPreviewInputDrafts = next;
  }

  $: promptPreviewMissingRequired = promptPreviewDeclaredInputs.filter((i) => {
    if (!i.required) return false;
    const v = promptPreviewInputDrafts[i.name];
    return v === undefined || v === null || (typeof v === "string" && !v.trim());
  });

  /** Translate Jinja2's terse error strings into plain English for the
   * prompt author. Right now: UndefinedError attribute-misses on `input.<X>`
   * (the most common authoring mistake — typo in the input name, or referring
   * to a label instead of the name). Falls through unchanged for everything
   * else. */
  function friendlyTemplateError(raw: string, declared: PromptInputDefinition[]): string {
    const m = /UndefinedError:\s*'\w+\s*object'\s*has\s*no\s*attribute\s*'(\w+)'/.exec(raw);
    if (m) {
      const missing = m[1];
      const declaredNames = declared.map((d) => d.name);
      const inputsList = declaredNames.length
        ? ` Available inputs: ${declaredNames.map((n) => "input." + n).join(", ")}.`
        : " No inputs are declared on this prompt — add one in the Detail Type editor first.";
      return `Your template references \`{{ input.${missing} }}\` but there's no input named "${missing}".${inputsList}`;
    }
    return raw;
  }

  function seedInputDrafts(declared: PromptInputDefinition[]): Record<string, string> {
    const drafts: Record<string, string> = {};
    for (const input of declared) {
      if (input.default !== undefined && input.default !== null) {
        drafts[input.name] = String(input.default);
      } else if (input.type === "boolean") {
        drafts[input.name] = "false";
      } else {
        drafts[input.name] = "";
      }
    }
    return drafts;
  }

  // Fallback scene binding for the preview's `scene` variable. The user
  // controls the explicit binding by marking a scene ★ in any context_pick
  // input — that wins backend-side (preview.py:_find_marked_target_scene_id).
  $: if (isPrompt() && !promptPreviewSceneId && availableScenes.length > 0) {
    promptPreviewSceneId = availableScenes[0].id;
  }

  // Auto re-render on any preview-relevant change. Debounced.
  $: schedulePromptPreviewRender(rawBody, promptPreviewSceneId, JSON.stringify(promptPreviewInputDrafts));

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
      promptPreviewResult = await api.aiPreview({
        template_source: rawBody,
        target_scene_id: promptPreviewSceneId || "",
        inputs,
        commit: false,
      });
      promptPreviewError = null;
      promptPreviewDiagnostics = [];
    } catch (e) {
      promptPreviewError = friendlyTemplateError(
        (e as Error).message || "Render failed.",
        promptPreviewDeclaredInputs,
      );
      // If the error carries a line number (Jinja2 syntax errors do), pin a
      // gutter marker on that line. UndefinedError has no line — the error
      // text shown below the preview is the only signal in that case.
      const next: typeof promptPreviewDiagnostics = [];
      if (e instanceof HttpError && e.detail && typeof e.detail === "object") {
        const d = e.detail as { line?: unknown; col?: unknown; message?: unknown };
        if (typeof d.line === "number" && d.line > 0) {
          next.push({
            line: d.line,
            col: typeof d.col === "number" && d.col > 0 ? d.col : undefined,
            severity: "error",
            message: typeof d.message === "string" ? d.message : promptPreviewError,
          });
        }
      }
      promptPreviewDiagnostics = next;
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
    <CodeEditor bind:value={rawBody} language={rawBodyLanguage} diagnostics={isPrompt() ? promptPreviewDiagnostics : []} />
  </div>

  {#if isPrompt()}
    {#if canRestoreDefaultBody}
      <button
        type="button"
        class="prompt-restore-default-button"
        title="Replace this body with the type's default template. Ctrl+Z to undo."
        aria-label="Restore default body"
        on:click={restoreDefaultBody}
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
      on:click={toggleCheatsheetPopover}
    >?</button>
  {/if}
</div>

{#if isPrompt()}
  {#if cheatsheetPopoverOpen}
    <div class="prompt-help-popover" role="dialog" aria-label="Variables and helpers" style="top: {popoverPos.top}px; right: {popoverPos.right}px;">
      <header class="prompt-help-popover-header">
        <strong>Variables &amp; helpers</strong>
        <small>what you can reference in <code>&lbrace;&lbrace; … &rbrace;&rbrace;</code> and <code>&lbrace;% … %&rbrace;</code></small>
        <button type="button" class="prompt-help-popover-close" aria-label="Close" on:click={() => (cheatsheetPopoverOpen = false)}>×</button>
      </header>
      <div class="prompt-cheatsheet-body">
        <section>
          <h4>Variables</h4>
          <dl>
            <dt><code>scene</code></dt>
            <dd>The target scene. <code>scene.title</code>, <code>scene.body_markdown</code>, <code>scene.entry_type</code>, <code>scene.&lt;field&gt;</code> for any field on the scene (e.g. <code>scene.summary</code>, <code>scene.pov.title</code>). Entity-ref fields auto-resolve.</dd>
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

  <details class="entry-inputs-editor" bind:open={entryInputsExpanded}>
    <summary>
      Inputs <small>{entryInputDrafts.length}</small>
      <small class="entry-inputs-hint">declared on this prompt · use as <code>&lbrace;&lbrace; input.&lt;id&gt; &rbrace;&rbrace;</code></small>
    </summary>
    {#if entryInputDrafts.length === 0}
      <p class="muted entry-inputs-empty">No inputs yet. Click + Input to declare one.</p>
    {/if}
    {#each entryInputDrafts as draft, index (draft.clientId)}
      {#if draft.type === "context_pick"}
        <!-- context_pick owns its entire row (chevron · label · id ·
             type select · Required · Multiple · ×). Generic input types
             still render the .prompt-input-grid below. -->
        <div
          class="prompt-input-row prompt-input-row-context"
          role="group"
          class:dragging={inputDragFromIndex === index}
          class:drop-before={inputDragOverIndex === index && inputDragOverPosition === "before"}
          class:drop-after={inputDragOverIndex === index && inputDragOverPosition === "after"}
          on:dragover={(e) => handleInputDragOver(e, index)}
          on:drop={(e) => handleInputDrop(e, index)}
        >
          <span
            class="tree-handle prompt-input-handle"
            draggable="true"
            role="button"
            tabindex="-1"
            aria-label="Drag to reorder"
            on:dragstart={(e) => handleInputDragStart(e, index)}
            on:dragend={handleInputDragEnd}
          >⋮⋮</span>
          <NodePickerConfigEditor
            config={draft.nodePickerConfig}
            metadataSchema={metadataSchema}
            label={draft.label}
            name={draft.name}
            required={draft.required}
            on:change={(event) => updateEntryInputNodePickerConfig(index, event.detail.config)}
            on:labelchange={(event) => updateEntryInputLabel(index, event.detail.value)}
            on:namechange={(event) => updateEntryInputName(index, event.detail.value)}
            on:requiredchange={(event) => updateEntryInput(index, { required: event.detail.value })}
            on:typechange={(event) => updateEntryInput(index, { type: event.detail.value })}
            on:remove={() => removeEntryInput(index)}
          />
        </div>
      {:else}
        <div
          class="prompt-input-row"
          role="group"
          class:dragging={inputDragFromIndex === index}
          class:drop-before={inputDragOverIndex === index && inputDragOverPosition === "before"}
          class:drop-after={inputDragOverIndex === index && inputDragOverPosition === "after"}
          on:dragover={(e) => handleInputDragOver(e, index)}
          on:drop={(e) => handleInputDrop(e, index)}
        >
          <span
            class="tree-handle prompt-input-handle"
            draggable="true"
            role="button"
            tabindex="-1"
            aria-label="Drag to reorder"
            on:dragstart={(e) => handleInputDragStart(e, index)}
            on:dragend={handleInputDragEnd}
          >⋮⋮</span>
          <div class="prompt-input-grid">
            <label>
              Label
              <input value={draft.label} placeholder="Topic to brainstorm" on:input={(e) => updateEntryInputLabel(index, (e.currentTarget as HTMLInputElement).value)} />
            </label>
            <label>
              ID
              <input value={draft.name} placeholder="topic_to_brainstorm" on:input={(e) => updateEntryInputName(index, (e.currentTarget as HTMLInputElement).value)} />
              {#if draft.name}
                <small class="prompt-input-accessor"><code>&lbrace;&lbrace; input.{draft.name} &rbrace;&rbrace;</code></small>
              {/if}
            </label>
            <label>
              Type
              <select value={draft.type} on:change={(e) => updateEntryInput(index, { type: (e.currentTarget as HTMLSelectElement).value as import("./types").PromptInputType })}>
                <option value="text">Text</option>
                <option value="long_text">Long Text</option>
                <option value="number">Number</option>
                <option value="boolean">Boolean</option>
                <option value="select">Select</option>
                <option value="entity_ref">Entity Reference</option>
                <option value="entity_ref_list">Entity Reference List</option>
                <option value="context_pick">Context Picker</option>
              </select>
            </label>
            <label>
              Default
              <input value={draft.defaultValue} placeholder="" on:input={(e) => updateEntryInput(index, { defaultValue: (e.currentTarget as HTMLInputElement).value })} />
            </label>
            {#if draft.type === "select"}
              <label class="prompt-input-options">
                Options
                <input value={draft.options} placeholder="quick, thorough" on:input={(e) => updateEntryInput(index, { options: (e.currentTarget as HTMLInputElement).value })} />
              </label>
            {/if}
            {#if draft.type === "entity_ref" || draft.type === "entity_ref_list"}
              <label>
                Target kind
                <select value={draft.targetKind} on:change={(e) => updateEntryInput(index, { targetKind: (e.currentTarget as HTMLSelectElement).value as "" | "scene" | "lore" })}>
                  <option value="">Any</option>
                  <option value="scene">Scene</option>
                  <option value="lore">Lore</option>
                </select>
              </label>
              <label>
                Target entry type
                <input value={draft.targetEntryType} placeholder="" on:input={(e) => updateEntryInput(index, { targetEntryType: (e.currentTarget as HTMLInputElement).value })} />
              </label>
            {/if}
            <label class="prompt-input-required">
              <input type="checkbox" checked={draft.required} on:change={(e) => updateEntryInput(index, { required: (e.currentTarget as HTMLInputElement).checked })} />
              Required
            </label>
            <button type="button" class="prompt-input-remove" title="Remove input" on:click={() => removeEntryInput(index)}>×</button>
          </div>
        </div>
      {/if}
    {/each}
    <div class="entry-inputs-add">
      <button type="button" on:click={addEntryInput}>+ Input</button>
    </div>
  </details>

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
      on:mousedown={startPromptPreviewResize}
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
        on:click={() => (promptPreviewCollapsed = !promptPreviewCollapsed)}
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
          <button type="button" disabled={promptPreviewRunning || !rawBody.trim()} on:click={runPromptPreview}>
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
                    on:click|preventDefault={() => navigator.clipboard?.writeText(`{{ input.${inputDef.name} }}`).catch(() => {})}
                  ><code>&lbrace;&lbrace; input.{inputDef.name} &rbrace;&rbrace;</code></button>
                </span>
                <PromptInputField
                  input={inputDef}
                  value={draft ?? ""}
                  metadataSchema={metadataSchema}
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
            {promptPreviewMissingRequired.map((i) => i.label || i.name).join(", ")} — the rendered output below will have empty slots wherever this is referenced.
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
