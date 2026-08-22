<!--
  FinalizeRoleplayDialog — the "Finalize roleplay" modal (ADR-0070 S3). Turns
  a roleplayed scene into finished prose: pick a finalize prompt, stream the
  clean-prose projection as a preview, then commit it. Opened imperatively
  (`bind:this` → `open(scene)`), mirroring PromptInvocationDialog's pattern —
  the host never reaches into this component's state, only calls `open`.

  Flow: pick → generating → preview → applying. The finalize is a POV
  projection (the prompt writes from one character's eyes), so generation is
  gated on the scene's `pov` metadata being set.
-->
<script lang="ts">
  import Modal from "@/components/dialogs/Modal.svelte";
  import { api } from "@/lib/api";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { hiddenLibraryStore } from "@/lib/stores/hiddenLibrary";
  import { finalizePromptRoster, type PromptResolutionContext } from "@/lib/editor-core/promptResolution";
  import { formatCostEur } from "@/lib/utils/money";
  import type { EditableDocument, LoreEntrySummary, PromptEntrySummary, Scene } from "@/lib/types";

  let {
    promptEntries = [],
    loreEntries = [],
    availableScenes = [],
    onFlush = undefined,
    onFinalized = undefined,
  }: {
    promptEntries?: PromptEntrySummary[];
    loreEntries?: LoreEntrySummary[];
    availableScenes?: { id: string; title: string }[];
    // Flush the scene's pending (autosave-debounced) edits to disk before the
    // projection reads it — the finalize source and the safety-net snapshot must
    // see the author's latest words, not the ~6s-stale disk copy.
    onFlush?: (sceneId: string) => Promise<void>;
    onFinalized?: (scene: Scene) => void;
  } = $props();

  type Phase = "pick" | "generating" | "preview" | "applying";

  let openScene: EditableDocument | null = $state(null);
  let phase: Phase = $state("pick");
  let selectedPromptId: string | null = $state(null);
  // Accumulated streamed prose.
  let generated = $state("");
  let error: string | null = $state(null);
  let cost: number | null = $state(null);

  // Not $state — an imperative handle for the in-flight stream, not
  // something the template reads reactively.
  let abortController: AbortController | null = null;

  // Snapshot for the pure prompt-resolution helpers, mirroring ProseBodyView's
  // `promptCtx` (see body/ProseBodyView.svelte).
  let ctx = $derived<PromptResolutionContext>({
    metadataSchema: $metadataSchemaStore,
    promptEntries,
    loreEntries,
    availableScenes,
    hiddenPromptIds: $hiddenLibraryStore,
  });
  let roster = $derived(finalizePromptRoster(ctx));

  function povIdOf(scene: EditableDocument | null): string {
    const value = scene?.metadata?.pov;
    return typeof value === "string" ? value : "";
  }
  let povId = $derived(povIdOf(openScene));
  let povName = $derived(loreEntries.find((e) => e.id === povId)?.title ?? "");
  let povMissing = $derived(!povId);

  let selectedPrompt = $derived(roster.find((p) => p.id === selectedPromptId) ?? null);
  let canGenerate = $derived(!povMissing && !!selectedPrompt);

  // Opened by the host. Resets the whole flow and defaults the prompt pick to
  // the first roster entry.
  export function open(scene: EditableDocument): void {
    openScene = scene;
    phase = "pick";
    generated = "";
    error = null;
    cost = null;
    selectedPromptId = finalizePromptRoster(ctx)[0]?.id ?? null;
  }

  function close() {
    abortController?.abort();
    abortController = null;
    openScene = null;
  }

  async function generate() {
    const scene = openScene;
    const entry = selectedPrompt;
    if (!scene || !entry || povMissing) return;
    generated = "";
    error = null;
    cost = null;
    phase = "generating";
    abortController = new AbortController();
    try {
      // Push the editor's latest words to disk first, so the projection (and the
      // safety-net snapshot it takes on Apply) sees them, not the stale copy.
      await onFlush?.(scene.id);
      for await (const ev of api.aiGenerateStream(
        {
          template_source: entry.body,
          target_scene_id: scene.id,
          session_id: scene.id,
          commit: false,
        },
        abortController.signal,
      )) {
        if (ev.type === "delta") generated += ev.text;
        else if (ev.type === "done") cost = ev.cost_usd ?? null;
        else if (ev.type === "error") error = ev.error || "Generation failed.";
      }
      phase = error ? "pick" : "preview";
      if (!error && !generated.trim()) {
        error = "The model returned no prose.";
        phase = "pick";
      }
    } catch (e) {
      error = (e as Error).message;
      phase = "pick";
    } finally {
      abortController = null;
    }
  }

  // Stops the in-flight stream and returns to the picker — the "disable the
  // buttons" state during `generating` has only this affordance live.
  function cancelGenerating() {
    abortController?.abort();
    abortController = null;
    generated = "";
    error = null;
    phase = "pick";
  }

  function discard() {
    generated = "";
    error = null;
    cost = null;
    phase = "pick";
  }

  async function apply() {
    const scene = openScene;
    if (!scene) return;
    phase = "applying";
    try {
      const result = await api.finalizeScene(scene.id, generated);
      onFinalized?.(result);
      close();
    } catch (e) {
      error = (e as Error).message;
      phase = "preview";
    }
  }
</script>

{#if openScene}
  <Modal
    title="Finalize roleplay"
    frameStyle="--modal-width: 640px; --modal-max-height: 80vh; --modal-overflow-y: auto;"
  >
    <div class="frd-body">
      {#if povMissing}
        <p class="frd-pov-gate">Set this scene's POV character before finalizing.</p>
      {:else}
        <p class="frd-pov">Point of view: <strong>{povName}</strong></p>
      {/if}

      {#if phase === "pick"}
        {#if error}
          <p class="frd-error" role="alert">{error}</p>
        {/if}
        {#if roster.length === 0}
          <p class="frd-empty">No finalize prompts available.</p>
        {:else}
          <div class="frd-roster" role="radiogroup" aria-label="Finalize prompt">
            {#each roster as entry (entry.id)}
              <button
                type="button"
                class="frd-roster-row"
                class:selected={selectedPromptId === entry.id}
                role="radio"
                aria-checked={selectedPromptId === entry.id}
                onclick={() => (selectedPromptId = entry.id)}
              >
                {entry.title}
              </button>
            {/each}
          </div>
        {/if}
      {:else if phase === "generating"}
        <div class="frd-preview" style="white-space: pre-wrap;">{generated}</div>
      {:else if phase === "preview" || phase === "applying"}
        <div class="frd-preview" style="white-space: pre-wrap;">{generated}</div>
        {#if typeof cost === "number"}
          <p class="frd-cost">Cost: {formatCostEur(cost)}</p>
        {/if}
        {#if error}
          <p class="frd-error" role="alert">{error}</p>
        {/if}
      {/if}
    </div>

    {#snippet actions()}
      {#if phase === "pick"}
        <button type="button" onclick={close}>Cancel</button>
        <button type="button" class="primary" disabled={!canGenerate} onclick={generate}>Generate</button>
      {:else if phase === "generating"}
        <button type="button" onclick={cancelGenerating}>Cancel</button>
        <button type="button" class="primary" disabled>Generating…</button>
      {:else if phase === "preview"}
        <button type="button" onclick={discard}>Discard</button>
        <button type="button" onclick={generate}>Regenerate</button>
        <span class="frd-apply-group">
          <button type="button" class="primary" onclick={apply}>Apply</button>
          <small class="frd-apply-note">A snapshot is saved first, so you can undo this.</small>
        </span>
      {:else if phase === "applying"}
        <button type="button" disabled>Discard</button>
        <button type="button" disabled>Regenerate</button>
        <span class="frd-apply-group">
          <button type="button" class="primary" disabled>Applying…</button>
          <small class="frd-apply-note">A snapshot is saved first, so you can undo this.</small>
        </span>
      {/if}
    {/snippet}
  </Modal>
{/if}

<style>
  .frd-body {
    display: grid;
    gap: var(--sp-3);
    font-size: var(--fs-md);
  }

  .frd-pov {
    margin: 0;
    color: var(--text-2);
  }

  .frd-pov strong {
    color: var(--text);
  }

  .frd-pov-gate {
    margin: 0;
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid var(--divider);
    border-radius: 6px;
    background: var(--inset);
    color: var(--text-2);
  }

  .frd-error {
    margin: 0;
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid var(--danger-border);
    border-radius: 6px;
    background: var(--danger-soft);
    color: var(--danger);
    font-size: var(--fs-sm);
  }

  .frd-empty {
    margin: 0;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }

  .frd-roster {
    display: grid;
    gap: var(--sp-1);
    max-height: 220px;
    overflow: auto;
  }

  .frd-roster-row {
    display: block;
    width: 100%;
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid var(--divider);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text);
    font-size: var(--fs-md);
    text-align: left;
    cursor: pointer;
  }

  .frd-roster-row:hover {
    background: var(--accent-soft);
  }

  .frd-roster-row.selected {
    border-color: var(--accent);
    background: var(--accent-soft2);
    color: var(--accent-emphasis);
  }

  .frd-preview {
    max-height: 320px;
    overflow: auto;
    padding: var(--sp-3);
    border: 1px solid var(--divider);
    border-radius: 6px;
    background: var(--inset);
    color: var(--text);
    font-size: var(--fs-md);
    line-height: 1.5;
  }

  .frd-cost {
    margin: 0;
    color: var(--text-2);
    font-size: var(--fs-sm);
  }

  .frd-apply-group {
    display: inline-flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 2px;
  }

  .frd-apply-note {
    color: var(--text-3);
    font-size: var(--fs-xs);
  }
</style>
