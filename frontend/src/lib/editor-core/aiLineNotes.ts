// The lore check's run (ADR-0098): one streaming call that answers with notes,
// then each note's quote located in the checked selection. Split out of
// AiSuggestionController, which keeps the reactive state and the wiring; this
// module is the network + placement half, returning an outcome the controller
// applies. Nothing here touches the document.

import type { Editor } from "@tiptap/core";
import { api } from "@/lib/api";
import type { AIStreamEvent } from "@/lib/api/core";
import { resolutionSceneIdFromInputs } from "@/lib/editor-core/promptResolution";
import { gatheredRequestFields, type InlineGathered, type OutputRun } from "@/lib/editor-core/outputHandlers";
import { placeLineNotes, type PlacedNote } from "@/lib/editor-core/lineEdits";
import type { CheckedEntry } from "@/lib/types";

export type NotesDone = Extract<AIStreamEvent, { type: "done" }>;

export type NotesOutcome =
  | { kind: "cancelled" }
  // The writer left the document (or switched scenes) mid-call: not theirs to see.
  | { kind: "stale" }
  // `res`: the finished reply when there was one - paid for even when unusable.
  | { kind: "error"; message: string; res?: NotesDone }
  | {
      kind: "ready";
      res: NotesDone;
      placed: PlacedNote[];
      /** Notes the backend dropped plus those whose quote could not be placed. */
      dropped: number;
      checkedAgainst: CheckedEntry[];
    };

export interface NotesRunArgs {
  editor: Editor;
  gathered: InlineGathered;
  run: OutputRun;
  /** The wire id of the open document (the scene id, or "" for other prose). */
  sceneIdForWire: string;
  signal: AbortSignal;
  isStale: () => boolean;
}

// The one notice a finished run owes the writer, or null when the notes speak for
// themselves: an empty reply, nothing placeable, or some notes skipped.
export function noteNotice(placedCount: number, dropped: number): string | null {
  if (placedCount === 0) {
    if (dropped === 1) return "The note couldn't be placed.";
    return dropped > 0 ? `None of the ${dropped} notes could be placed.` : "No contradictions found.";
  }
  if (dropped > 0) {
    return `${dropped} note${dropped === 1 ? "" : "s"} couldn't be matched and ${dropped === 1 ? "was" : "were"} skipped.`;
  }
  return null;
}

export async function fetchLineNotes(args: NotesRunArgs): Promise<NotesOutcome> {
  const { editor, gathered, run, sceneIdForWire, signal, isStale } = args;
  const { from, to, selectionText } = gathered;
  const { entry, inputs, assistantId, scene } = run;
  try {
    // The notes are read whole, so the deltas are ignored - the call rides the
    // streaming route because only a stream's disconnect stops the provider (#2464).
    let res: NotesDone | null = null;
    let streamError: string | null = null;
    for await (const ev of api.aiGenerateStream({
      template_source: entry.body,
      target_scene_id: sceneIdForWire,
      session_id: scene.id,
      inputs,
      resolution_scene_id: resolutionSceneIdFromInputs(entry, inputs),
      ...gatheredRequestFields(gathered),
      ...(assistantId ? { assistant_id: assistantId } : {}),
      commit: false,
      response_format: "notes",
    }, signal)) {
      if (signal.aborted) break;
      if (ev.type === "done") res = ev;
      else if (ev.type === "error") streamError = ev.error || "Unknown error";
    }
    // Cancelled: drop the reply, even one that raced the abort.
    if (signal.aborted) return { kind: "cancelled" };
    if (isStale()) return { kind: "stale" };
    if (streamError !== null || !res) {
      return { kind: "error", message: streamError ?? "The model's reply ended before it finished." };
    }
    if (res.ok === false) return { kind: "error", message: res.error || "Unknown error", res };
    if (editor.state.doc.textBetween(from, to, "\n\n", " ") !== selectionText) {
      return { kind: "error", message: "Document changed during the AI call. Re-select the text and retry.", res };
    }
    const { placed, dropped } = placeLineNotes(editor.state.doc, from, to, res.notes ?? []);
    return {
      kind: "ready",
      res,
      placed,
      dropped: (res.notes_dropped ?? 0) + dropped,
      checkedAgainst: res.checked_against ?? [],
    };
  } catch (e) {
    return signal.aborted ? { kind: "cancelled" } : { kind: "error", message: (e as Error).message };
  }
}
