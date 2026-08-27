<!--
  PromptOutputEditor — the Setup tab's authoring control for a prompt
  instance's `context_strategy.output` (ADR-0062 Am.2 / D3): which
  OutputHandler runs its result, the orthogonal `headless` toggle, and each
  mode's sub-form (inline destination + accept-time mark; extract_to_node's
  commit — review, target type). A sidecar like OfferOnPicker/EntryInputsEditor,
  peer to both in the Setup tab.

  Every field here has a live runtime consumer (see promptResolution.ts /
  outputHandlers.ts) — this is not an inert form. `headless` is the one
  exception mid-flight: D3 authors it, but `{extract_to_node, headless}` has
  no runtime yet (arrives with E) — the sub-form annotates that combination
  rather than pretending it runs.

  `contextStrategy` is bind:'d to the parent (NodeEditor's
  contextStrategyDraft) so the parent's save logic owns serialization;
  `onChange` fires the pane's emitChange. Emits the whole
  `PromptContextStrategy | null` on any edit — null when the output would be
  entirely empty (a plain conversation carries no output block).
-->
<script lang="ts">
  import SegmentedControl from "@/components/widgets/SegmentedControl.svelte";
  import { commitTargetOptions } from "./promptOutputFields";
  import type { MetadataSchema, PromptCommit, PromptContextStrategy, PromptOnAccept, PromptOutput } from "@/lib/types";

  interface Props {
    // Persisted shape (bind:'d by the parent) — the instance's context_strategy.
    contextStrategy?: PromptContextStrategy | null;
    metadataSchema: MetadataSchema | null;
    // Locked for a built-in Library prompt (the host also wraps us in `inert`).
    readOnly?: boolean;
    // Outbound: the output config changed → parent emits its change/save.
    onChange?: () => void;
  }

  let {
    contextStrategy = $bindable(null),
    metadataSchema = null,
    readOnly = false,
    onChange,
  }: Props = $props();

  type Handler = "" | "inline" | "extract_to_node";

  const MODES: { id: Handler; label: string; hint: string }[] = [
    { id: "", label: "Conversation", hint: "a plain chat about this subject; the reply stays in the conversation" },
    { id: "inline", label: "Inline suggestion", hint: "streams a draft into the prose editor to accept or reject" },
    { id: "extract_to_node", label: "Brainstorm / commit", hint: "a chat whose result you commit to a node as a reviewable patch" },
  ];
  const DESTINATIONS: { id: "cursor" | "selection"; label: string; hint: string }[] = [
    { id: "cursor", label: "Continue at cursor", hint: "writes a continuation at the caret" },
    { id: "selection", label: "Replace selection", hint: "rewrites the selected prose in place" },
  ];
  const REVIEWS: { id: "visual_diff" | "replace"; label: string; hint: string }[] = [
    { id: "visual_diff", label: "Visual diff", hint: "adopt the result field-by-field against the current entry" },
    { id: "replace", label: "Replace", hint: "a plain current → proposed swap" },
  ];

  // The persistent "when to pick this" line under the mode control — the lasting
  // cue the per-option hover tooltips can't be (hover is undiscoverable on touch).
  const MODE_HINTS: Record<Handler, string> = {
    "": "Pick Conversation for a back-and-forth that doesn't write anywhere on its own.",
    inline: "Pick Inline suggestion to draft prose directly into the editor.",
    extract_to_node: "Pick Brainstorm / commit to workshop a node, then commit the result as a reviewable change.",
  };

  const output = $derived(contextStrategy?.output ?? null);
  const handler = $derived((output?.handler ?? "") as Handler);
  const headless = $derived(!!output?.headless);
  const destination = $derived(output?.destination === "selection" ? "selection" : "cursor");
  const commit = $derived(output?.commit ?? null);
  const review = $derived(commit?.review === "replace" ? "replace" : "visual_diff");
  const onAccept = $derived(output?.on_accept ?? null);
  const targetOptions = $derived(commitTargetOptions(metadataSchema));
  // The one cell with no runtime yet (E lands the one-shot produce path) —
  // annotate it so the author doesn't think it silently no-ops.
  const headlessExtractNote = $derived(handler === "extract_to_node" && headless);
  const modeHint = $derived(MODE_HINTS[handler]);

  // Rebuild the whole context_strategy from a candidate output, dropping to
  // null when it's entirely empty (a plain conversation) — matching the
  // writer's `model_dump(exclude_none=True)` empty-drop.
  function emit(nextOutput: PromptOutput | null): void {
    if (readOnly) return;
    const isEmpty =
      !nextOutput || (!nextOutput.handler && !nextOutput.headless && !nextOutput.commit && !nextOutput.on_accept);
    contextStrategy = isEmpty ? null : { output: nextOutput };
    onChange?.();
  }

  function patchOutput(patch: Partial<PromptOutput>): void {
    emit({ ...(output ?? {}), ...patch });
  }

  function setHandler(next: Handler): void {
    const patch: PromptOutput = { ...(output ?? {}), handler: next };
    // A clean switch: each mode's sub-config is meaningless (and validator-
    // rejected) under a different handler, so drop it rather than leave it
    // stranded for the next switch to resurrect.
    if (next !== "inline") {
      delete patch.destination;
      delete patch.on_accept;
    }
    if (next !== "extract_to_node") delete patch.commit;
    emit(patch);
  }

  function toggleHeadless(): void {
    const patch: PromptOutput = { ...(output ?? {}) };
    if (patch.headless) delete patch.headless;
    else patch.headless = true;
    emit(patch);
  }

  function setDestination(next: "cursor" | "selection"): void {
    patchOutput({ destination: next });
  }

  function setOnAcceptMark(value: string): void {
    const from_input = onAccept?.from_input ?? "";
    patchOutput({ on_accept: value || from_input ? { mark: value, from_input } : undefined });
  }

  function setOnAcceptFromInput(value: string): void {
    const mark = onAccept?.mark ?? "";
    patchOutput({ on_accept: mark || value ? { mark, from_input: value } : undefined });
  }

  function toggleCommit(on: boolean): void {
    patchOutput({ commit: on ? ({ review: "visual_diff" } satisfies PromptCommit) : undefined });
  }

  function setReview(next: "visual_diff" | "replace"): void {
    if (!commit) return;
    patchOutput({ commit: { ...commit, review: next } });
  }

  function setTarget(next: string): void {
    if (!commit) return;
    patchOutput({ commit: { ...commit, target: next || undefined } });
  }
