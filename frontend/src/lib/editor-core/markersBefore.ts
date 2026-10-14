// The ids of the mutation pills (anchors and closes) that sit before a position,
// in document order (#2491). A lore check sends them so the backend can read the
// lore as it stands where the selection starts: it looks each id up in the SAVED
// scene, so it needs ids, not an editor offset that drifts with unsaved edits.
import type { Node as PMNode } from "@tiptap/pm/model";

export function markerIdsBefore(doc: PMNode, pos: number): string[] {
  const ids: string[] = [];
  doc.nodesBetween(0, pos, (node) => {
    const attr =
      node.type.name === "mutation" ? node.attrs.anchorId
      : node.type.name === "mutationClose" ? node.attrs.closeId
      : null;
    if (attr) ids.push(String(attr));
    return true;
  });
  return ids;
}
