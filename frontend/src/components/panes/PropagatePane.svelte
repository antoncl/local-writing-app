<script lang="ts">
  // The Propagate confirm surface (ADR-0090 §7, Amendment 1/2): a settled
  // change to a lore entry, its candidates tickable and grouped by tier, the
  // source's diff beside them. An on-demand editor tab (never a dialog — a
  // candidate can be opened beside it before deciding), homed via
  // `propagate.svelte.ts` / `workspaceLayout`. Read-only except for the one
  // Confirm write the store makes; this component only renders state and
  // forwards gestures to the store.
  import PickTree, { type PickTreeRow } from "@/components/widgets/PickTree.svelte";
  import ReadOnlyBodyOverlay from "@/components/editor/body/ReadOnlyBodyOverlay.svelte";
  import { propagate } from "@/lib/stores/propagate.svelte";
  import { api } from "@/lib/api";
  import { notchWhen, inNotchOrder } from "@/lib/utils/snapshotTime";
  import { diffRuns, fieldDiffs, listDiff } from "@/lib/utils/snapshotDiff";
  import { renderDiffRuns } from "@/lib/utils/diffRuns";
  import type { ChangeCandidate, ChangeCandidateReason, ChangeCandidateTier, FieldDiff } from "@/lib/types";

  const TIERS: { key: ChangeCandidateTier; label: string }[] = [
    { key: "declared", label: "Declared" },
    { key: "marker_untouched", label: "Markers on untouched fields" },
    { key: "mention", label: "Mentions" },
  ];

  // ADR-0090 §7: reasons must stay visible, in the app's own vocabulary (⤳ is
  // the mutation mark). Several reasons on one candidate join with " · ".
  function reasonText(sourceTitle: string, reason: ChangeCandidateReason): string {
    switch (reason.route) {
      case "references_source":
        return `\`${reason.field_id}\` refers to ${sourceTitle}`;
      case "referenced_by_source":
        return `${sourceTitle}'s \`${reason.field_id}\` refers here`;
      case "mutates_source":
        return `⤳ \`${reason.field_id}\`` + (reason.field_changed ? " changed" : " untouched by this change");
      case "mentions_source":
        return `mentions ${sourceTitle}`;
      case "mentioned_by_source":
        return `${sourceTitle} names this entry`;
    }
  }

  function detailFor(candidate: ChangeCandidate): string {
    return candidate.reasons.map((reason) => reasonText(propagate.sourceTitle, reason)).join(" · ");
  }

  // The candidate list, flattened into PickTree's row shape: one pickable
  // (tri-state) header row per non-empty tier, then one leaf row per
  // candidate at depth 1. The design language has no scene-kind colour, so a
  // scene candidate is left unstriped rather than inventing one.
  let rows = $derived.by<PickTreeRow[]>(() => {
    const items = propagate.candidates?.items ?? [];
    const out: PickTreeRow[] = [];
    for (const tier of TIERS) {
      const tierItems = items.filter((item) => item.tier === tier.key);
      if (tierItems.length === 0) continue;
      const keptCount = tierItems.filter((item) => propagate.kept.has(item.id)).length;
      const allKept = keptCount === tierItems.length;
      const folded = propagate.folded.has(tier.key);
      out.push({
        key: `group:${tier.key}`,
        depth: 0,
        hasChildren: true,
        collapsed: folded,
        isContainer: true,
        pickable: true,
        state: keptCount === 0 ? "off" : allKept ? "on" : "indeterminate",
        title: tier.label,
        count: null,
        countNoun: "item",
        countText: `${keptCount} of ${tierItems.length}`,
        onToggle: () => propagate.setGroup(tier.key, !allKept),
        onCollapse: () => propagate.toggleFold(tier.key),
      });
      if (folded) continue;
      for (const item of tierItems) {
        out.push({
          key: item.id,
          depth: 1,
          hasChildren: false,
          collapsed: false,
          isContainer: false,
          pickable: true,
          state: propagate.kept.has(item.id) ? "on" : "off",
          title: item.title,
          detail: detailFor(item),
          stripeColor: item.kind === "lore" ? "var(--k-lore)" : null,
          count: null,
          countNoun: "item",
          onToggle: () => propagate.toggle(item.id),
          onCollapse: () => {},
        });
      }
    }
    return out;
  });

  let keptTotal = $derived(propagate.kept.size);
  let confirmLabel = $derived(
    keptTotal > 0 ? `Confirm ${keptTotal} review item${keptTotal === 1 ? "" : "s"}` : "Confirm",
  );
  let footNote = $derived(
    keptTotal > 0
      ? `Writes ${keptTotal} todo${keptTotal === 1 ? "" : "s"} and a snapshot of ${propagate.sourceTitle}. Nothing else.`
      : "Nothing kept — nothing will be written.",
  );

  // The "since" selector — newest snapshot first, the whole-entry option
  // always first. Selected value is the RESOLVED baseline (`candidates`'s
  // own), not the store's explicit request, so the default shows correctly
  // before the writer has touched it.
  let snapshotsNewestFirst = $derived([...inNotchOrder(propagate.snapshots)].reverse());
  let sinceValue = $derived(propagate.candidates?.baseline_snapshot_id ?? "");

  function snapshotLabel(snapshot: (typeof propagate.snapshots)[number]): string {
    return `${snapshot.origin === "propagation" ? "last propagation" : "snapshot"} · ${notchWhen(snapshot)}`;
  }

  function onSinceChange(event: Event): void {
    void propagate.setBaseline((event.target as HTMLSelectElement).value);
  }

  // ---- The right pane: the source's diff, since the resolved baseline. ----
  let diffFieldsState = $state<Record<string, FieldDiff>>({});
  let diffBodyHtml = $state("");
  let diffLoading = $state(false);
  let diffError = $state<string | null>(null);

  function formatFieldValue(value: unknown): string {
    if (value === null || value === undefined || value === "") return "(none)";
    if (Array.isArray(value)) return value.length ? value.map(String).join(", ") : "(none)";
    return String(value);
  }

  $effect(() => {
    const sourceId = propagate.sourceId;
    const candidates = propagate.candidates;
    if (!sourceId || !candidates) {
      diffFieldsState = {};
      diffBodyHtml = "";
      return;
    }
    const baseline = candidates.baseline_snapshot_id;
    let cancelled = false;
    diffLoading = true;
    diffError = null;
    void (async () => {
      try {
        let wasMetadata: Record<string, unknown> = {};
        let wasBody = "";
        if (baseline) {
          const detail = await api.readNodeSnapshot(sourceId, baseline);
          wasMetadata = detail.metadata;
          wasBody = detail.body;
        }
        const live = await api.getLoreEntry(sourceId);
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
  let diffSubtitle = $derived.by(() => {
    const c = propagate.candidates;
    if (!c) return "";
    if (c.whole_entry) return "No baseline: the whole entry counts as the change.";
    const n = diffFieldIds.length;
    const baselineSnapshot = propagate.snapshots.find((s) => s.id === c.baseline_snapshot_id);
    const since = baselineSnapshot ? notchWhen(baselineSnapshot) : "the last propagation";
    return `${n} field${n === 1 ? "" : "s"}${c.body_changed ? " and the body" : ""}, since ${since}.`;
  });
</script>

<div class="propagate-pane">
  <div class="propagate-head">
    <h2>Propagate <span class="serif">{propagate.sourceTitle}</span></h2>
    <div class="since">
      <label for="propagate-since">since</label>
      <select id="propagate-since" value={sinceValue} onchange={onSinceChange}>
        <option value="">the whole entry</option>
        {#each snapshotsNewestFirst as snapshot (snapshot.id)}
          <option value={snapshot.id}>{snapshotLabel(snapshot)}</option>
        {/each}
      </select>
    </div>
  </div>

  {#if propagate.error}
    <p class="muted propagate-error">{propagate.error}</p>
  {:else if propagate.loading && !propagate.candidates}
    <p class="muted">Loading…</p>
  {:else}
    <div class="propagate-body">
      <div class="propagate-list">
        <PickTree {rows} ariaLabel={`Candidates for ${propagate.sourceTitle}`} />
      </div>
      <aside class="propagate-diff" aria-label={`What changed in ${propagate.sourceTitle}`}>
        <h3>What changed</h3>
        <p class="sub">{diffSubtitle}</p>
        {#if diffError}
          <p class="muted">{diffError}</p>
        {:else if diffLoading}
          <p class="muted">Loading…</p>
        {:else}
          {#each diffFieldIds as fieldId (fieldId)}
            {@const diff = diffFieldsState[fieldId]}
            {@const items = listDiff(diff.was, diff.now)}
            <div class="frow">
              <div class="frow-key">{fieldId}</div>
              <div class="frow-vals">
                {#if items}
                  {#each items as item, index (index)}
                    <span class="pill" class:same={item.state === "same"} class:pill-was={item.state === "was"} class:pill-now={item.state === "now"}>{item.text}</span>
                  {/each}
                {:else}
                  {#if diff.was !== null && diff.was !== undefined}
                    <span class="pill pill-was">{formatFieldValue(diff.was)}</span>
                  {/if}
                  <span class="pill pill-now">{formatFieldValue(diff.now)}</span>
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
    </div>

    <div class="propagate-foot">
      <span class="note">{footNote}</span>
      <span class="spacer"></span>
      <button class="btn" type="button" onclick={() => propagate.close()}>Cancel</button>
      <button
        class="btn primary"
        type="button"
        disabled={keptTotal === 0 || propagate.loading}
        onclick={() => void propagate.confirm()}
      >
        {confirmLabel}
      </button>
    </div>
  {/if}
</div>

<style>
  .propagate-pane {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
  }

  .propagate-head {
    display: flex;
    align-items: baseline;
    gap: 12px;
    padding: 16px 24px 12px;
    border-bottom: 1px solid var(--divider);
  }

  .propagate-head h2 {
    font-family: var(--serif);
    font-size: var(--fs-xl);
    font-weight: var(--w-bold);
    margin: 0;
  }

  .propagate-head h2 .serif {
    font-family: var(--serif);
    color: var(--text);
  }

  .since {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--text-2);
    font-size: var(--fs-sm);
  }

  .since select {
    font: inherit;
    color: var(--text);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    padding: 3px 6px;
  }

  .propagate-body {
    display: grid;
    grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
    min-height: 0;
    flex: 1;
    overflow: hidden;
  }

  @media (max-width: 760px) {
    .propagate-body {
      grid-template-columns: 1fr;
      overflow: auto;
    }
    .propagate-diff {
      border-left: 0;
      border-top: 1px solid var(--divider);
    }
  }

  .propagate-list {
    padding: 8px 12px 12px;
    overflow: auto;
    min-height: 0;
  }

  .propagate-diff {
    border-left: 1px solid var(--divider);
    padding: 12px 24px 16px;
    overflow: auto;
    background: var(--panel);
    min-height: 0;
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

  .propagate-foot {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 24px;
    border-top: 1px solid var(--divider);
    background: var(--surface);
  }

  .propagate-foot .note {
    color: var(--text-3);
    font-size: var(--fs-sm);
  }

  .propagate-foot .spacer {
    flex: 1;
  }

  .btn {
    font: inherit;
    font-size: var(--fs-md);
    border-radius: var(--r-md);
    padding: 6px 14px;
    cursor: pointer;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-2);
  }

  .btn:hover {
    background: var(--inset);
  }

  .btn.primary {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
    font-weight: var(--w-semibold);
  }

  .btn.primary:hover {
    background: var(--accent-strong);
  }

  .btn.primary:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .muted {
    margin: 0;
    padding: 2px 4px;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }

  .propagate-error {
    color: var(--danger);
    padding: 16px 24px;
  }
</style>
