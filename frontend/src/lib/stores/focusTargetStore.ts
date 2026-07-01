// Cross-cutting "find target" resolver. Tracks every visible
// find-style input (SearchInput, NodeEditor's find-in-document) and
// publishes which one Ctrl/Cmd+F would activate based on the current
// focus.
//
// Resolution (in priority order, recomputed on focusin / register /
// unregister):
//   1. Walk up from document.activeElement — first registered target
//      ancestor wins. The "I'm typing inside an expanded NodeRow with
//      its own inner search" case.
//   2. Outermost target inside the currently focused pane (closest
//      ancestor [data-pane-id] to activeElement). The "I clicked into
//      the lore pane but haven't focused its search yet" case.
//   3. No target — Ctrl+F falls through to the browser default.
//
// SearchInput / find inputs register themselves on mount and pass an
// `element` reference. They subscribe to `currentTargetId` to know
// whether to render their hint badge in the active state.

import { writable, get, derived, type Readable } from "svelte/store";

let nextId = 1;

type FindKind = "search" | "find";

type Registration = {
  id: number;
  element: HTMLElement;
  kind: FindKind;
};

const registrations = writable<Registration[]>([]);

// Tracks the id of the find-input that Ctrl+F would activate right now,
// or null if no target resolves. Recomputed when registrations change
// or when DOM focus moves.
export const currentTargetId = writable<number | null>(null);

export function registerFindTarget(
  element: HTMLElement,
  kind: FindKind = "search",
): { id: number; unregister: () => void } {
  const id = nextId++;
  registrations.update((list) => [...list, { id, element, kind }]);
  recomputeTarget();
  return {
    id,
    unregister: () => {
      registrations.update((list) => list.filter((r) => r.id !== id));
      recomputeTarget();
    },
  };
}

function recomputeTarget() {
  const list = get(registrations);
  if (list.length === 0) {
    currentTargetId.set(null);
    return;
  }
  const active = document.activeElement as HTMLElement | null;

  // 1. Walk up from active element looking for a registered target.
  if (active) {
    let cursor: HTMLElement | null = active;
    while (cursor) {
      const match = list.find((r) => r.element === cursor);
      if (match) {
        currentTargetId.set(match.id);
        return;
      }
      cursor = cursor.parentElement;
    }
  }

  // 2. Outermost target in the focused pane.
  const pane = active?.closest("[data-pane-id]") as HTMLElement | null;
  if (pane) {
    // Among registrations inside this pane, the outermost in DOM order
    // is the one with the fewest ancestors. Equivalently: the first one
    // we hit when descending.
    const inside = list.filter((r) => pane.contains(r.element));
    if (inside.length > 0) {
      // Choose the one whose element is *not* a descendant of any other
      // registered element. Outermost.
      const outermost = inside.find(
        (r) => !inside.some((other) => other.id !== r.id && other.element.contains(r.element)),
      );
      if (outermost) {
        currentTargetId.set(outermost.id);
        return;
      }
    }
  }

  // 3. No target.
  currentTargetId.set(null);
}

// Whether a given registered target is the current Ctrl+F target.
// SearchInputs use this to decide whether to render the active badge.
export function isCurrentTarget(id: number | null): Readable<boolean> {
  return derived(currentTargetId, ($id) => id !== null && id === $id);
}

// Module-level listeners: track focus changes globally so the resolver
// stays current without each consumer wiring its own listener.
if (typeof window !== "undefined") {
  // `focusin` bubbles (unlike `focus`); fires when any element gains
  // focus anywhere in the document.
  window.addEventListener("focusin", () => recomputeTarget());
  // `focusout` fires when focus leaves — but `activeElement` updates
  // synchronously so the next `focusin` is what actually matters.
  // We still recompute on blur-to-body cases.
  window.addEventListener("focusout", () => {
    // Defer so document.activeElement reflects the new focus.
    queueMicrotask(() => recomputeTarget());
  });

  // Cmd/Ctrl+F intercept: if a target resolves, focus it; otherwise
  // fall through to the browser's default find.
  window.addEventListener("keydown", (event) => {
    const isFind =
      (event.ctrlKey || event.metaKey) && (event.key === "f" || event.key === "F");
    if (!isFind) return;
    const id = get(currentTargetId);
    if (id == null) return;
    const target = get(registrations).find((r) => r.id === id);
    if (!target) return;
    event.preventDefault();
    target.element.focus();
    if (target.element instanceof HTMLInputElement || target.element instanceof HTMLTextAreaElement) {
      target.element.select();
    }
  });
}
