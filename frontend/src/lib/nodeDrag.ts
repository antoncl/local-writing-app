// Node drag-and-drop (#2413): dragging a row from a node list (manuscript, research,
// lore) onto a chat's context picker picks that node. The payload is the picker's own
// `NodePickerRef`, so a drop writes exactly the value the popover would.
//
// Same shape as plotDnd.ts: a custom MIME so a drop target can tell a node-drag from any
// other drag, with the ref ALSO held in memory — during `dragover` the browser withholds
// the data (only `types` is readable), so admission while hovering reads the in-memory
// ref and the real payload is read on `drop`.

import type { MetadataSchema, NodePickerRef, StructureDocument } from "@/lib/types";
import { dropPickAt } from "@/lib/utils/manuscriptPickTree";
import { allowedTypeSet, type pickerMembership } from "@/lib/utils/pickerSources";
import { entryTypeIsA } from "@/lib/utils/schemaTypeHelpers";

export const NODE_DND_MIME = "application/x-local-writing-node";

let current: NodePickerRef | null = null;

export function setNodeDrag(event: DragEvent, ref: NodePickerRef): void {
  current = ref;
  const dt = event.dataTransfer;
  if (!dt) return;
  dt.setData(NODE_DND_MIME, JSON.stringify(ref));
  // Coexist with a list's own reorder drag (it sets "move" first, from the handle, and
  // this bubbles after it): widen to copyMove so both a reorder drop and a picker drop
  // are allowed; a plain row drag has nothing set yet and is a copy.
  dt.effectAllowed = dt.effectAllowed === "move" ? "copyMove" : "copy";
}

/** The node being dragged by `event`, or null — readable during `dragover`. The event
 * must carry the MIME, so a stale ref (a drag whose source unmounted before `dragend`)
 * never answers for some other drag. */
export function currentNodeDrag(event: DragEvent): NodePickerRef | null {
  return event.dataTransfer?.types.includes(NODE_DND_MIME) ? current : null;
}

export function clearNodeDrag(): void {
  current = null;
}

/** The dropped ref: the MIME payload, or null for any other drag. */
export function readNodeDrag(event: DragEvent): NodePickerRef | null {
  const raw = event.dataTransfer?.getData(NODE_DND_MIME);
  if (!raw) return null;
  try {
    const ref = JSON.parse(raw) as NodePickerRef;
    return ref && typeof ref.id === "string" && typeof ref.kind === "string" ? ref : null;
  } catch {
    return null; // malformed — not one of ours
  }
}

export interface DropPickOptions {
  membership: ReturnType<typeof pickerMembership>;
  schema: MetadataSchema | null;
  excludeIds: string[];
  multiple: boolean;
  structure: StructureDocument | null;
}

const refKey = (ref: NodePickerRef): string => `${ref.kind}:${ref.id}`;

/** Whether the picker's scope admits `ref`: its kind, its entry_type when the kind is
 * narrowed (a manuscript container is gated by its scene sub-types, not itself), and
 * not an excluded id. */
export function admitsRef(ref: NodePickerRef, opts: DropPickOptions): boolean {
  if (!opts.membership.kinds.includes(ref.kind) || opts.excludeIds.includes(ref.id)) return false;
  const allowed = allowedTypeSet(opts.membership, opts.schema, ref.kind);
  if (allowed.size === 0) return true;
  const entryType = ref.entry_type ?? "";
  if (ref.kind === "manuscript" && entryTypeIsA(opts.schema, entryType, "manuscript:container")) return true;
  return allowed.has(entryType);
}

/** The picker value after dropping `ref`, or null for no change: not admitted, or
 * already picked (a drop adds, it never unpicks). Single-select replaces; a manuscript
 * container picks as the picker's tree does. */
export function dropPick(value: NodePickerRef[], ref: NodePickerRef, opts: DropPickOptions): NodePickerRef[] | null {
  if (!admitsRef(ref, opts)) return null;
  if (value.some((r) => refKey(r) === refKey(ref))) return null;
  if (!opts.multiple) return [ref];
  if (ref.kind === "manuscript" && opts.structure) return dropPickAt(opts.structure, value, ref);
  return [...value, ref];
}
