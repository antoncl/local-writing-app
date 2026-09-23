<script lang="ts">
  // The Propagate pane's diff column (ADR-0091 §7), split out of
  // `PropagatePane.svelte`: the fetch effect, the field rows with labelled
  // reference pills (#2133), the body overlay, the legend, the rule line, and
  // the nothing-changed sentence. Read-only — the pane's list column and its
  // Confirm write live in the parent; this component only shows the source's
  // diff for whatever `candidates` it is handed.
  import ReadOnlyBodyOverlay from "@/components/editor/body/ReadOnlyBodyOverlay.svelte";
  import { api } from "@/lib/api";
  import { notchWhenCaptured } from "@/lib/utils/snapshotTime";
  import { diffRuns, fieldDiffs, listDiff } from "@/lib/utils/snapshotDiff";
  import { renderDiffRuns } from "@/lib/utils/diffRuns";
  import { ruleLine as ruleLineFor, nothingChanged as nothingChangedFor } from "@/lib/utils/candidateGroups";
  import { fieldValueLabel, listItemLabel } from "@/lib/utils/fieldValueTitles";
  import { buildRefResolver } from "@/lib/utils/refResolve";
  import { structureStore } from "@/lib/stores/structure";
  import { loreEntriesStore } from "@/lib/stores/lore";
  import { promptEntriesStore } from "@/lib/stores/prompts";
  import { assistantEntriesStore } from "@/lib/stores/assistants";
  import { plotlineEntriesStore } from "@/lib/stores/plotlines";
  import { tagById } from "@/lib/stores/tagNodes";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import type { ChangeCandidateSet, FieldDiff, MetadataSchema, Snapshot } from "@/lib/types";

  let {
    sourceId,
    sourceTitle,
    candidates,
    snapshots,
  }: {
    sourceId: string | null;
    sourceTitle: string;
    candidates: ChangeCandidateSet | null;
    snapshots: Snapshot[];
  } = $props();

  // The SAME roster recipe MetadataPanel's rail uses for a reference value's
  // title (#2133) — structure, lore, prompts, assistants, plotlines, tags.
  let resolver = $derived(
    buildRefResolver({
      structure: $structureStore,
      loreEntries: $loreEntriesStore,
      promptEntries: $promptEntriesStore,
      assistantEntries: $assistantEntriesStore,
      plotEntries: $plotlineEntriesStore,
      tagById: $tagById,
    }),
  );
  let resolveTitle = $derived((id: string): string | null => resolver(id)?.title ?? null);

  // ---- The fetch effect: the source's diff, since the resolved baseline. ----
  let diffFieldsState = $state<Record<string, FieldDiff>>({});
  let diffBodyHtml = $state("");
  let diffLoading = $state(false);
  let diffError = $state<string | null>(null);

  $effect(() => {
    const id = sourceId;
    const set = candidates;
    if (!id || !set) {
      diffFieldsState = {};
      diffBodyHtml = "";
      return;
    }
    const baseline = set.baseline_snapshot_id;
    let cancelled = false;
    diffLoading = true;
    diffError = null;
    void (async () => {
      try {
        let wasMetadata: Record<string, unknown> = {};
        let wasBody = "";
        if (baseline) {
          const detail = await api.readNodeSnapshot(id, baseline);
          wasMetadata = detail.metadata;
          wasBody = detail.body;
        }
        const live = await api.getLoreEntry(id);
        if (cancelled) return;
        diffFieldsState = fieldDiffs(wasMetadata, "", live.metadata, "");
        diffBodyHtml = await renderDiffRuns(diffRuns(wasBody, live.body ?? ""), "both");
      } catch (error) {
        if (!cancelled) diffError = error instanceof Error ? error.message : String(error);
      } finally {
        if (!cancelled) diffLoading = false;
      }
    })();
    return () => {
      cancelled = true;
    };
  });

  let diffFieldIds = $derived(Object.keys(diffFieldsState).sort());

  let ruleLine = $derived(candidates ? ruleLineFor(candidates) : "");
  let nothingChanged = $derived(candidates ? nothingChangedFor(candidates) : false);

  // ADR-0091 §7: the nothing-changed sentence reads the baseline's CAPTURE
  // time, a deliberate exception to `notchWhen`'s content-time rule (see
  // `notchWhenCaptured`'s own comment) — "since" is asking when the writer
  // last confirmed, not how old the prose is.
  let nothingChangedSentence = $derived.by(() => {
    if (!candidates) return "";
    const baselineSnapshot = snapshots.find((s) => s.id === candidates!.baseline_snapshot_id);
    const age = baselineSnapshot ? notchWhenCaptured(baselineSnapshot) : "the last propagation";
    return `Nothing has changed since the last propagation, ${age} — pick an earlier snapshot to propagate an older change.`;
  });

  function itemLabel(schema: MetadataSchema | null, fieldId: string) {
    return (item: unknown) => listItemLabel(schema, fieldId, item, resolveTitle);
  }
