<script context="module" lang="ts">
  // The shared chrome controller — the five pane-layout handlers, all owned by
  // App (document-level drag/resize + the floating-pane layout state). They're
  // identical for every pane, so App builds this once and passes the same
  // object to each <Pane>; Pane calls them with its own id.
  export type PaneChrome = {
    focus: (id: string) => void;
    headerKeydown: (event: KeyboardEvent, id: string) => void;
    headerDrag: (event: MouseEvent, id: string) => void;
    resizeKeydown: (event: KeyboardEvent, id: string) => void;
    resizeDrag: (event: MouseEvent, id: string) => void;
  };
</script>

<script lang="ts">
  import type { Snippet } from "svelte";

  // A floating pane's chrome: the draggable header, the resize handle, and the
  // section wrapper that App's drag/resize code finds by `data-pane-id`. The
  // body is the caller's — most panes wrap it in `<div class="pane-content">`,
  // but the schema panes drop their editor straight in, so Pane stays agnostic.
  export let id: string;
  // Drives the <h2> and every aria label ("{title} pane", "Move/Resize …").
  export let title: string;
  // The pane-specific section class, e.g. "lore-pane".
  export let paneClass: string;
  export let hidden = false;
  // Initial position/size from App's paneStyle(id). Drag/resize mutate the DOM
  // directly afterwards (by data-pane-id), so this need not stay reactive.
  export let style = "";
  export let chrome: PaneChrome;
  // Optional header buttons (rendered in `.pane-header-actions`) and the body.
  export let actions: Snippet | undefined = undefined;
  export let children: Snippet | undefined = undefined;
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<section
  class:hidden-pane={hidden}
  class="pane {paneClass}"
  data-pane-id={id}
  {style}
  aria-label="{title} pane"
  on:mousedown={() => chrome.focus(id)}
>
  <header
    class="pane-header"
    role="button"
    tabindex="0"
    aria-label="Move {title} pane"
    on:keydown={(event) => chrome.headerKeydown(event, id)}
    on:mousedown={(event) => chrome.headerDrag(event, id)}
  >
    <h2>{title}</h2>
    {#if actions}
      <div class="pane-header-actions">
        {@render actions()}
      </div>
    {/if}
  </header>
  {@render children?.()}
  <button
    class="pane-resize"
    type="button"
    aria-label="Resize {title} pane"
    on:keydown={(event) => chrome.resizeKeydown(event, id)}
    on:mousedown={(event) => chrome.resizeDrag(event, id)}
  ></button>
</section>
