<script lang="ts">
  // NodeEditor's header region (#2029 split): the chat void branch (grid-row
  // placeholder) plus the `.editor-header` section (title row, layer authoring
  // bar, cost hint). Moved verbatim out of NodeEditor — state/persistence for
  // the title input itself stays in NodeEditor (the `chatTitleField` snippet is
  // handed down and rendered here bare inside `.title-label`; ChatBodyView
  // renders the SAME snippet on its own row, ADR-0076 S6).
  //
  // Rendered at NodeEditor's component root (no wrapper element): the void div
  // / `<section>` must land as a direct child of `.editor-panel`'s grid so row 1
  // stays pinned (see the `> :global(*)` rail-column rules in NodeEditor's
  // style block).
  import type { BodyShape, DocumentKind } from "@/lib/types";
  import type { CharacterCostRow, RollupCost } from "@/lib/editor-core/characterCost";
  import LayerAuthoringBar from "@/components/editor/LayerAuthoringBar.svelte";
  import EditorCostHint from "@/components/editor/EditorCostHint.svelte";
  import { INTERIORITY_EYE_SVG } from "@/lib/editor-core/interiorityReveal";

  interface HeaderModel {
    scene: import("@/lib/types").EditableDocument | null;
    documentKind: DocumentKind;
    bodyShape: BodyShape;
    documentNameLabel: string;
    titleMutated: boolean;
    hasInteriorityBeats: boolean;
    interiorityRevealed: boolean;
    liveWordCount: number;
    characterCostRowsView: CharacterCostRow[];
    lastInvocationCostUsd: number | null;
    sceneSessionCostUsd: number;
    rollupCostKind: RollupCost | null;
    todoStatusHint: string;
    authoringLayerId: string | null;
    recentlySaved: boolean;
    // The five title-input variants, defined once in NodeEditor (state and
    // persistence live entirely there — see its own doc comment).
    chatTitleField: import("svelte").Snippet;
  }

  interface HeaderCallbacks {
    toggleInteriority: () => void;
    authoringLayerChange?: ((layerId: string | null) => void) | undefined;
  }

  interface Props {
    model: HeaderModel;
    on: HeaderCallbacks;
  }

  let { model, on }: Props = $props();
</script>

{#if model.scene && model.bodyShape === "chat"}
  <!-- ADR-0076 S6: the chat header (title + setup) is one row inside the body,
       so the shell renders no header content (LayerAuthoringBar no-ops for chat,
       EditorCostHint is empty for a chat node). But an EMPTY header slot must
       still occupy grid row 1 at zero height — without it ChatBodyView
       auto-places into the `auto` row 1 instead of the `1fr` body row, and the
       transcript stops filling the pane (dead space below the composer). -->
  <div class="editor-header-void" aria-hidden="true"></div>
{:else}
  <section class="editor-header">
    {#if model.scene}
      <div class="scene-title-row">
        <label class="title-label">
          {model.documentNameLabel}{#if model.titleMutated}<span class="title-mutated-marker" title="Changed by here">⤳</span>{/if}
          <!-- Same five title-input variants as the chat header, from the one
               `chatTitleField` snippet — here they sit inside the eyebrow
               label; chat renders the snippet bare (ADR-0076 S6). -->
          {@render model.chatTitleField()}
        </label>
        <!-- Interiority reveal (ADR-0070 S2): a shell affordance, present only
             while the scene holds roleplay. Adaptive-stateful — quiet eye when
             idle, gaining the name "Interiority" + a tint while revealing. The
             shortcut lives in the tooltip, never as a compound on the button. -->
        {#if model.hasInteriorityBeats}
          <button
            type="button"
            class="interiority-toggle"
            class:active={model.interiorityRevealed}
            aria-pressed={model.interiorityRevealed}
            aria-label="Interiority — reveal every beat"
            title="Interiority — reveal every beat  (Alt+I)"
            onclick={() => on.toggleInteriority()}
          >
            <span class="tg-glyph" aria-hidden="true">{@html INTERIORITY_EYE_SVG}</span>
            {#if model.interiorityRevealed}<span class="tg-name">Interiority</span>{/if}
          </button>
        {/if}
      </div>
      <!-- Layer override authoring (#314 / ADR-0042): choose which level this
           inherited entry's edits write to. Renders only for an inherited lore
           entry; no-ops otherwise. -->
      <LayerAuthoringBar
        scene={model.scene}
        documentKind={model.documentKind}
        authoringLayerId={model.authoringLayerId}
        recentlySaved={model.recentlySaved}
        onAuthoringLayerChange={on.authoringLayerChange}
      />
      <EditorCostHint
        todoStatusHint={model.todoStatusHint}
        documentKind={model.documentKind}
        liveWordCount={model.liveWordCount}
        characterCosts={model.characterCostRowsView}
        lastInvocationCostUsd={model.lastInvocationCostUsd}
        sceneSessionCostUsd={model.sceneSessionCostUsd}
        rollupCost={model.rollupCostKind}
      />
    {:else}
      <h2>Select a scene</h2>
    {/if}
  </section>
{/if}

<style>
  /* Header-only chrome, moved verbatim from NodeEditor (#2029). */
  .editor-header {
    display: grid;
    gap: 6px;
    padding: 12px 22px 6px;
    border-bottom: 1px solid var(--divider);
    background: var(--surface);
  }
  /* ADR-0076 S6: empty stand-in that holds the header's grid row for chat (which
     renders its header inside the body), so ChatBodyView stays in the `.editor-panel`
     1fr row and the transcript fills the pane. Zero height, no chrome. */
  .editor-header-void {
    min-height: 0;
    padding: 0;
    border: 0;
  }

  .scene-title-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 4px 8px;
    align-items: center;
  }

  /* Interiority reveal toggle (ADR-0070 S2) — a shell affordance in the title
     row's right column. Adaptive-stateful: quiet eye when idle; gains the name
     "Interiority" + an accent tint while revealing (mirrors the ⤢/theme
     shell-affordance pattern in design-language.md §5). */
  .interiority-toggle {
    justify-self: end;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 6px;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    font-size: var(--fs-sm);
  }
  .interiority-toggle .tg-glyph {
    display: inline-flex;
    width: 16px;
    height: 16px;
  }
  .interiority-toggle .tg-glyph :global(svg) {
    width: 16px;
    height: 16px;
  }
  .interiority-toggle:hover {
    color: var(--text-2);
    background: var(--inset);
  }
  .interiority-toggle.active {
    color: var(--accent);
    background: var(--accent-soft);
  }
  .interiority-toggle .tg-name {
    font-weight: 600;
  }

  .title-mutated-marker {
    margin-left: 4px;
    color: var(--mutation-color);
    font-weight: 700;
  }

  .title-label {
    display: grid;
    gap: 3px;
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 700;
    text-transform: uppercase;
  }
</style>
