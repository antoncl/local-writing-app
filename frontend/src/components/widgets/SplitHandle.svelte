<script lang="ts">
  // The shared pane-divider gesture (ADR-0091 §7): lifted out of
  // `EditorRail.svelte`'s inline `startResize`/`onResizeMove`/`endResize`, the
  // rail's first consumer, the Propagate pane's diff-column divider its
  // second. Owns the gesture itself — `preventDefault` on mousedown,
  // global mousemove/mouseup added on drag start and removed on end
  // (AGENTS.md: a pane drag uses global handlers + direct DOM updates, never
  // pointer-capture/state-only, which didn't move panes reliably) — and the
  // accent stripe + `separator` role/orientation. Each host keeps its OWN
  // clamp and persistence in the callbacks; this widget carries no size or
  // project state of its own.
  //
  // Destructured as `axis` — TypeScript's DOM lib declares an ambient global
  // `orientation` (the deprecated window.orientation), which a same-named
  // top-level `let` in this script collides with under svelte-check.
  //
  // NOTE: no backtick (code-span) markup in a comment BETWEEN the properties
  // of the `$props()` type literal below — svelte-check's own tokenizer
  // mis-scans it as an unterminated template literal and reports the whole
  // <script> as never closed. Backticks are fine everywhere else in this file
  // (this comment block included); only inside that one type literal.
  let {
    orientation: axis,
    label,
    onDragStart,
    onDrag,
    onDragEnd,
    class: className = "",
  }: {
    orientation: "vertical" | "horizontal";
    // Accessible name — the host says what it resizes ("Resize details
    // rail", "Resize the candidate list").
    label: string;
    onDragStart: (event: MouseEvent) => void;
    onDrag: (event: MouseEvent) => void;
    onDragEnd: () => void;
    // Passthrough for a host's own positioning rule (e.g. the rail's inset
    // -3px handle) — a class a host defines in ITS OWN style block as a
    // :global(...) rule, since a class passed from outside never matches a
    // child component's own scoped selector.
    class?: string;
  } = $props();

  let dragging = $state(false);

  function onMouseDown(event: MouseEvent) {
    event.preventDefault();
    dragging = true;
    onDragStart(event);
    // `window`, not `document` — the same target `EditorRail`'s own
    // `<svelte:window>` listened on before this widget lifted the gesture out
    // of it; a real drag's mousemove reaches both, but keeping the widget on
    // the rail's original target is what let its characterisation test
    // (EditorRail.resize.test.ts) stay unchanged across the extraction.
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  }
  function onMouseMove(event: MouseEvent) {
    onDrag(event);
  }
  function onMouseUp() {
    dragging = false;
    window.removeEventListener("mousemove", onMouseMove);
    window.removeEventListener("mouseup", onMouseUp);
    onDragEnd();
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
  class={`split-handle ${axis} ${className}`}
  class:dragging
  role="separator"
  aria-orientation={axis}
  aria-label={label}
  onmousedown={onMouseDown}
></div>

<style>
  .split-handle {
    background: transparent;
    transition: background var(--t-fast);
  }

  .split-handle.vertical {
    cursor: col-resize;
  }

  .split-handle.horizontal {
    cursor: row-resize;
  }

  .split-handle.vertical:hover,
  .split-handle.vertical.dragging {
    background: linear-gradient(to right, transparent 0 2px, var(--accent) 2px 4px, transparent 4px);
  }

  .split-handle.horizontal:hover,
  .split-handle.horizontal.dragging {
    background: linear-gradient(to bottom, transparent 0 2px, var(--accent) 2px 4px, transparent 4px);
  }
</style>
