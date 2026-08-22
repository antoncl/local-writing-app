<script lang="ts">
  // The chrome dropdown/popover primitive (#766.1). The top bar and the
  // breadcrumb hand-rolled this same shell four times — the project switcher and
  // the ≡ app menu (TopBar), the inheritance editor and the "Contains" descent
  // menu (ProjectBreadcrumb). Each one is a full-viewport overlay for the
  // click-outside dismiss + an absolutely-positioned panel anchored under its
  // trigger + Escape-to-refocus, and the modal one adds focus-into-on-open and a
  // Tab-trap. Kept in sync by hand, a fix to one (the Escape refocus rule, the
  // click-outside handling) never propagated to the others. This collapses them.
  //
  // Like Modal.svelte, this owns only the SHELL — the overlay, the positioned
  // panel box, and the focus/dismiss behaviour. The panel's CONTENTS come in as
  // the default snippet, so they carry the CONSUMER's style scope (see Modal's
  // note on slotted content): each caller keeps styling its own rows/items. The
  // size/shape that varies per caller (widths, padding, gap, vertical offset,
  // left-vs-right anchor) is passed as props → `--pop-*` custom properties, the
  // same override seam Modal uses for `--modal-*`.
  //
  // NOT the TagPicker/SwatchPicker portal pattern: those reparent to <body> and
  // track the trigger with getBoundingClientRect under workspace zoom (#245).
  // This one anchors in-flow against a `position: relative` wrapper the caller
  // provides, which is all the chrome dropdowns need.
  import type { Snippet } from "svelte";
  import { rovingMenu } from "@/lib/utils/rovingMenu";

  let {
    // Two-way: overlay-click and Escape flip this back to false in the caller.
    open = $bindable(false),
    // The control that opened the popover. Escape returns focus here (the panel
    // unmounts on close, so without this focus falls to <body> and the next Tab
    // restarts from the top of the document). A click on the overlay does NOT
    // refocus — a mouse user dismissing shouldn't have focus yanked onto the
    // button. Post-action focus (a menu item that navigates elsewhere) stays the
    // caller's business.
    triggerEl = null,
    // `menu` (non-modal, like the switcher/app-menu/contains) vs `dialog` (modal:
    // owns focus while open — focus-into on mount, Tab trapped, aria-modal). The
    // inheritance editor is the only modal one.
    role = "menu",
    // Accessible name: `label` → aria-label, or `labelledby` → aria-labelledby
    // when the panel carries its own visible heading (the inherit editor does).
    label = undefined,
    labelledby = undefined,
    // Panel id, so the caller's trigger can point aria-controls at it while open.
    id = undefined,
    // Horizontal anchor against the positioned wrapper: `left` drops the panel from
    // the wrapper's left edge, `right` from its right edge (#766.3 — a trigger on
    // the right side of the bar wants its panel right-aligned so a wide panel grows
    // leftward into the bar rather than off the viewport's right edge).
    anchor = "left",
    // Vertical gap between the trigger and the panel.
    offset = 4,
    // Per-caller box shape (see the class comments on each dropdown for why the
    // numbers differ). `overflow-y` is derived: a capped panel (maxHeight set)
    // scrolls, an uncapped one (the small inherit editor) stays `visible` so it is
    // byte-identical to the pre-primitive markup.
    minWidth = "auto",
    maxWidth = "none",
    maxHeight = "none",
    padding = "6px",
    gap = "1px",
    // Exposes the panel element to the caller (the switcher juggles focus among its
    // remove-buttons after a row unmounts, #423). Bindable; unused by most callers.
    panel = $bindable(null),
    // Extra side effect to run whenever the popover dismisses itself (overlay click
    // or Escape) — the app menu resets its inline "save preset" field here.
    onClose = undefined,
    children,
  }: {
    open?: boolean;
    triggerEl?: HTMLElement | null;
    role?: "menu" | "dialog";
    label?: string | undefined;
    labelledby?: string | undefined;
    id?: string | undefined;
    anchor?: "left" | "right";
    offset?: number;
    minWidth?: string;
    maxWidth?: string;
    maxHeight?: string;
    padding?: string;
    gap?: string;
    panel?: HTMLElement | null;
    onClose?: (() => void) | undefined;
    children: Snippet;
  } = $props();

  const modal = $derived(role === "dialog");
  const overflowY = $derived(maxHeight === "none" ? "visible" : "auto");
  const panelStyle = $derived(
    `--pop-offset:${offset}px;` +
      `--pop-min-w:${minWidth};` +
      `--pop-max-w:${maxWidth};` +
      `--pop-max-h:${maxHeight};` +
      `--pop-pad:${padding};` +
      `--pop-gap:${gap};` +
      `--pop-overflow-y:${overflowY};`,
  );

  // Everything tabbable inside the panel — for the initial focus and the trap.
  const FOCUSABLE =
    'input:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function close(refocus: boolean): void {
    open = false;
    onClose?.();
    if (refocus) triggerEl?.focus();
  }

  function onOverlayClick(): void {
    close(false);
  }

  // All keyboard handling rides one window listener (no handler on the panel div,
  // which would trip the a11y linter): Escape closes + refocuses; Tab is trapped
  // for the modal dialog so focus cannot walk out to the controls behind the
  // overlay. A non-modal menu leaves Tab alone — focus never entered it.
  function handleKeydown(event: KeyboardEvent): void {
    if (!open) return;
    if (event.key === "Escape") close(true);
    else if (modal && event.key === "Tab") trapTab(event);
  }

  function trapTab(event: KeyboardEvent): void {
    if (!panel) return;
    const focusable = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  // Move focus into the panel the moment a modal popover mounts (i.e. on open),
  // so a keyboard/SR user lands INSIDE the dialog rather than on the trigger now
  // behind the overlay. Falls back to the panel itself when every control is
  // disabled (mid-save), so the dialog is still announced — `tabindex = -1` is
  // set here rather than as a static attribute so it lands only on the modal
  // dialog, not the non-modal menus (and so the linter needn't reason about a
  // dynamic `tabindex`/`role` pair). A no-op for menus, which do not steal focus.
  function focusInto(node: HTMLElement, enabled: boolean): void {
    if (!enabled) return;
    node.tabIndex = -1;
    (node.querySelector<HTMLElement>(FOCUSABLE) ?? node).focus();
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
  <!-- Click-outside dismiss (does not refocus; see close()). -->
  <div class="popover-overlay" role="presentation" onclick={onOverlayClick}></div>
  <div
    bind:this={panel}
    class="popover-panel"
    class:anchor-right={anchor === "right"}
    {role}
    {id}
    aria-modal={modal ? "true" : undefined}
    aria-label={labelledby ? undefined : label}
    aria-labelledby={labelledby}
    style={panelStyle}
    use:focusInto={modal}
    use:rovingMenu
  >
    {@render children()}
  </div>
{/if}

<style>
  /* Overlay + panel z-indexes match the pre-primitive markup: the overlay sits
     below the panel, both inside the top bar's stacking context. */
  .popover-overlay {
    position: fixed;
    inset: 0;
    z-index: 99;
  }

  .popover-panel {
    position: absolute;
    top: calc(100% + var(--pop-offset));
    left: 0;
    z-index: 101;
    min-width: var(--pop-min-w);
    max-width: var(--pop-max-w);
    max-height: var(--pop-max-h);
    overflow-y: var(--pop-overflow-y);
    display: grid;
    gap: var(--pop-gap);
    padding: var(--pop-pad);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: var(--elev-2);
  }

  .popover-panel.anchor-right {
    left: auto;
    right: 0;
  }
</style>
