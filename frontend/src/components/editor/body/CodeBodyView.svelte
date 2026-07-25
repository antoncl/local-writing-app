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
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import CodeEditor from "@/components/widgets/CodeEditor.svelte";
  import EntryInputsEditor from "@/components/editor/body/EntryInputsEditor.svelte";
  import PromptPreviewPane from "@/components/editor/body/PromptPreviewPane.svelte";
  import { type EntryInputDraft } from "@/lib/utils/promptInputs";
  import type {
    DocumentKind,
    EditableDocument,
    EntryBodyLanguage,
    LoreEntrySummary,
    PromptEntrySummary,
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

  // Gutter diagnostics for the CodeEditor — written by PromptPreviewPane's
  // render pipeline (bound below) and fed to the editor's `diagnostics` prop.
  let promptPreviewDiagnostics: {
    line: number;
    col?: number;
    severity: "error" | "warning";
    message: string;
  }[] = $state([]);

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

  <PromptPreviewPane
    bind:diagnostics={promptPreviewDiagnostics}
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
