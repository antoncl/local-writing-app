<!--
  ProseTableToolbar — floating toolbar shown when the caret is inside a table in
  ProseBodyView (column/row insert+delete, cell alignment, header toggles,
  delete table).

  The host owns when/where it shows (tableMenu state) and the alignment logic
  (column-wide vs single cell, via onAlign -> setCellAlign). The plain table
  commands are TipTap chain calls, so they live here next to the buttons that
  fire them — this is inherently a table-command surface. onmousedown handlers
  preventDefault so a click never blurs the editor.
-->
<script lang="ts">
  import type { Editor } from "@tiptap/core";

  interface Props {
    menu: { visible: boolean; x: number; y: number };
    editor: Editor | null;
    onAlign: (align: "left" | "center" | "right") => void;
  }

  let { menu, editor, onAlign }: Props = $props();
</script>

{#if menu.visible}
  <div class="table-toolbar" style={`left: ${menu.x}px; top: ${menu.y}px;`}>
    <button type="button" title="Insert column before" onmousedown={(e) => { e.preventDefault(); editor?.chain().focus().addColumnBefore().run(); }}>+ col ←</button>
    <button type="button" title="Insert column after" onmousedown={(e) => { e.preventDefault(); editor?.chain().focus().addColumnAfter().run(); }}>+ col →</button>
    <button type="button" title="Delete column" onmousedown={(e) => { e.preventDefault(); editor?.chain().focus().deleteColumn().run(); }}>− col</button>
    <span class="table-toolbar-sep" aria-hidden="true"></span>
    <button type="button" title="Insert row above" onmousedown={(e) => { e.preventDefault(); editor?.chain().focus().addRowBefore().run(); }}>+ row ↑</button>
    <button type="button" title="Insert row below" onmousedown={(e) => { e.preventDefault(); editor?.chain().focus().addRowAfter().run(); }}>+ row ↓</button>
    <button type="button" title="Delete row" onmousedown={(e) => { e.preventDefault(); editor?.chain().focus().deleteRow().run(); }}>− row</button>
    <span class="table-toolbar-sep" aria-hidden="true"></span>
    <button type="button" title="Align left" onmousedown={(e) => { e.preventDefault(); onAlign("left"); }}>⟵</button>
    <button type="button" title="Align center" onmousedown={(e) => { e.preventDefault(); onAlign("center"); }}>↔</button>
    <button type="button" title="Align right" onmousedown={(e) => { e.preventDefault(); onAlign("right"); }}>⟶</button>
    <span class="table-toolbar-sep" aria-hidden="true"></span>
    <button type="button" title="Toggle header row" onmousedown={(e) => { e.preventDefault(); editor?.chain().focus().toggleHeaderRow().run(); }}>Hdr row</button>
    <button type="button" title="Toggle header column" onmousedown={(e) => { e.preventDefault(); editor?.chain().focus().toggleHeaderColumn().run(); }}>Hdr col</button>
    <span class="table-toolbar-sep" aria-hidden="true"></span>
    <button type="button" title="Delete table" onmousedown={(e) => { e.preventDefault(); editor?.chain().focus().deleteTable().run(); }}>Delete</button>
  </div>
{/if}

<style>
  .table-toolbar {
    position: absolute;
    z-index: 22;
    display: flex;
    align-items: center;
    overflow: visible;
    border: 1px solid var(--toolbar-border);
    border-radius: 7px;
    background: var(--toolbar-surface);
    box-shadow: var(--elev-2);
    white-space: nowrap;
  }

  .table-toolbar button {
    height: 34px;
    min-width: 38px;
    padding: 0 10px;
    border: 0;
    border-right: 1px solid var(--toolbar-divider);
    border-radius: 0;
    background: transparent;
    color: var(--toolbar-text);
    font-size: var(--fs-md);
    font-weight: 700;
    cursor: pointer;
  }

  .table-toolbar button:first-child {
    border-top-left-radius: 6px;
    border-bottom-left-radius: 6px;
  }

  .table-toolbar button:last-child {
    border-right: 0;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
  }

  .table-toolbar button:hover {
    background: var(--toolbar-hover);
  }

  .table-toolbar-sep {
    display: inline-block;
    width: 1px;
    height: 22px;
    background: var(--toolbar-divider);
  }
</style>
