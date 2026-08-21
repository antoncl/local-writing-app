// Pure cost helpers for the editor footer's hint row (extracted from NodeEditor,
// #1261). Both are functions of their arguments — no component state — so they
// unit-test on their own and feed NodeEditor's `$derived`s, which pass the
// results down to EditorCostHint for display.
import { resolveColor } from "@/lib/utils/colors";
import type { EditableDocument, LoreEntrySummary, MetadataSchema } from "@/lib/types";

export type CharacterCostRow = { id: string; title: string; cost: number; color: string };

// Per-character roleplay cost for a scene, summed from the persisted
// ai_invocations log (ProseBodyView owns the raw map; this shapes it for the
// footer). Character colour resolves from the lore entry, falling back to a
// deterministic hue when unset. Sorted most-expensive first; zero/negatives drop.
export function characterCostRows(
  map: Record<string, number>,
  lore: LoreEntrySummary[],
  schema: MetadataSchema | null,
): CharacterCostRow[] {
  const rows: CharacterCostRow[] = [];
  for (const [id, cost] of Object.entries(map)) {
    if (typeof cost !== "number" || cost <= 0) continue;
    const entry = lore.find((e) => e.id === id);
    const title = entry?.title || id;
    const instance =
      entry && typeof entry.metadata?.color === "string" ? (entry.metadata.color as string) : null;
    const swatch = resolveColor(instance, entry?.entry_type, "lore", schema);
    let color: string;
    if (swatch) {
      color = swatch.hex;
    } else {
      let hash = 0;
      for (let i = 0; i < id.length; i++) {
        hash = (hash * 31 + id.charCodeAt(i)) | 0;
      }
      const hue = ((hash % 360) + 360) % 360;
      color = `hsl(${hue}, 62%, 48%)`;
    }
    rows.push({ id, title, cost, color });
  }
  rows.sort((a, b) => b.cost - a.cost);
  return rows;
}

export type RollupCost = { kind: "character" | "project"; value: number };

// All-time rollup cost surfaced as a single footer chip: character_cost on lore
// character entries, project_cost on the project node — backend populates both
// via `computed_metadata`. Trust the computed field as the surface contract;
// return null unless the kind matches this document and the number is non-zero.
export function rollupCostFor(
  scene: EditableDocument | null,
  documentKind: string,
): RollupCost | null {
  if (!scene) return null;
  const computed = (scene as { computed_metadata?: Record<string, unknown> }).computed_metadata;
  if (documentKind === "lore" && typeof computed?.character_cost === "number" && computed.character_cost > 0) {
    return { kind: "character", value: computed.character_cost };
  }
  if (documentKind === "project" && typeof computed?.project_cost === "number" && computed.project_cost > 0) {
    return { kind: "project", value: computed.project_cost };
  }
  return null;
}
