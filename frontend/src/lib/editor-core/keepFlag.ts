/** Keep a flag as a TODO (ADR-0099 decision 3). A flag - a line edit or a lore
 *  check's note - is the AI's proposal; Keep is how the writer makes one persist
 *  without deciding on it now. This module makes the TODO and nothing else: the
 *  caller resolves the flag as `kept` once it succeeds, and the flag's words are
 *  never touched.
 *
 *  Where the TODO lives: in a manuscript scene, a flag inside ONE textblock that
 *  no existing TODO touches becomes an embedded TODO over its words; anything
 *  else in a scene is a `scene`-scoped file TODO quoting the words, and any other
 *  node's body (a lore entry) gets a `node`-scoped one. */
import type { Node as PMNode } from "@tiptap/pm/model";
import type { NewTodo } from "@/lib/todoTypes";

/** A line edit's TODO text: why, and what the model proposed. */
export function editKeepNote(reason: string, replace: string): string {
  const proposed = `proposed: ${replace ? `“${replace}”` : "cut"}`;
  return reason ? `${reason} — ${proposed}` : proposed;
}

/** A note's TODO text: the problem and the entry it is about (a remark from a
 *  conversation has none, ADR-0100 §7: the problem alone). */
export const noteKeepNote = (problem: string, entryName: string): string =>
  entryName ? `${problem} (${entryName})` : problem;

/** What the caller lends: the embedded-mark write (null when it could not be
 *  made) and the file-TODO write (throws when it failed). */
export type KeepWriters = {
  markRange: (from: number, to: number, note: string) => string | null;
  createTodos: (items: NewTodo[]) => Promise<void>;
};

export type KeepRequest = {
  doc: PMNode;
  from: number;
  to: number;
  /** The flagged words, as the flag quoted them. */
  quote: string;
  note: string;
  /** True for a manuscript scene; false for any other node's body. */
  inScene: boolean;
  /** The scene id (`inScene`) or the node id. */
  docId: string;
};

/** True when the range lies inside one textblock, holds only text (an inline
 *  node — a hard break, a mutation pill — would split the mark into runs that
 *  aren't adjacent, and `enforceUnique` would keep only the first), and no TODO
 *  mark touches it. */
function canEmbed(doc: PMNode, from: number, to: number): boolean {
  if (!doc.resolve(from).sameParent(doc.resolve(to)) || !doc.resolve(from).parent.isTextblock) return false;
  let ok = true;
  doc.nodesBetween(from, to, (node) => {
    if (node.isTextblock) return true;
    if (!node.isText || node.marks.some((m) => m.type.name === "todoAnchor")) ok = false;
    return ok;
  });
  return ok;
}

/** Make the TODO. Throws when the write failed, so the flag can stay. */
export async function keepFlag(req: KeepRequest, writers: KeepWriters): Promise<void> {
  const { doc, from, to, quote, note, inScene, docId } = req;
  if (inScene && canEmbed(doc, from, to)) {
    if (writers.markRange(from, to, note) === null) throw new Error("Couldn't mark the TODO in the scene.");
    return;
  }
  const text = `${note} — “${quote}”`;
  await writers.createTodos([
    inScene ? { scope: "scene", scene_id: docId, text } : { scope: "node", node_id: docId, text },
  ]);
}
