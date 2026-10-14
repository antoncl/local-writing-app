/** The decision card for the CURRENT line edit (#2460): its reason, Accept /
 *  Reject and prev / next, next to the edit being judged. Built as plain DOM for
 *  the plugin's widget decoration; the plugin passes the actions in (this module
 *  never imports it). Placement is CSS: `wide` puts the card in the margin right
 *  of the prose column at the edit's line, otherwise it is a block under the
 *  paragraph. mousedown preventDefault on the card keeps the editor focused. */

export const LINE_EDIT_CARD_CLASS = "line-edit-card";
export const LINE_EDIT_CARD_WIDE_CLASS = "line-edit-card-wide";

export type LineEditCardActions = {
  prev: () => void;
  next: () => void;
  accept: () => void;
  reject: () => void;
};

export function button(
  testid: string,
  className: string,
  label: string,
  title: string,
  text: string,
  run: () => void,
): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.className = `lec-btn ${className}`;
  b.dataset.testid = testid;
  b.title = title;
  b.setAttribute("aria-label", label);
  b.textContent = text;
  b.addEventListener("click", run);
  return b;
}

export function buildLineEditCard(reason: string, wide: boolean, actions: LineEditCardActions): HTMLElement {
  const card = document.createElement("div");
  card.className = wide ? `${LINE_EDIT_CARD_CLASS} ${LINE_EDIT_CARD_WIDE_CLASS}` : LINE_EDIT_CARD_CLASS;
  card.contentEditable = "false";
  card.dataset.testid = "line-edit-card";
  card.setAttribute("role", "group");
  card.setAttribute("aria-label", "Current line edit");
  card.addEventListener("mousedown", (e) => e.preventDefault());

  const text = document.createElement("div");
  text.className = "lec-reason";
  text.dataset.testid = "line-edit-card-reason";
  text.textContent = reason;

  const row = document.createElement("div");
  row.className = "lec-actions";
  row.append(
    button("line-edit-card-accept", "lec-accept", "Accept this edit", "Accept this edit (Alt+Enter)", "Accept", actions.accept),
    button("line-edit-card-reject", "lec-reject", "Reject this edit", "Reject this edit (Alt+Backspace)", "Reject", actions.reject),
    button("line-edit-card-prev", "lec-step", "Previous edit", "Previous edit (Alt+Up)", "‹", actions.prev),
    button("line-edit-card-next", "lec-step", "Next edit", "Next edit (Alt+Down)", "›", actions.next),
  );
  card.append(text, row);
  return card;
}
