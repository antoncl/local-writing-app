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

/** After a save, copy the backend-minted id onto each item that has none, positionally
 *  (the roster was sent in this order). `key` is the field's declared identity member
 *  (ADR-0096 §1; "id" for the plot board's beat-specific callers). Returns the new
 *  array, or null when nothing changed (so the caller doesn't push a needless new
 *  reference into the editors). Non-record items and items that already carry a
 *  non-empty string id are returned as-is. */
export function withStampedBeatIds(current: MetadataValue, saved: MetadataValue, key = "id"): MetadataValue[] | null {
  if (!Array.isArray(current) || !Array.isArray(saved)) return null;
  let changed = false;
  const next = current.map((item, index) => {
    const record = recordOf(item);
    if (!record || (typeof record[key] === "string" && record[key])) return item;
    const savedRecord = recordOf(saved[index]);
    const savedId = savedRecord?.[key];
    if (typeof savedId !== "string" || !savedId) return item;
    changed = true;
    return { ...record, [key]: savedId };
  });
  return changed ? next : null;
}

/** The document-pane counterpart of {@link withStampedBeatIds} (#2255): after a pane
 *  save, adopt the ids the backend minted (or re-salted for a duplicate) into the
 *  draft, so the pane isn't left dirty against its own save and re-minting a fresh id
 *  every autosave. `identityKeys` maps a field id to its declared identity member's
 *  key (ADR-0096 §1) — every list field of the draft's entry type that declares one,
 *  read off the schema by the caller (editorPanes.svelte.ts). Only a list the author
 *  left untouched while the save was in flight (`draft[field]` still equals what was
 *  `sent`) is stamped — then the saved roster lines up with it position for position,
 *  and taking the saved id wholesale is exact. Returns the new metadata, or null when
 *  nothing changed. */
export function adoptSavedItemIds(
  draft: Record<string, MetadataValue>,
  sent: Record<string, MetadataValue>,
  saved: Record<string, MetadataValue>,
  identityKeys: Record<string, string>,
): Record<string, MetadataValue> | null {
  let next: Record<string, MetadataValue> | null = null;
  for (const [field, key] of Object.entries(identityKeys)) {
    const current = draft[field];
    const returned = saved[field];
    if (!Array.isArray(current) || !Array.isArray(returned) || current.length !== returned.length) continue;
    if (JSON.stringify(current) !== JSON.stringify(sent[field])) continue;
    let changed = false;
    const stamped = current.map((item, index) => {
      const record = recordOf(item);
      const savedId = recordOf(returned[index])?.[key];
      if (!record || typeof savedId !== "string" || !savedId || record[key] === savedId) return item;
      changed = true;
      return { ...record, [key]: savedId };
    });
    if (changed) next = { ...(next ?? draft), [field]: stamped };
  }
  return next;
}
