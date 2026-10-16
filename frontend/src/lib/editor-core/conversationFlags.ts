/** Flags placed from a conversation (ADR-0100): the edits and notes one extraction
 *  turn made from a chosen reply, placed over the WHOLE scene with the existing
 *  placers and counted when some can't be found. The controller
 *  (aiSuggestion.svelte.ts) installs the result as one mixed review. */
import type { Node as PMNode } from "@tiptap/pm/model";
import type { FlagNote, LineEdit, LineNote } from "@/lib/aiTypes";
import { placeLineEdits, placeLineNotes, type PlacedEdit, type PlacedNote } from "./lineEdits";

/** What an extraction turn hands the scene's pane. */
export type SceneFlags = { edits: LineEdit[]; notes: FlagNote[] };

export type PlacedSceneFlags = {
  edits: PlacedEdit[];
  notes: PlacedNote[];
  /** Edits and notes whose quote is absent, ambiguous or overlapped. */
  dropped: number;
  /** How many flags the reply held. */
  total: number;
};

/** A note with no entry carries "" (ADR-0100 §7). */
const asLineNote = (n: FlagNote): LineNote => ({ quote: n.quote, problem: n.problem, entry: n.entry_id ?? "" });

export function placeSceneFlags(doc: PMNode, flags: SceneFlags): PlacedSceneFlags {
  const end = doc.content.size;
  const edits = placeLineEdits(doc, 0, end, flags.edits);
  const notes = placeLineNotes(doc, 0, end, flags.notes.map(asLineNote));
  return {
    edits: edits.placed,
    notes: notes.placed,
    dropped: edits.dropped + notes.dropped,
    total: flags.edits.length + flags.notes.length,
  };
}

/** The notice for flags that couldn't be placed; null when all were. */
export function flagsNotice(dropped: number, total: number): string | null {
  if (dropped <= 0) return null;
  if (dropped >= total) return `None of the ${total} flags could be found in the scene.`;
  return `${dropped} of ${total} flags couldn't be found in the scene.`;
}

/** Entry id to display name, from the response's notes. */
export function flagEntryNames(flags: SceneFlags): Map<string, string> {
  const names = new Map<string, string>();
  for (const n of flags.notes) if (n.entry_id && n.entry_name) names.set(n.entry_id, n.entry_name);
  return names;
}
