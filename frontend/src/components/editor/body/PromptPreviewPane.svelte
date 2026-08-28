<!--
  PromptPreviewPane — the inline prompt-author preview for a prompt entry.
  Extracted from CodeBodyView (#14, P2): the resize handle + preview section
  plus the whole render pipeline (debounced auto-render against /api/ai/preview,
  per-input draft seeding, friendly template-error rendering).

  All state here is presentational/derived — the only piece the parent needs back
  is `diagnostics` (the gutter markers driven by render errors), exposed as a
  $bindable so CodeBodyView can feed them to the CodeEditor. The template source
  (`rawBody`) and entry context are read-only props.
-->
<script lang="ts">
  import PromptInputField from "@/components/widgets/PromptInputField.svelte";
  import { api } from "@/lib/api";
  import { formatCostEur, formatTokens } from "@/lib/utils/money";
  import { coerceInputValue, friendlyTemplateError } from "@/lib/utils/promptInputs";
  import { buildSelectorRoster, expandSelectorsInEncodedValue } from "@/lib/views/pickerSelectors";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { cardEntriesStore } from "@/lib/stores/plotCards";
  import { promptPreviewDrafts } from "@/lib/stores/promptPreviewDrafts.svelte";
  import type {
    DocumentKind,
    EditableDocument,
    LoreEntrySummary,
    PromptEntrySummary,
    PromptInputDefinition,
    StructureDocument,
  } from "@/lib/types";

  // Design-time preview has no live prose context (#1427): the author is editing
  // the template, not running it against a real selection. The three runtime
  // prose slots are sent as visible placeholder tokens so a revise/continue
  // template renders with its `{{ selection }}` / `{{ text_before }}` /
  // `{{ text_after }}` position shown, rather than silently empty. Only the
  // author preview does this — the chat and estimate previews carry real context.
  const PREVIEW_TEXT_BEFORE = "«text before the cursor»";
  const PREVIEW_TEXT_AFTER = "«text after the cursor»";
  const PREVIEW_SELECTION = "«the selected text»";

  interface Props {
    // Template source + entry context (read-only from the parent).
    rawBody?: string;
    scene?: EditableDocument | null;
    documentKind?: DocumentKind;
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    availableScenes?: { id: string; title: string }[];
    loadedSceneId?: string | null;
    // Gutter diagnostics driven by render errors — bound OUT to the parent's
    // CodeEditor (was an internal CodeBodyView state before the split).
    diagnostics?: {
      line: number;
      col?: number;
      severity: "error" | "warning";
      message: string;
    }[];
    // ADR-0061 S3b: the live effective inputs + provenance (name → source snippet
    // id), bound OUT so the sibling EntryInputsEditor can render the inherited
    // tier from the SAME resolve this pane already runs on every body change —
    // which fires even while the pane is collapsed, so the tier stays live.
    effectiveInputs?: PromptInputDefinition[];
    inputProvenance?: Record<string, string>;
    // ADR-0062 §1: `fill` mode — the pane owns a whole column (the code‖preview
    // split, later a detached pane) rather than sitting stacked under the editor.
    // It's then always expanded, drops the collapse caret + vertical resize
    // handle, and stretches to fill instead of carrying a pixel height.
    fill?: boolean;
    // The open prompt's output handler (#1252): when it commits to a node
    // (`extract_to_node`) but the render registers no field_contract, the commit
    // can only produce an empty change — lint it here, at authoring time.
    outputHandler?: string;
  }

  let {
    rawBody = "",
    scene = null,
    documentKind = "prompt",
    structure = null,
    researchStructure = null,
    loreEntries = [],
    promptEntries = [],
    availableScenes = [],
    loadedSceneId = null,
    diagnostics = $bindable([]),
    effectiveInputs = $bindable([]),
    inputProvenance = $bindable({}),
    fill = false,
    outputHandler = "",
  }: Props = $props();

  const isPrompt = (): boolean => documentKind === "prompt" && !!scene;

  // Roster a context_pick selector (tag / saved view / plotline) expands against at
  // invocation (ADR-0074 slice 5/6). Author design-time preview — lore + manuscript
  // + plot cards cover the common kinds; a rarer assistant selector under-expands here.
  const selectorRoster = $derived(
    buildSelectorRoster({ schema: $metadataSchemaStore, structure, loreEntries, cardEntries: $cardEntriesStore }),
  );

  // ADR-0062 Amendment 2 / D1: the preview's input values + render state live in a
  // per-document store, not in this component, so a detached preview (a second
  // instance for the same prompt) shares one record instead of starting empty and
  // wiping the author's typed inputs. Keyed by the open prompt's document id; the
  // "__unattached__" bucket only holds the inert non-prompt case (isPrompt gates
  // every use). All `record.*` below is the shared, reactive state.
  const record = $derived(promptPreviewDrafts.entryFor(loadedSceneId ?? "__unattached__"));

  let promptPreviewPaneHeight = $state(280); // px; persisted only in memory for now.
  let promptPreviewCollapsed = $state(true);
  // In `fill` mode the pane always shows its full contents; otherwise the
  // author's collapse toggle governs. Everything below gates on this, not on
  // the raw collapse flag, so a filled pane ignores the (irrelevant) toggle.
  const previewExpanded = $derived(fill || !promptPreviewCollapsed);
  let promptPreviewDebounceTimer: ReturnType<typeof setTimeout> | null = null;

  // The prompt's OWN inputs (what the editor edits), read straight off the open
  // doc so this re-fires as they change in the editor section below.
  const promptPreviewOwnInputs = $derived(
    isPrompt() ? ((scene as unknown as PromptEntrySummary).inputs ?? []) : [],
  );

  // ADR-0061 S2: the EFFECTIVE inputs the panel renders — own ∪ every
  // `{% include %}`d snippet's, resolved server-side against the LIVE body and
  // returned by the last render. Falls back to own inputs as an instant
  // placeholder until the first render returns (so a snippet-free prompt and the
  // moment of opening a prompt are unchanged). The resolver stays the single
  // source; this is only which set the panel displays. `effectiveInputs` is a
  // bind-out prop (S3b) so the editor's inherited tier reads the same live set.
  const promptPreviewDeclaredInputs = $derived(
    !isPrompt()
      ? []
      : effectiveInputs.length > 0
        ? effectiveInputs
        : promptPreviewOwnInputs,
  );

  // Reset preview when the underlying entry changes. The default-filler
  // reactive below idempotently seeds any input that's still missing — needed
  // because the schema (which carries the input definitions) can arrive in a
  // different tick from the entry itself. The seed guard (`record.seededEntryId`)
  // lives on the shared record, so a second instance for the same document (a
  // detached preview) sees it already seeded and reuses the drafts.
  $effect(() => {
    if (loadedSceneId && loadedSceneId !== record.seededEntryId) {
      record.result = null;
      record.error = null;
      record.lastRenderKey = "";
      diagnostics = [];
      // Drop the previous entry's resolved set — fall back to the new entry's own
      // inputs until its first render resolves includes (ADR-0061 S2).
      effectiveInputs = [];
      inputProvenance = {};
      record.conflicts = [];
      record.inputDrafts = seedInputDrafts(promptPreviewDeclaredInputs);
      record.seededEntryId = loadedSceneId;
    }
  });
  $effect(() => {
    let changed = false;
    const next: Record<string, string> = { ...record.inputDrafts };
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
    if (changed) record.inputDrafts = next;
  });

  const promptPreviewMissingRequired = $derived(
    promptPreviewDeclaredInputs.filter((i) => {
      if (!i.required) return false;
      const v = record.inputDrafts[i.name];
      return v === undefined || v === null || (typeof v === "string" && !v.trim());
    }),
  );

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
    if (isPrompt() && !record.sceneId && availableScenes.length > 0) {
      record.sceneId = availableScenes[0].id;
    }
  });

  // Auto re-render on any preview-relevant change. Debounced.
  $effect(() => {
    schedulePromptPreviewRender(rawBody, record.sceneId, JSON.stringify(record.inputDrafts));
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
      record.result = null;
      record.error = null;
      record.lastRenderKey = "";
      return;
    }
    const inputs: Record<string, unknown> = {};
    for (const declared of promptPreviewDeclaredInputs) {
      const raw = record.inputDrafts[declared.name] ?? "";
      let coerced = coerceInputValue(raw, declared.type);
      if (declared.type === "context_pick")
        coerced = expandSelectorsInEncodedValue(coerced as string, selectorRoster);
      if (coerced !== null && coerced !== "") inputs[declared.name] = coerced;
    }
    const key = JSON.stringify({ rawBody, sceneId: record.sceneId, inputs });
    if (key === record.lastRenderKey && !record.error) return;
    record.lastRenderKey = key;
    record.running = true;
    try {
      const result = await api.aiPreview({
        template_source: rawBody,
        target_scene_id: record.sceneId || "",
        text_before: PREVIEW_TEXT_BEFORE,
        text_after: PREVIEW_TEXT_AFTER,
        selection: PREVIEW_SELECTION,
        inputs,
        commit: false,
        // ADR-0061 S2: resolve the live body's effective inputs (own ∪ includes)
        // so the panel below shows a snippet's fields; own inputs are sent so the
        // resolver can merge them with the includes'.
        own_inputs: promptPreviewOwnInputs,
        resolve_effective_inputs: true,
      });
      record.result = result;
      // Adopt the resolved set + provenance + any include-type conflict (returned
      // even when the render errored, so the form appears before the body renders).
      effectiveInputs = result.effective_inputs ?? [];
      inputProvenance = result.input_provenance ?? {};
      record.conflicts = result.input_conflicts ?? [];
      // Render errors come back as 200 + result.error (the endpoint is
      // exploratory; auto-firing it before required inputs are filled
      // would otherwise look like an HTTP failure). HttpError is still
      // possible for non-render failures (project not open, 5xx, etc.).
      if (result.error) {
        record.error = friendlyTemplateError(
          result.error,
          promptPreviewDeclaredInputs,
          record.inputDrafts,
        );
        const line = result.error.line;
        diagnostics = typeof line === "number" && line > 0
          ? [{
              line,
              col: typeof result.error.col === "number" && result.error.col > 0
                ? result.error.col
                : undefined,
              severity: "error",
              message: record.error ?? result.error.message,
            }]
          : [];
      } else {
        record.error = null;
        diagnostics = [];
      }
    } catch (e) {
      // Falls here only for non-render failures (e.g. project closed, 5xx).
      record.error = (e as Error).message || "Render failed.";
      diagnostics = [];
    } finally {
      record.running = false;
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
</script>

<!-- Vertical split: editor above gets the remaining space when the
     preview is expanded; collapsed by default so the body editor is
     the primary focus. The header toggles open/closed; the handle
     between editor and preview resizes the preview when expanded. -->
<!-- The vertical resize handle only makes sense in the stacked layout (a pixel
     height under the editor); in `fill` mode the pane's column owns its size. -->
{#if previewExpanded && !fill}
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
  class:collapsed={!previewExpanded}
  class:fill
  style={fill || promptPreviewCollapsed ? "" : `height: ${promptPreviewPaneHeight}px;`}
>
  <header class="prompt-preview-pane-header">
    {#if fill}
      <strong class="prompt-preview-title">Preview</strong>
    {:else}
      <button
        type="button"
        class="prompt-preview-toggle"
        aria-expanded={!promptPreviewCollapsed}
        onclick={() => (promptPreviewCollapsed = !promptPreviewCollapsed)}
      >
        <span class="prompt-preview-caret" aria-hidden="true">{promptPreviewCollapsed ? "▸" : "▾"}</span>
        <strong>Preview</strong>
      </button>
    {/if}
    <div class="prompt-preview-pane-meta">
      {#if record.running}
        <span class="prompt-preview-status">rendering…</span>
      {:else if record.result}
        <span class="prompt-preview-status">{record.result.messages.length} msg · {record.result.char_count} chars</span>
        {#if record.result.estimated_tokens}
          <span class="prompt-preview-cost" title="Estimated tokens (universal tokenizer; provider-specific counts may vary slightly).">
            · {formatTokens(record.result.estimated_tokens)} tok
          </span>
        {/if}
        {#if record.result.estimated_cost_usd != null}
          <span
            class="prompt-preview-cost"
            title="Estimated input cost on a settled send (warm cache — cache reads). The parenthetical is the first send (cache writes). Output cost depends on the response and isn't included."
          >
            · {formatCostEur(record.result.estimated_cost_usd)}
            {#if record.result.estimated_first_cost_usd != null && record.result.estimated_first_cost_usd !== record.result.estimated_cost_usd}
              ({formatCostEur(record.result.estimated_first_cost_usd)} first send)
            {/if}
          </span>
        {/if}
      {/if}
      {#if previewExpanded}
        <button type="button" disabled={record.running || !rawBody.trim()} onclick={runPromptPreview}>
          {record.running ? "Rendering…" : "Render now"}
        </button>
      {/if}
    </div>
  </header>

  {#if previewExpanded}
    <div class="prompt-preview-pane-controls">
      {#if promptPreviewDeclaredInputs.length > 0}
        <div class="prompt-preview-inputs">
          <div class="prompt-preview-inputs-heading">
            Inputs
            <small>{promptPreviewDeclaredInputs.length}</small>
            <small class="prompt-preview-inputs-hint">use in template as <code>&lbrace;&lbrace; input.&lt;name&gt; &rbrace;&rbrace;</code></small>
          </div>
          {#each promptPreviewDeclaredInputs as inputDef (inputDef.name)}
            {@const draft = record.inputDrafts[inputDef.name]}
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
                onChange={(next) => record.inputDrafts = {...record.inputDrafts, [inputDef.name]: next}}
              />
            </label>
          {/each}
        </div>
      {/if}
    </div>

    <div class="prompt-preview-pane-body">
      {#if record.conflicts.length > 0}
        <div class="prompt-preview-error" role="alert">
          <strong>Input type conflict</strong>
          {#each record.conflicts as conflict (conflict.name)}
            <p>
              <code>{conflict.name}</code> is declared with different types across included
              snippets ({conflict.types.join(", ")}). Included snippets must agree on an
              input's type before this prompt can resolve it.
            </p>
          {/each}
        </div>
      {/if}
      {#if record.error}
        <p class="prompt-preview-error">{record.error}</p>
      {/if}
      {#if promptPreviewMissingRequired.length > 0}
        <p class="prompt-preview-required-notice">
          {promptPreviewMissingRequired.length} required input{promptPreviewMissingRequired.length === 1 ? "" : "s"} empty:
          {promptPreviewMissingRequired.map((i) => i.label || i.name).join(", ")} — fill them in above to render the preview.
        </p>
      {/if}

      {#if !rawBody.trim()}
        <p class="prompt-preview-empty muted">Type a template above to see the rendered output here.</p>
      {:else if record.result}
        {@const emptyCommitContract =
          outputHandler === "extract_to_node" &&
          record.result.rendered &&
          (record.result.field_contract_stored?.length ?? 0) === 0}
        {#if record.result.warnings.length > 0 || emptyCommitContract}
          <div class="prompt-preview-warnings">
            <strong>Warnings</strong>
            {#each record.result.warnings as warning}
              <p>{warning}</p>
            {/each}
            {#if emptyCommitContract}
              <p>
                This prompt commits to a node but declares no fields, so it can only produce an
                empty change. Add a field_contract loop
                (<code>{"{% do field_contract.store(f) %}"}</code>) so the commit has fields to
                write.
              </p>
            {/if}
          </div>
        {/if}
        <!-- ADR-0060 §6: the send-path composition the model will receive — the
             system prefix, the tier-tagged lore the backend places (visible again),
             then the uncached conversation turns. -->
        {#each record.result.cache_blocks as block}
          <div class="prompt-preview-message prompt-preview-message-{block.role}">
            <header class="prompt-preview-message-role">
              <span>{block.label}</span>
              {#if block.tier}
                <span
                  class="prompt-preview-tier prompt-preview-tier-{block.tier}"
                  title={block.tier === "stable"
                    ? "Stable — cached 1h on explicit-cache providers"
                    : "Volatile — new or changed; cached 5m"}
                >{block.tier}</span>
              {/if}
              <span class="prompt-preview-block-tokens">{formatTokens(block.tokens)}</span>
            </header>
            {#if block.text}<pre class="prompt-preview-block">{block.text}</pre>{/if}
          </div>
        {/each}
      {:else if !record.running && !record.error}
        <p class="prompt-preview-empty muted">Waiting for first render…</p>
      {/if}
    </div>
  {/if}
</section>

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
    font-size: var(--fs-md);
    border-top: 1px solid var(--border);
    overflow: hidden;
  }
  .prompt-preview-pane.collapsed {
    grid-template-rows: auto;
    min-height: 0;
    height: auto;
  }
  /* ADR-0062 §1: filling a split/detached column — stretch to the parent's
     height, drop the stacked-layout top divider (the split gutter separates). */
  .prompt-preview-pane.fill {
    flex: 1 1 0;
    min-height: 0;
    border-top: none;
  }
  .prompt-preview-title {
    color: var(--text);
    font: inherit;
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
    font-size: var(--fs-md);
    color: inherit;
  }
  .prompt-preview-caret {
    display: inline-block;
    width: 12px;
    text-align: center;
    font-size: var(--fs-xs);
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
    font-size: var(--fs-xs);
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
    font-size: var(--fs-xs);
    color: var(--text-2);
  }
  .prompt-preview-field > span {
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .prompt-preview-field > :global(input),
  .prompt-preview-field > :global(select),
  .prompt-preview-field > :global(textarea) {
    padding: 3px 6px;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: var(--fs-sm);
    background: var(--surface);
  }
  .prompt-preview-field > :global(textarea) {
    font-family: var(--mono);
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
    font-size: var(--fs-xs);
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
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .prompt-preview-inputs-hint > code {
    font-family: var(--mono);
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
    font-size: var(--fs-xs);
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
    font-family: var(--mono);
    font-size: var(--fs-xs);
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
    font-size: var(--fs-sm);
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
    font-size: var(--fs-sm);
  }
  .prompt-preview-error {
    margin: 8px 0 0;
    padding: 6px 10px;
    background: var(--danger-soft);
    border: 1px solid var(--danger-border);
    border-radius: 4px;
    color: var(--danger-emphasis);
    font-size: var(--fs-sm);
    line-height: 1.45;
  }
  .prompt-preview-warnings {
    padding: 6px 10px;
    background: var(--star-soft);
    border: 1px solid var(--star-border);
    border-radius: 4px;
    color: var(--star);
    font-size: var(--fs-sm);
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
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-xs);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-3);
  }
  .prompt-preview-block-tokens {
    margin-left: auto;
    font-weight: 400;
    font-variant-numeric: tabular-nums;
  }
  /* Volatility tier (ADR-0060 §6): stable = quiet neutral, volatile = a gentle
     attention accent (reuses the ★ tokens). */
  .prompt-preview-tier {
    padding: 0 5px;
    border-radius: 3px;
    font-weight: 600;
    letter-spacing: 0.04em;
  }
  .prompt-preview-tier-stable {
    color: var(--text-3);
    border: 1px solid var(--border);
  }
  .prompt-preview-tier-volatile {
    color: var(--star);
    background: var(--star-soft);
    border: 1px solid var(--star-border);
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
    font-family: var(--mono);
    font-size: var(--fs-sm);
    line-height: 1.45;
    color: var(--text);
  }
  .prompt-preview-cost {
    font-variant-numeric: tabular-nums;
  }
</style>
