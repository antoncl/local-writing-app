<script lang="ts">
  // The time-travel strip docked at the bottom of a lore card (#64, ADR-0013).
  // Discrete stops — stop 0 = base/edit (home), then one stop per mutation
  // UNIT (#70, ADR-0016: fewer, more meaningful stops; the tooltip lists the
  // rows changing there); effective state is constant BETWEEN points so there
  // is nothing to interpolate. Position is the mode: the rest position (stop
  // 0) means the card is editable, any stop ≥ 1 flips it to a read-only
  // effective overlay. Scrub state lives in NodeEditor (the card shell); this
  // strip only renders the stops and emits the chosen one.
  import { mutationRecordLabel } from "@/lib/editor-core/mutationNodes";
  import {
    mutationUnitGroupLabel,
    type MutationUnitGroup,
  } from "@/lib/editor-core/mutationUnits";

  let {
    units,
    index,
    onScrub,
  }: {
    units: MutationUnitGroup[];
    /** 0 = base (editable); i ≥ 1 = as of units[i-1]. */
    index: number;
    onScrub: (index: number) => void;
  } = $props();

  // Per-stop labels: originating scene, disambiguated when one scene holds
  // several of this entity's units ("Scene 5 · #2").
  const stopLabels = $derived.by(() => {
    const scenePath = (unit: MutationUnitGroup) => unit.records[0]?.scene_path ?? "";
    const totals = new Map<string, number>();
    for (const unit of units) {
      totals.set(scenePath(unit), (totals.get(scenePath(unit)) ?? 0) + 1);
    }
    const seen = new Map<string, number>();
    return units.map((unit) => {
      const path = scenePath(unit);
      const nth = (seen.get(path) ?? 0) + 1;
      seen.set(path, nth);
      return (totals.get(path) ?? 1) > 1 ? `${path || "scene"} · #${nth}` : path || "scene";
    });
  });

  function stopTooltip(i: number): string {
    const unit = units[i];
    const label = mutationUnitGroupLabel(unit);
    const rows =
      unit.records.length > 1
        ? ` — ${unit.records.map((record) => mutationRecordLabel({ ...record, name: "" })).join(", ")}`
        : "";
    return `${stopLabels[i]} — ${label}${rows}`;
  }
</script>

<div class="mutation-scrubber-strip" role="group" aria-label="Effective-state scrubber">
  <button
    type="button"
    class="scrub-stop scrub-base"
    class:current={index === 0}
    title="Base — book start (editable)"
    aria-label="Base — book start"
    onclick={() => onScrub(0)}
  >
    <i class="ti ti-home" aria-hidden="true"></i>
  </button>
  <div class="scrub-track">
    {#each units as unit, i (unit.unitId)}
      <button
        type="button"
        class="scrub-stop"
        class:current={index === i + 1}
        class:passed={index > i + 1}
        title={stopTooltip(i)}
        aria-label={`As of ${stopLabels[i]}`}
        onclick={() => onScrub(i + 1)}
      ></button>
    {/each}
  </div>
  <span class="scrub-asof" class:scrubbed={index > 0}>
    {#if index === 0}
      Base — book start
    {:else}
      As of {stopLabels[index - 1]} · read-only
    {/if}
  </span>
</div>

<style>
  .mutation-scrubber-strip {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 14px;
    border-top: 1px solid var(--divider);
    background: var(--inset);
    min-width: 0;
  }

  .scrub-stop {
    flex: none;
    width: 14px;
    height: 14px;
    padding: 0;
    border-radius: 50%;
    border: 2px solid color-mix(in srgb, var(--mutation-color) 42%, transparent);
    background: var(--surface);
    cursor: pointer;
    transition: border-color 80ms linear, background-color 80ms linear;
  }
  .scrub-stop:hover {
    border-color: var(--mutation-color);
  }
  .scrub-stop.passed {
    background: color-mix(in srgb, var(--mutation-color) 30%, var(--surface));
  }
  .scrub-stop.current {
    background: var(--mutation-color);
    border-color: var(--mutation-color);
  }

  /* Stop 0 — home/base. A touch larger, carries the edit affordance. */
  .scrub-base {
    width: 20px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 6px;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .scrub-base.current {
    color: #fff;
  }

  .scrub-track {
    display: flex;
    align-items: center;
    gap: 12px;
    position: relative;
    padding: 0 2px;
    overflow-x: auto;
    scrollbar-width: none;
  }
  /* The connecting rail behind the dots. */
  .scrub-track::before {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    top: 50%;
    height: 2px;
    background: color-mix(in srgb, var(--mutation-color) 24%, transparent);
  }
  .scrub-track .scrub-stop {
    position: relative;
  }

  .scrub-asof {
    margin-left: auto;
    flex: none;
    font-size: var(--fs-xs);
    color: var(--text-3);
    white-space: nowrap;
  }
  .scrub-asof.scrubbed {
    color: var(--mutation-color);
    font-weight: 600;
  }
</style>