</script>

<aside class="propagate-diff" aria-label={`What changed in ${sourceTitle}`}>
  <h3>What changed</h3>
  {#if ruleLine}
    <p class="sub">{ruleLine}</p>
  {/if}
  {#if diffError}
    <p class="muted">{diffError}</p>
  {:else if diffLoading}
    <p class="muted">Loading…</p>
  {:else if nothingChanged}
    <p class="muted nothing-changed">{nothingChangedSentence}</p>
  {:else}
    {#each diffFieldIds as fieldId (fieldId)}
      {@const diff = diffFieldsState[fieldId]}
      {@const items = listDiff(diff.was, diff.now, itemLabel($metadataSchemaStore, fieldId))}
      <div class="frow">
        <div class="frow-key">{fieldId}</div>
        <div class="frow-vals">
          {#if items}
            {#each items as item, index (index)}
              <span
                class="pill"
                class:same={item.state === "same"}
                class:pill-was={item.state === "was"}
                class:pill-now={item.state === "now"}
                >{item.label}</span
              >
            {/each}
          {:else}
            {#if diff.was !== null && diff.was !== undefined}
              <span class="pill pill-was">{fieldValueLabel($metadataSchemaStore, fieldId, diff.was, resolveTitle)}</span>
            {/if}
            <span class="pill pill-now">{fieldValueLabel($metadataSchemaStore, fieldId, diff.now, resolveTitle)}</span>
          {/if}
        </div>
      </div>
    {/each}
    {#if diffBodyHtml}
      <div class="propagate-prose">
        <ReadOnlyBodyOverlay html={diffBodyHtml} label="Body change" tone="snapshot" />
      </div>
    {/if}
    <div class="legend">
      <span class="pill same">unchanged</span>
      <span class="pill pill-was">was</span> the baseline &nbsp;
      <span class="pill pill-now">now</span> the entry today
    </div>
  {/if}
</aside>

<style>
  .propagate-diff {
    padding: 12px 24px 16px;
    overflow: auto;
    background: var(--panel);
    min-height: 0;
    height: 100%;
  }

  .propagate-diff h3 {
    font-family: var(--serif);
    font-size: var(--fs-lg);
    font-weight: var(--w-bold);
    margin: 0 0 4px;
  }

  .propagate-diff .sub {
    font-size: var(--fs-sm);
    color: var(--text-2);
    margin: 0 0 12px;
  }

  .frow {
    display: grid;
    grid-template-columns: 96px 1fr;
    column-gap: 12px;
    padding: 6px 0;
    border-top: 1px solid var(--divider);
    font-size: var(--fs-md);
  }

  .frow-key {
    color: var(--text-3);
    font-size: var(--fs-sm);
    padding-top: 2px;
    font-family: var(--mono);
  }

  .pill {
    display: inline-block;
    padding: 1px 6px;
    border-radius: var(--r-sm);
    margin: 1px 4px 1px 0;
    font-size: var(--fs-sm);
  }

  /* ADR-0044's one-colour rule: the tint says which version the text belongs
     to, so an item unchanged between was/now carries none (#2125). */
  .pill.same {
    background: transparent;
    color: var(--text);
    box-shadow: inset 0 0 0 1px var(--divider);
  }

  .pill-was {
    background: var(--diff-was-soft);
    color: var(--diff-was);
    box-shadow: inset 0 0 0 1px var(--diff-was-edge);
  }

  .pill-now {
    background: var(--diff-now-soft);
    color: var(--diff-now);
    box-shadow: inset 0 0 0 1px var(--diff-now-edge);
  }

  .propagate-prose {
    margin-top: 12px;
    border-top: 1px solid var(--divider);
    padding-top: 12px;
  }

  .legend {
    font-size: var(--fs-xs);
    color: var(--text-3);
    margin-top: 12px;
  }

  .muted {
    margin: 0;
    padding: 2px 4px;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }

  .nothing-changed {
    padding: 12px 4px;
  }
</style>
