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
  import { coerceInputValue } from "@/lib/utils/promptInputs";
  import type {
    AIPreviewResponse,
    DocumentKind,
    EditableDocument,
    LoreEntrySummary,
    PreviewErrorInfo,
    PromptEntrySummary,
    PromptInputConflict,
    PromptInputDefinition,
    StructureDocument,
  } from "@/lib/types";

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
  }: Props = $props();

  const isPrompt = (): boolean => documentKind === "prompt" && !!scene;

  let promptPreviewSceneId = $state("");
  let promptPreviewInputDrafts: Record<string, string> = $state({});
  let promptPreviewResult: AIPreviewResponse | null = $state(null);
  let promptPreviewRunning = $state(false);
  let promptPreviewError: string | null = $state(null);
  let promptPreviewPaneHeight = $state(280); // px; persisted only in memory for now.
  let promptPreviewCollapsed = $state(true);
  let promptPreviewDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let promptPreviewLastRenderKey = "";

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
  let promptPreviewConflicts: PromptInputConflict[] = $state([]);
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
  // different tick from the entry itself.
  let promptPreviewSeededEntryId: string | null = null;
  $effect(() => {
    if (loadedSceneId && loadedSceneId !== promptPreviewSeededEntryId) {
      promptPreviewResult = null;
      promptPreviewError = null;
      promptPreviewLastRenderKey = "";
      diagnostics = [];
      // Drop the previous entry's resolved set — fall back to the new entry's own
      // inputs until its first render resolves includes (ADR-0061 S2).
      effectiveInputs = [];
      inputProvenance = {};
      promptPreviewConflicts = [];
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
      const ns = err.undefined_namespace;
      if (missing && ns) {
        // A real, populated namespace object was accessed with an attribute it
        // doesn't have — a wrong path, not a missing input (#1019).
        let msg = `Your template references \`${ns}.${missing}\`, but \`${ns}\` has no attribute \`${missing}\`.`;
        if (ns === "project") {
          msg += ` A project's authored fields live under \`${ns}.metadata\` — did you mean \`${ns}.metadata.${missing}\`?`;
        }
        return msg;
      }
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
        // ADR-0061 S2: resolve the live body's effective inputs (own ∪ includes)
        // so the panel below shows a snippet's fields; own inputs are sent so the
        // resolver can merge them with the includes'.
        own_inputs: promptPreviewOwnInputs,
        resolve_effective_inputs: true,
      });
      promptPreviewResult = result;
      // Adopt the resolved set + provenance + any include-type conflict (returned
      // even when the render errored, so the form appears before the body renders).
      effectiveInputs = result.effective_inputs ?? [];
      inputProvenance = result.input_provenance ?? {};
      promptPreviewConflicts = result.input_conflicts ?? [];
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
        diagnostics = typeof line === "number" && line > 0
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
        diagnostics = [];
      }
    } catch (e) {
      // Falls here only for non-render failures (e.g. project closed, 5xx).
      promptPreviewError = (e as Error).message || "Render failed.";
      diagnostics = [];
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
</script>

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

    <div class="prompt-preview-pane-body">
      {#if promptPreviewConflicts.length > 0}
        <div class="prompt-preview-error" role="alert">
          <strong>Input type conflict</strong>
          {#each promptPreviewConflicts as conflict (conflict.name)}
            <p>
              <code>{conflict.name}</code> is declared with different types across included
              snippets ({conflict.types.join(", ")}). Included snippets must agree on an
              input's type before this prompt can resolve it.
            </p>
          {/each}
        </div>
      {/if}
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
        <!-- ADR-0060 §6: the send-path composition the model will receive — the
             system prefix, the tier-tagged lore the backend places (visible again),
             then the uncached conversation turns. -->
        {#each promptPreviewResult.cache_blocks as block}
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
      {:else if !promptPreviewRunning && !promptPreviewError}
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
    color: var(--danger);
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
