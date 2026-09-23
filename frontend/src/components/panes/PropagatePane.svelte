<script lang="ts">
  // The Propagate confirm surface (ADR-0091 §2/§7): a settled change to a lore
  // entry, its candidates tickable and grouped from their REASONS (Declared /
  // Markers / Mentions — never the wire's `tier`), the source's diff beside
  // them behind a draggable divider. An on-demand editor tab (never a dialog —
  // a candidate can be opened beside it before deciding), homed via
  // `propagate.svelte.ts` / `workspaceLayout`. Read-only except for the one
  // Confirm write the store makes; this component and `PropagateDiff` (the
  // diff column, split out so the fetch/rule-line/nothing-changed logic isn't
  // all in one file) only render state and forward gestures to the store.
  import PickTree, { type PickTreeRow } from "@/components/widgets/PickTree.svelte";
  import SplitHandle from "@/components/widgets/SplitHandle.svelte";
  import PropagateDiff from "@/components/panes/PropagateDiff.svelte";
  import { propagate } from "@/lib/stores/propagate.svelte";
  import {
    clampListWidth,
    propagateLayout,
    PROPAGATE_DIFF_COLUMN_MIN,
  } from "@/lib/stores/propagateLayout.svelte";
  import { notchWhenCapturedDistinct } from "@/lib/utils/snapshotTime";
  import { groupedItems } from "@/lib/utils/candidateGroups";
  import type { CandidateGroup, ChangeCandidate, ChangeCandidateReason } from "@/lib/types";

  const GROUPS: { key: CandidateGroup; label: string }[] = [
    { key: "declared", label: "Declared" },
    { key: "markers", label: "Markers" },
    { key: "mentions", label: "Mentions" },
  ];

  // ADR-0090/0091 §7: reasons must stay visible, in the app's own vocabulary (⤳
  // is the mutation mark). Several reasons on one candidate join with " · ".
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
  // (tri-state) header row per non-empty group, then one leaf row per
  // candidate at depth 1. The design language has no scene-kind colour, so a
  // scene candidate is left unstriped rather than inventing one.
  let rows = $derived.by<PickTreeRow[]>(() => {
    if (!propagate.candidates) return [];
    const groups = groupedItems(propagate.candidates);
    const out: PickTreeRow[] = [];
    for (const group of GROUPS) {
      const groupItems = groups[group.key];
      if (groupItems.length === 0) continue;
      const keptCount = groupItems.filter((item) => propagate.kept.has(item.id)).length;
      const allKept = keptCount === groupItems.length;
      const folded = propagate.folded.has(group.key);
      out.push({
        key: `group:${group.key}`,
        depth: 0,
        hasChildren: true,
        collapsed: folded,
        isContainer: true,
        pickable: true,
        state: keptCount === 0 ? "off" : allKept ? "on" : "indeterminate",
        title: group.label,
        count: null,
        countNoun: "item",
        countText: `${keptCount} of ${groupItems.length}`,
        onToggle: () => propagate.setGroup(group.key, !allKept),
        onCollapse: () => propagate.toggleFold(group.key),
      });
      if (folded) continue;
      for (const item of groupItems) {
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
  // Newest CAPTURE first — the API lists snapshots (captured_at, id)-sorted
  // oldest first, and the labels below read capture time (ADR-0091 §7), so
  // the order must follow the same clock; `inNotchOrder` (content time) is
  // the strip's rule, not this selector's.
  let snapshotsNewestFirst = $derived([...propagate.snapshots].reverse());
  let sinceValue = $derived(propagate.candidates?.baseline_snapshot_id ?? "");

  // ADR-0091 §7: the "since" labels read capture time, the same deliberate
  // exception `PropagateDiff`'s nothing-changed sentence takes (see
  // `notchWhenCaptured`) — "since" measures from when a baseline was TAKEN.
  // Computed for the list as a whole (#2141): two captures on one day would
  // both read "yesterday", so a shared phrase carries its clock time too.
  let sinceWhen = $derived(notchWhenCapturedDistinct(snapshotsNewestFirst));
  function snapshotLabel(snapshot: (typeof propagate.snapshots)[number], when: string): string {
    return `${snapshot.origin === "propagation" ? "last propagation" : "snapshot"} · ${when}`;
  }

  function onSinceChange(event: Event): void {
    void propagate.setBaseline((event.target as HTMLSelectElement).value);
  }

  // The list/diff divider's drag (ADR-0091 §7): the gesture lives in the
  // shared `SplitHandle`; this pane keeps only the clamp (via
  // `propagateLayout.setListWidth`) and the live width during the drag.
  function onDividerDragStart(): void {}
  function onDividerDrag(event: MouseEvent): void {
    const paneRect = paneEl?.getBoundingClientRect();
    if (!paneRect) return;
    propagateLayout.listWidth = clampListWidth(event.clientX - paneRect.left, paneRect.width);
  }
  function onDividerDragEnd(): void {
    propagateLayout.setListWidth(propagateLayout.listWidth);
  }

  let paneEl: HTMLElement | undefined = $state();
</script>

<div class="propagate-pane" bind:this={paneEl}>
  <div class="propagate-head">
    <h2>Propagate <span class="serif">{propagate.sourceTitle}</span></h2>
    <div class="since">
      <label for="propagate-since">since</label>
      <select id="propagate-since" value={sinceValue} onchange={onSinceChange}>
        <option value="">the whole entry</option>
        {#each snapshotsNewestFirst as snapshot, i (snapshot.id)}
          <option value={snapshot.id}>{snapshotLabel(snapshot, sinceWhen[i] ?? "")}</option>
        {/each}
      </select>
    </div>
  </div>

  {#if propagate.error}
    <p class="muted propagate-error">{propagate.error}</p>
  {:else if propagate.loading && !propagate.candidates}
    <p class="muted">Loading…</p>
  {:else}
    <div class="propagate-body" style={`grid-template-columns: min(${propagateLayout.listWidth}px, calc(100% - ${PROPAGATE_DIFF_COLUMN_MIN}px)) auto minmax(0, 1fr)`}>
      <div class="propagate-list">
        <PickTree {rows} ariaLabel={`Candidates for ${propagate.sourceTitle}`} />
      </div>
      <SplitHandle
        orientation="vertical"
        label="Resize the candidate list"
        onDragStart={onDividerDragStart}
        onDrag={onDividerDrag}
        onDragEnd={onDividerDragEnd}
        class="propagate-divider"
      />
      <PropagateDiff
        sourceId={propagate.sourceId}
        sourceTitle={propagate.sourceTitle}
        candidates={propagate.candidates}
        snapshots={propagate.snapshots}
      />
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
    min-height: 0;
    flex: 1;
    overflow: hidden;
  }

  @media (max-width: 760px) {
    .propagate-body {
      grid-template-columns: 1fr !important;
      overflow: auto;
    }
    .propagate-body > :global(.propagate-divider) {
      display: none;
    }
  }

  .propagate-list {
    padding: 8px 12px 12px;
    overflow: auto;
    min-height: 0;
  }

  /* The shared SplitHandle sits in the grid's own middle column here (unlike
     the rail's absolute-inset use) — a normal grid track, not an overlay. */
  .propagate-body > :global(.propagate-divider) {
    width: 7px;
    align-self: stretch;
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
