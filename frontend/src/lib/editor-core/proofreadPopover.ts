// Proofreading (ADR-0102 §3–§4): the one popover a finding opens — its message,
// then sections of choices: the fixes, and the three permanent ignores. Built by
// hand, like the implicit-context card, because it lives in a ProseMirror
// plugin; placement is `anchoredPopover`'s.
//
// A choice may be async (a write through the backend). While it runs the
// choices are disabled; when it fails the popover stays open and says so, at
// the item, instead of a toast elsewhere.
import { anchoredPopover } from "@/lib/actions/anchoredPopover";

export const POPOVER_CLASS = "proofread-popover";

export type PopoverChoice = { label: string; run: () => void | Promise<void> };
/** A heading (empty for the fixes, which need none) and its choices. */
export type PopoverSection = { heading: string; choices: PopoverChoice[] };

export type FindingPopover = {
  readonly target: HTMLElement | null;
  show(target: HTMLElement, message: string, sections: PopoverSection[]): void;
  hide(): void;
};

export function createFindingPopover(): FindingPopover {
  const el = document.createElement("div");
  el.className = POPOVER_CLASS;
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-label", "Proofreading");
  let target: HTMLElement | null = null;
  let placement: ReturnType<typeof anchoredPopover> | null = null;

  function hide() {
    if (!target) return;
    target = null;
    placement?.destroy();
    placement = null;
    document.removeEventListener("keydown", onKeydown, true);
    document.removeEventListener("pointerdown", onPointerDown, true);
  }
  // Escape is consumed: the keypress that closes the popover must not also
  // close the dialog or menu the editor sits in.
  function onKeydown(event: KeyboardEvent) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    hide();
  }
  function onPointerDown(event: Event) {
    const node = event.target;
    if (!(node instanceof Node) || (!el.contains(node) && !target?.contains(node))) hide();
  }

  async function choose(choice: PopoverChoice) {
    const buttons = Array.from(el.querySelectorAll("button"));
    buttons.forEach((b) => (b.disabled = true));
    el.querySelector(`.${POPOVER_CLASS}-error`)?.remove();
    try {
      await choice.run();
      hide();
    } catch (err) {
      buttons.forEach((b) => (b.disabled = false));
      const error = document.createElement("p");
      error.className = `${POPOVER_CLASS}-error`;
      error.setAttribute("role", "alert");
      error.textContent = `Couldn't do that: ${err instanceof Error ? err.message : String(err)}`;
      el.appendChild(error);
    }
  }

  function render(message: string, sections: PopoverSection[]) {
    el.replaceChildren();
    const text = document.createElement("p");
    text.className = `${POPOVER_CLASS}-message`;
    text.textContent = message;
    el.appendChild(text);
    for (const section of sections) {
      if (section.choices.length === 0) continue;
      const box = document.createElement("div");
      box.className = `${POPOVER_CLASS}-section`;
      if (section.heading) {
        const heading = document.createElement("p");
        heading.className = `${POPOVER_CLASS}-heading`;
        heading.textContent = section.heading;
        box.appendChild(heading);
      }
      const row = document.createElement("div");
      row.className = `${POPOVER_CLASS}-choices`;
      for (const choice of section.choices) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `${POPOVER_CLASS}-choice`;
        button.textContent = choice.label;
        // Keep the editor's focus and selection: a fix is an edit in it.
        button.addEventListener("mousedown", (event) => event.preventDefault());
        button.addEventListener("click", () => void choose(choice));
        row.appendChild(button);
      }
      box.appendChild(row);
      el.appendChild(box);
    }
  }

  return {
    get target() {
      return target;
    },
    show(next, message, sections) {
      target = next;
      render(message, sections);
      if (placement) {
        placement.update({ anchor: next });
        return;
      }
      placement = anchoredPopover(el, { anchor: next });
      document.addEventListener("keydown", onKeydown, true);
      document.addEventListener("pointerdown", onPointerDown, true);
    },
    hide,
  };
}
