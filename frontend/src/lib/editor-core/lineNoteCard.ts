/** The card for the CURRENT lore-check note (ADR-0098): what is wrong with the
 *  quoted passage and which entry it contradicts, with Open entry / Dismiss and
 *  prev / next. Built like lineEditCard.ts and sharing its geometry classes, so
 *  the margin / block placement is the same CSS; there is no Accept, because a
 *  note never writes to the document. */
import { LINE_EDIT_CARD_CLASS, LINE_EDIT_CARD_WIDE_CLASS, button } from "./lineEditCard";

export const LINE_NOTE_CARD_CLASS = "line-note-card";

export type LineNoteCardActions = {
  prev: () => void;
  next: () => void;
  openEntry: () => void;
  dismiss: () => void;
};

export function buildLineNoteCard(
  problem: string,
  entryName: string,
  wide: boolean,
  actions: LineNoteCardActions,
): HTMLElement {
  const card = document.createElement("div");
  card.className = [LINE_EDIT_CARD_CLASS, LINE_NOTE_CARD_CLASS, ...(wide ? [LINE_EDIT_CARD_WIDE_CLASS] : [])].join(" ");
  card.contentEditable = "false";
  card.dataset.testid = "line-note-card";
  card.setAttribute("role", "group");
  card.setAttribute("aria-label", "Current note");
  card.addEventListener("mousedown", (e) => e.preventDefault());

  const text = document.createElement("div");
  text.className = "lnc-problem";
  text.dataset.testid = "line-note-card-problem";
  text.textContent = problem;

  const entry = document.createElement("div");
  entry.className = "lnc-entry";
  entry.dataset.testid = "line-note-card-entry";
  entry.textContent = entryName;

  const row = document.createElement("div");
  row.className = "lec-actions";
  row.append(
    button("line-note-card-open", "lec-accept", "Open entry", "Open the entry this note is about", "Open entry", actions.openEntry),
    button("line-note-card-dismiss", "lec-step", "Dismiss this note", "Dismiss this note (Alt+Backspace)", "Dismiss", actions.dismiss),
    button("line-note-card-prev", "lec-step", "Previous note", "Previous note (Alt+Up)", "‹", actions.prev),
    button("line-note-card-next", "lec-step", "Next note", "Next note (Alt+Down)", "›", actions.next),
  );
  card.append(text, entry, row);
  return card;
}
