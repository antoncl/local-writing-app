<script lang="ts">
  // Promote a lore entry to an ancestor project (ADR-0078 §2/§9), launched from
  // the editor's "Promote to…" doc action on an owned lore entry. Self-contained
  // like DirectoryPickerModal: it fetches the destination roster and the dry-run
  // plan itself on the closed→open transition, rather than the parent staging
  // them — there is nothing about "what ancestors exist" or "what would move"
  // that belongs anywhere but here. The parent only owns the `open` guard (the
  // entry to promote) and what happens to the pane once the promotion commits
  // (`onPromoted`), mirroring ValidateModal/AIPolicyModal's split.
  //
  // Backend errors (409 already-inherited, 400 not-a-declared-ancestor) surface
  // inline rather than the app-wide error banner — a promotion needs the author
  // looking at the dialogue that caused it, not a toast that vanishes.
  import { api } from "@/lib/api";
  import Modal from "@/components/dialogs/Modal.svelte";
  import type { LoreEntry, PromotionPlan, PromotionTarget } from "@/lib/types";

  let {
    open,
    entry,
    onClose,
    onFlush,
    onPromoted,
  }: {
    open: boolean;
    // The lore entry being promoted. Only read at the closed→open transition,
    // like FinalizeRoleplayDialog's `openScene` — the modal owns its own copy
    // of "what's loading" for the life of one promotion attempt.
    entry: LoreEntry | null;
    onClose: () => void;
    // Flush the pane's pending (autosave-debounced) edits before promoting —
    // the promoted file must carry the author's latest words, mirroring
    // FinalizeRoleplayDialog's `onFlush`.
    onFlush?: (entryId: string) => Promise<void>;
    // Called with the now-inherited entry on a successful commit. The parent
    // owns the pane/roster refresh (editorPanes.applyPromotedLoreEntry), same
    // division as onFinalized.
    onPromoted: (entry: LoreEntry) => void;
  } = $props();

  let targets = $state<PromotionTarget[]>([]);
  let targetsLoading = $state(false);
  let targetsError = $state<string | null>(null);

  let selectedLayerId = $state<string | null>(null);
  let plan = $state<PromotionPlan | null>(null);
  let previewLoading = $state(false);
  let previewError = $state<string | null>(null);

  let promoting = $state(false);
  let promoteError = $state<string | null>(null);

  let selectedTargetLabel = $derived(
    targets.find((t) => t.layer_id === selectedLayerId)?.label ?? "",
  );

  // Load the roster on each closed→open transition only, matching
  // DirectoryPickerModal / AIPolicyModal — a later external change (unrelated
  // navigation) must not re-fetch mid-dialogue.
  let wasOpen = false;
  $effect(() => {
    if (open && entry && !wasOpen) {
      wasOpen = true;
      void loadTargets(entry.id);
    } else if (!open) {
      wasOpen = false;
    }
  });

  async function loadTargets(entryId: string): Promise<void> {
    targetsLoading = true;
    targetsError = null;
    targets = [];
    selectedLayerId = null;
    plan = null;
    previewError = null;
    promoteError = null;
    try {
      targets = await api.promotionTargets();
      // Outermost-first; the nearest ancestor (the usual pick) is last.
      const nearest = targets[targets.length - 1];
      if (nearest) {
        selectedLayerId = nearest.layer_id;
        await loadPreview(entryId, nearest.layer_id);
      }
    } catch (err) {
      targetsError = err instanceof Error ? err.message : String(err);
    } finally {
      targetsLoading = false;
    }
  }

  async function loadPreview(entryId: string, targetLayerId: string): Promise<void> {
    previewLoading = true;
    previewError = null;
    plan = null;
    try {
      plan = await api.previewLorePromotion(entryId, targetLayerId);
    } catch (err) {
      previewError = err instanceof Error ? err.message : String(err);
    } finally {
      previewLoading = false;
    }
  }

  function selectTarget(layerId: string): void {
    if (!entry || layerId === selectedLayerId) return;
    selectedLayerId = layerId;
    void loadPreview(entry.id, layerId);
  }

  async function confirmPromote(): Promise<void> {
    if (!entry || !selectedLayerId) return;
    promoting = true;
    promoteError = null;
    try {
      await onFlush?.(entry.id);
      const promoted = await api.promoteLoreEntry(entry.id, selectedLayerId);
      onPromoted(promoted);
      onClose();
    } catch (err) {
      promoteError = err instanceof Error ? err.message : String(err);
    } finally {
      promoting = false;
    }
  }
