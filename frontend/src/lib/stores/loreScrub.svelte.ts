// Time-travel scrub state for one lore card (#64, ADR-0013; per-unit stops
// since #70/ADR-0016). Extracted from NodeEditor as a per-instance rune
// controller: the card owns its scrub position — 0 = base/book-start (fully
// editable, today's card), i ≥ 1 = a read-only effective overlay as of the
// i-th mutation UNIT. The ordered points feed both the bottom scrubber strip
// and the rail's mutation list — two views of one dataset, fetched once here.
import { api } from "@/lib/api";
import { groupMutationUnits } from "@/lib/editor-core/mutationUnits";
import type { MutationMarkerRecord } from "@/lib/types";

export class LoreScrubController {
  markers = $state<MutationMarkerRecord[]>([]);
  index = $state(0);
  /** Override map of ONLY the mutated fields at the scrub point (may include
   *  the intrinsic `title` / `body`). Membership = "changed by here". */
  overrides = $state<Record<string, string | string[]> | null>(null);
  units = $derived(groupMutationUnits(this.markers));

  // The entity the markers belong to, and a monotonic token so out-of-order
  // responses from rapid scrubbing (or an entity switch mid-flight) can't
  // overwrite the latest position.
  #entityId: string | null = null;
  #seq = 0;

  /** (Re)load the entity's ordered mutation points, resetting to base —
   *  either the entity changed or a scene save touched the mutations index
   *  (#63), and both may have moved/removed stops. Returns a cancel fn for
   *  the fetch (the caller's $effect teardown). */
  load(entityId: string | null): () => void {
    this.index = 0;
    this.overrides = null;
    this.#entityId = entityId;
    this.#seq++;
    if (!entityId) {
      this.markers = [];
      return () => {};
    }
    let cancelled = false;
    api
      .getEntityMutations(entityId)
      .then((res) => {
        if (!cancelled) this.markers = res.items;
      })
      .catch(() => {
        if (!cancelled) this.markers = [];
      });
    return () => {
      cancelled = true;
    };
  }

  async scrubTo(index: number): Promise<void> {
    this.index = index;
    if (index === 0) {
      this.overrides = null;
      return;
    }
    // "As of" a unit = every row of it live → resolve at the unit's last
    // record (carrier rows share one offset; a legacy group= spans several).
    const unit = this.units[index - 1];
    const marker = unit?.records[unit.records.length - 1];
    const entityId = this.#entityId;
    if (!marker || !entityId) return;
    const seq = ++this.#seq;
    const fresh = () => seq === this.#seq && this.#entityId === entityId;
    try {
      // Resolve at the marker's own position so it counts as live (offset <=
      // position), giving the effective state "as of" this change.
      const res = await api.getEntityEffectiveState(entityId, marker.scene_id, marker.offset);
      if (fresh()) this.overrides = res.values;
    } catch {
      // Can't resolve → don't pretend: fall back to the editable base.
      if (fresh()) {
        this.index = 0;
        this.overrides = null;
      }
    }
  }
}
