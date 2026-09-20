// Beat roster id stamping (#2043 slice 3): a plot board beat is now edited
// through PlotBeatSections/BodyListSection, which writes the whole roster on
// every keystroke and knows nothing about ids — the backend mints one for a
// beat that doesn't carry one yet, on save. Pure helper so the node component
// (PlotPlotlineNode / PlotArcNode) can reconcile the saved roster's ids back
// onto its draft without re-deriving the positional match itself.
import type { MetadataValue } from "@/lib/types";

function recordOf(item: MetadataValue): Record<string, MetadataValue> | null {
  return item != null && typeof item === "object" && !Array.isArray(item) ? (item as Record<string, MetadataValue>) : null;
}

/** After a save, copy the backend-minted `id` onto each item that has none, positionally
 *  (the roster was sent in this order). Returns the new array, or null when nothing changed
 *  (so the caller doesn't push a needless new reference into the editors). Non-record items
 *  and items that already carry a non-empty string id are returned as-is. */
export function withStampedBeatIds(current: MetadataValue, saved: MetadataValue): MetadataValue[] | null {
  if (!Array.isArray(current) || !Array.isArray(saved)) return null;
  let changed = false;
  const next = current.map((item, index) => {
    const record = recordOf(item);
    if (!record || (typeof record.id === "string" && record.id)) return item;
    const savedRecord = recordOf(saved[index]);
    const savedId = savedRecord?.id;
    if (typeof savedId !== "string" || !savedId) return item;
    changed = true;
    return { ...record, id: savedId };
  });
  return changed ? next : null;
}