</script>

{#if open && entry}
  <Modal
    title="Promote to…"
    label={`Promote ${entry.title}`}
    frameStyle="--modal-width: min(480px, 92vw); --modal-max-height: 80vh; --modal-overflow-y: auto;"
  >
    <p class="promote-lead">Lift <strong>{entry.title}</strong> into a shared ancestor project — every descendant will inherit it from there.</p>

    {#if targetsLoading}
      <p class="promote-status">Looking for ancestor projects…</p>
    {:else if targetsError}
      <p class="promote-error">{targetsError}</p>
    {:else if targets.length === 0}
      <p class="promote-status">No ancestor projects to promote into.</p>
    {:else}
      <fieldset class="promote-destination">
        <legend>Destination</legend>
        {#each targets as target (target.layer_id)}
          <label>
            <input
              type="radio"
              name="promote-destination"
              value={target.layer_id}
              checked={selectedLayerId === target.layer_id}
              onchange={() => selectTarget(target.layer_id)}
            />
            {target.label}
          </label>
        {/each}
      </fieldset>

      {#if previewLoading}
        <p class="promote-status">Checking what would move…</p>
      {:else if previewError}
        <p class="promote-error">{previewError}</p>
      {:else if plan}
        <div class="promote-plan">
          <section class="promote-bucket">
            <h3>Moves to {plan.destination.label}</h3>
            <p class="promote-note">Its title, body, and metadata travel with it.</p>
            {#if plan.travels.length > 0}
              <ul>
                {#each plan.travels as field}
                  <li><span class="promote-field">{field}</span></li>
                {/each}
              </ul>
            {/if}
          </section>

          {#if plan.stays_in_origin.length > 0}
            <section class="promote-bucket">
              <h3>Stays in this project</h3>
              <ul>
                {#each plan.stays_in_origin as item (item.field)}
                  <li><span class="promote-field">{item.field}</span> — {item.reason}</li>
                {/each}
              </ul>
            </section>
          {/if}

          {#if plan.invisible_at_destination.length > 0}
            <section class="promote-bucket">
              <h3>Hidden at {plan.destination.label} until promoted</h3>
              <ul>
                {#each plan.invisible_at_destination as field}
                  <li><span class="promote-field">{field}</span></li>
                {/each}
              </ul>
              <p class="promote-note">Their field definitions live only here — they reappear once a definition is promoted too.</p>
            </section>
          {/if}
        </div>
      {/if}
    {/if}

    {#if promoteError}
      <p class="promote-error">{promoteError}</p>
    {/if}

    {#snippet actions()}
      <button type="button" onclick={onClose} disabled={promoting}>Close</button>
      {#if targets.length > 0}
        <button
          type="button"
          class="primary"
          disabled={!selectedLayerId || !plan || previewLoading || promoting}
          onclick={confirmPromote}
        >
          {promoting ? "Promoting…" : `Promote to ${selectedTargetLabel}`}
        </button>
      {/if}
    {/snippet}
  </Modal>
{/if}

<style>
  .promote-lead {
    margin: 0;
    color: var(--text-2);
    font-size: var(--fs-md);
    line-height: 1.4;
  }

  .promote-status {
    margin: 0;
    color: var(--text-2);
    font-size: var(--fs-md);
  }

  .promote-destination {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin: 0;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: var(--r-md);
  }

  .promote-destination legend {
    padding: 0 4px;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }

  .promote-destination label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-md);
    color: var(--text-1);
  }

  .promote-plan {
    display: grid;
    gap: 10px;
  }

  .promote-bucket h3 {
    margin: 0 0 4px;
    font-size: var(--fs-sm);
    text-transform: uppercase;
    letter-spacing: 0.02em;
    color: var(--text-2);
  }

  .promote-bucket ul {
    margin: 0;
    padding-left: 18px;
    display: grid;
    gap: 3px;
  }

  .promote-bucket li {
    font-size: var(--fs-sm);
    color: var(--text-1);
    line-height: 1.4;
  }

  .promote-field {
    font-weight: var(--w-semibold);
  }

  .promote-note {
    margin: 4px 0 0;
    font-size: var(--fs-sm);
    color: var(--text-2);
    line-height: 1.35;
  }

  .promote-error {
    margin: 0;
    padding: 8px 10px;
    border-radius: var(--r-md);
    background: var(--danger-soft);
    color: var(--danger);
    font-size: var(--fs-sm);
  }
</style>