</script>

<details class="prompt-output-editor">
  <summary>
    Output <small>{MODES.find((mode) => mode.id === handler)?.label ?? "Conversation"}</small>
    <small class="prompt-output-hint">which handler runs this prompt's result</small>
  </summary>

  <div class="prompt-output-mode">
    <SegmentedControl items={MODES} value={handler} ariaLabel="Output mode" onSelect={setHandler} />
    <label
      class="prompt-output-headless"
      title="Run headlessly — one-shot, no chat loop. Still collects required inputs and shows the result for review; it just skips the back-and-forth conversation."
    >
      <input type="checkbox" checked={headless} disabled={readOnly} onchange={() => toggleHeadless()} />
      Run headlessly
    </label>
  </div>
  <p class="prompt-output-mode-hint">{modeHint}</p>
  {#if headlessExtractNote}
    <p class="prompt-output-note">
      <i class="ti ti-info-circle" aria-hidden="true"></i>
      Generated headlessly (arrives with E) — no runtime yet for this combination.
    </p>
  {/if}

  {#if handler === "inline"}
    <div class="prompt-output-subform">
      <SegmentedControl items={DESTINATIONS} value={destination} ariaLabel="Inline destination" onSelect={setDestination} />
      <details class="prompt-output-onaccept">
        <summary>Accept-time mark <small>{onAccept ? "set" : "none"}</small></summary>
        <label class="prompt-output-field">
          Mark
          <input value={onAccept?.mark ?? ""} placeholder="character" disabled={readOnly} oninput={(e) => setOnAcceptMark(e.currentTarget.value)} />
        </label>
        <label class="prompt-output-field">
          From input
          <input value={onAccept?.from_input ?? ""} placeholder="character" disabled={readOnly} oninput={(e) => setOnAcceptFromInput(e.currentTarget.value)} />
        </label>
      </details>
    </div>
  {/if}

  {#if handler === "extract_to_node"}
    <div class="prompt-output-subform">
      <label class="prompt-output-commit-toggle">
        <input type="checkbox" checked={!!commit} disabled={readOnly} onchange={(e) => toggleCommit(e.currentTarget.checked)} />
        Commit button (extract to a node)
      </label>
      {#if commit}
        <SegmentedControl items={REVIEWS} value={review} ariaLabel="Commit review" onSelect={setReview} />
        <label class="prompt-output-field">
          Target type
          <select value={commit.target ?? ""} disabled={readOnly} onchange={(e) => setTarget(e.currentTarget.value)}>
            <option value="">Not set — revise the seeded entry</option>
            {#each targetOptions as opt (opt.id)}
              <option value={opt.id}>{opt.label}</option>
            {/each}
          </select>
        </label>
      {/if}
    </div>
  {/if}
</details>

<style>
  /* Mirrors OfferOnPicker/EntryInputsEditor's disclosure chrome so the three
     prompt sidecars read as a set (same inset panel, summary weight, hint colour). */
  .prompt-output-editor {
    padding: 6px 12px;
    background: var(--inset);
    border-top: 1px solid var(--border);
    font-size: var(--fs-md);
  }
  .prompt-output-editor[open] {
    max-height: 50vh;
    overflow-y: auto;
  }
  .prompt-output-editor > summary {
    cursor: pointer;
    user-select: none;
    font-weight: 600;
    color: var(--text);
    display: flex;
    align-items: baseline;
    gap: 6px;
  }
  .prompt-output-editor > summary > small {
    color: var(--text-3);
    font-weight: 400;
  }
  .prompt-output-hint {
    margin-left: auto;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .prompt-output-mode {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 6px 0;
    flex-wrap: wrap;
  }
  /* Persistent "when to pick this" cue under the mode control (discoverability,
     #1200) — a lasting line, not only the per-option hover tooltip. */
  .prompt-output-mode-hint {
    margin: 0 0 6px;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .prompt-output-headless {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: var(--fs-sm);
    color: var(--text-2);
    cursor: pointer;
  }
  .prompt-output-headless > input {
    margin: 0;
  }
  .prompt-output-note {
    margin: 4px 0 6px;
    padding: 4px 8px;
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-xs);
    color: var(--text-2);
    background: var(--surface);
    border: 1px solid var(--divider);
    border-radius: var(--r-sm);
  }
  .prompt-output-subform {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    margin-top: 6px;
    padding: 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
  }
  .prompt-output-onaccept {
    width: 100%;
    font-size: var(--fs-sm);
  }
  .prompt-output-onaccept > summary {
    cursor: pointer;
    user-select: none;
    color: var(--text-2);
    display: flex;
    align-items: baseline;
    gap: 6px;
  }
  .prompt-output-onaccept > summary > small {
    color: var(--text-3);
    font-weight: 400;
  }
  .prompt-output-field {
    display: grid;
    gap: 2px;
    width: 100%;
    max-width: 320px;
    font-size: var(--fs-xs);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3);
  }
  .prompt-output-field :global(input),
  .prompt-output-field :global(select) {
    padding: 3px 6px;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: var(--fs-sm);
    background: var(--surface);
    text-transform: none;
    font-weight: 400;
    letter-spacing: normal;
  }
  .prompt-output-commit-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-sm);
    color: var(--text-2);
    cursor: pointer;
  }
  .prompt-output-commit-toggle > input {
    flex: none;
    margin: 0;
  }
</style>
