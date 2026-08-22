// Roving-focus for a WAI-ARIA `role="menu"` container (#838). Attach to the menu
// element; it moves focus between the enabled `role="menuitem"` children on
// ArrowDown/ArrowUp (wrapping), Home, and End — the roving model those menus
// advertise but only partly honoured (Tab-only before this). A no-op unless the
// node is actually `role="menu"`, so it is safe to attach to every Popover panel
// (the modal `role="dialog"` variant keeps its own focus trap, untouched).
//
// Focus ENTRY stays Tab-driven: these menus are deliberately non-modal and do not
// steal focus on open (see Popover), so arrows act once focus is already inside.
// Component-specific keys (PromptMenu's ArrowLeft/ArrowRight/Escape descend/ascend,
// Enter to activate) are handled by the items themselves and bubble past this.
export function rovingMenu(node: HTMLElement) {
  function items(): HTMLElement[] {
    return Array.from(node.querySelectorAll<HTMLElement>('[role="menuitem"]')).filter(
      (el) =>
        !el.hasAttribute("disabled") &&
        el.getAttribute("aria-disabled") !== "true" &&
        !el.hasAttribute("hidden"),
    );
  }
  function onKeydown(event: KeyboardEvent) {
    if (node.getAttribute("role") !== "menu") return;
    const keys = ["ArrowDown", "ArrowUp", "Home", "End"];
    if (!keys.includes(event.key)) return;
    const list = items();
    if (list.length === 0) return;
    const active = document.activeElement as HTMLElement | null;
    const current = active ? list.indexOf(active) : -1;
    let next: number;
    if (event.key === "Home") next = 0;
    else if (event.key === "End") next = list.length - 1;
    else if (event.key === "ArrowDown") next = current < 0 ? 0 : (current + 1) % list.length;
    else next = current < 0 ? list.length - 1 : (current - 1 + list.length) % list.length;
    event.preventDefault();
    list[next]?.focus();
  }
  node.addEventListener("keydown", onKeydown);
  return {
    destroy() {
      node.removeEventListener("keydown", onKeydown);
    },
  };
}
