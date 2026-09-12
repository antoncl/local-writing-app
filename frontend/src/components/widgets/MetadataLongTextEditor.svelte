<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { Editor } from "@tiptap/core";
  import StarterKit from "@tiptap/starter-kit";
  import Table from "@tiptap/extension-table";
  import TableRow from "@tiptap/extension-table-row";
  import { editorHtmlToSceneMarkdown, sceneMarkdownToHtml } from "@/lib/utils/markdown";
  import { stateAtDocumentBoundary } from "@/lib/editor-core/documentBoundary";
  import { ImplicitContextHighlight, REBUILD_META } from "@/lib/editor-core/implicitContextHighlight";
  import type { CompiledMatcher } from "@/lib/editor-core/implicitContextMatcher";
  import { sanitizePastedHtml } from "@/lib/utils/sanitizePastedHtml";
  import { AlignedTableCell, AlignedTableHeader } from "@/lib/editor-core/alignedTable";
  import { placeSelectionToolbar, type FloatingMenuState, type ToolbarAction } from "@/lib/editor-core/selectionToolbar";
  import { visibleSelectionRect, selectionEndpointRect } from "@/lib/editor-core/selectionRects";
  import { formattingToolbarActions } from "@/lib/editor-core/formattingToolbarActions";
  import { countWords } from "@/lib/utils/wordCount";
  import ProseSelectionToolbar from "@/components/editor/body/ProseSelectionToolbar.svelte";

  let {
    value = "",
    ariaLabel = "Long text metadata",
    // Optional implicit-context matcher — when provided, lore-name matches
    // get inline highlighting + hover preview. Null disables.
    matcher = null,
    // Emitted with the new markdown value (was a `change` CustomEvent before the
    // runes pass); the parent persists it.
    onChange = () => {},
  }: {
    value?: string;
    ariaLabel?: string;
    matcher?: CompiledMatcher | null;
    onChange?: (value: string) => void;
  } = $props();

  let root = $state<HTMLDivElement | null>(null);
  let editorElement: HTMLDivElement;
  let editor = $state<Editor | null>(null);
  // Bookkeeping for the external/local value guard — mutated across the TipTap
  // onUpdate callback and loadValue, never rendered. `$state` so the value-sync
  // effect reads current values; it reads them inside untrack() so only `value`
  // (and `editor` becoming ready) drive it.
  let loadedValue = $state("");
  let lastExternalValue = $state("");
  let pendingLocalValue = $state<string | null>(null);
  let applyingExternalValue = $state(false);

  // Floating selection toolbar (#1884 slice 1): the field reads as prose at
  // rest — formatting lives in the same toolbar the prose body uses, shown on
  // a text selection or with the caret in a table.
  let menu = $state<FloatingMenuState>({ visible: false, x: 0, y: 0, wordCount: 0, placement: "above" });
  let actions = $state<ToolbarAction[]>([]);
  let openMenuId = $state<string | null>(null);
  let isEmpty = $state(true);

  // External value changes — sync into the editor without re-emitting change.
  // Only `value` (and `editor`) drive this; the bookkeeping reads/writes are
  // untracked so a loadValue() write can't re-trigger the effect.
  $effect(() => {
    const next = value;
    if (!editor) return;
    untrack(() => {
      if (next === lastExternalValue || applyingExternalValue) return;
      if (pendingLocalValue !== null && next === pendingLocalValue) {
        lastExternalValue = next;
        pendingLocalValue = null;
      } else {
        void loadValue(next);
      }
    });
  });

  // When the matcher reference changes, poke the ImplicitContextHighlight
  // extension so its plugin rebuilds the DecorationSet on the next transaction.
  $effect(() => {
    if (editor) updateMatcher(matcher);
  });
  function updateMatcher(next: CompiledMatcher | null): void {
    if (!editor) return;
    const ext = editor.extensionManager.extensions.find(
      (e) => e.name === "implicitContextHighlight",
    );
    if (!ext) return;
    ext.options.matcher = next;
    const view = editor.view;
    if (!view) return;
    const tr = view.state.tr.setMeta(REBUILD_META, true).setMeta("addToHistory", false);
    view.dispatch(tr);
  }

  // Mirrors the body's updateSelectionMenu (ProseBodyView): a text selection or a
  // caret in a table shows the menu, in every prose editor alike (#1893).
  function updateMenu() {
    if (!editor || !root) return;
    const { selection } = editor.state;
    const inTable = editor.isActive("table");
    const selectedText = selection.empty ? "" : editor.state.doc.textBetween(selection.from, selection.to, " ").trim();
    const hasText = selectedText.length > 0;
    if (!editor.isFocused || (!hasText && !inTable)) {
      hideMenu();
      return;
    }
    const anchor = (hasText ? visibleSelectionRect(root) : null) ?? selectionEndpointRect(editor);
    const placed = placeSelectionToolbar(anchor, root.getBoundingClientRect(), root.clientWidth, {
      width: window.innerWidth,
      height: window.innerHeight,
    });
    menu = { visible: true, ...placed, wordCount: hasText ? countWords(selectedText) : 0 };
    actions = formattingToolbarActions(editor, hasText, inTable);
    openMenuId = null;
  }

  function hideMenu() {
    menu = { ...menu, visible: false };
    openMenuId = null;
  }

  function toggleMenu(id: string) {
    openMenuId = openMenuId === id ? null : id;
  }

  async function focusAndRun(command: () => void | Promise<void>) {
    try {
      await command();
    } finally {
      editor?.commands.focus();
      // A no-op command (Style → Paragraph on a paragraph) dispatches nothing,
      // so no selectionUpdate closes the dropdown — close it here, as the body
      // does, and let the menu re-derive from the current selection.
      openMenuId = null;
      updateMenu();
    }
  }

  // "Empty" for the `+` placeholder = one blank paragraph, the doc that
  // setContent("<p></p>") produces. TipTap's `editor.isEmpty` recurses into
  // children, so a freshly inserted 3×3 table with nothing typed would count
  // as empty and draw the `+` over its first cell.
  function isBlankDocument(ed: Editor): boolean {
    const { doc } = ed.state;
    return doc.childCount === 1 && doc.firstChild!.type.name === "paragraph" && doc.firstChild!.content.size === 0;
  }

  onMount(() => {
    editor = new Editor({
      element: editorElement,
      extensions: [
        StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
        Table.configure({ resizable: true }),
        TableRow,
        AlignedTableHeader,
        AlignedTableCell,
        ImplicitContextHighlight.configure({ matcher }),
      ],
      content: "",
      editorProps: {
        attributes: {
          class: "metadata-long-text-body",
          "aria-label": ariaLabel,
          spellcheck: "true",
        },
        transformPastedHTML: (html) => sanitizePastedHtml(html),
      },
      onUpdate: () => {
        if (!editor || applyingExternalValue) return;
        loadedValue = editorHtmlToSceneMarkdown(editor.getHTML());
        pendingLocalValue = loadedValue;
        isEmpty = isBlankDocument(editor);
        updateMenu();
        onChange(loadedValue);
      },
      onSelectionUpdate: updateMenu,
      onFocus: updateMenu,
      onBlur: hideMenu,
    });

    void loadValue(value);
    return () => editor?.destroy();
  });

  async function loadValue(nextValue: string) {
    if (!editor) return;
    applyingExternalValue = true;
    const html = await sceneMarkdownToHtml(nextValue || "");
    // The field can unmount while the markdown parse above is in flight (#1884
    // slice 3: a group fold now removes a long_text row from the DOM
    // synchronously) — `editor` itself isn't nulled by the onMount cleanup, so
    // re-check `isDestroyed` rather than crash into a torn-down ProseMirror view.
    if (editor.isDestroyed) return;
    editor.commands.setContent(html || "<p></p>", false);
    // An external value push is a boundary, not an edit: rebuild the state so
    // undo history starts empty. Without this, a same-id external replacement —
    // notably "reset to inherited" re-seeding this still-mounted editor — lands
    // on the live undo stack, so Ctrl+Z resurrects the cleared override and
    // autosave re-persists it (#691, the #368 pattern applied to this widget).
    editor.view.updateState(stateAtDocumentBoundary(editor.state));
    loadedValue = nextValue || "";
    lastExternalValue = nextValue || "";
    pendingLocalValue = null;
    applyingExternalValue = false;
    isEmpty = isBlankDocument(editor);
  }
</script>

<div class="metadata-long-text" class:is-empty={isEmpty} bind:this={root}>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div onmousedown={() => editor?.commands.focus()} bind:this={editorElement}></div>
</div>
<ProseSelectionToolbar {menu} {actions} {openMenuId} onRun={focusAndRun} onToggleMenu={toggleMenu} />

<style>
  /* #1884: the container chrome (border, toolbar, scrollbox cap) is gone — the
     field reads as prose at rest, a quiet inset marks focus, and formatting
     happens through the same floating toolbar the body uses (ProseSelectionToolbar),
     shown on a text selection or with the caret in a table. Despite the shared
     TipTap document model, this field previously inherited the sans UI font at
     --fs-md, so long_text prose — the intrinsic Body field included — read as
     chrome, not prose (#546); it now matches the body editor's serif /
     prose-size / 1.65 typography. */
  .metadata-long-text {
    position: relative;
    border-radius: var(--r-md);
    color: var(--text);
    transition: background var(--t-fast), box-shadow var(--t-fast);
  }

  /* Editing: a quiet inset and the accent stripe the rail's open row uses. */
  .metadata-long-text:focus-within {
    background: var(--inset);
    box-shadow: inset 2px 0 0 var(--accent);
  }

  /* Empty at rest: a bare + where the first line would start — the empties rule (#1884). */
  .metadata-long-text.is-empty:not(:focus-within)::before {
    content: "+";
    position: absolute;
    left: 8px;
    top: 2px;
    color: var(--text-3);
    font-family: var(--sans);
    font-size: var(--fs-lg);
    line-height: 1.65;
    pointer-events: none;
  }

  :global(.metadata-long-text-body) {
    min-height: calc(1.65 * var(--fs-prose));   /* one prose line, so an empty field stays clickable */
    padding: 4px 8px;
    outline: none;
    font-family: var(--serif);
    font-size: var(--fs-prose);
    font-weight: 400;
    line-height: 1.65;
  }

  :global(.metadata-long-text-body p) {
    margin: 0 0 1em;
  }

  :global(.metadata-long-text-body p:last-child) {
    margin-bottom: 0;
  }

  /* Headings and tables mirror the body editor's own treatment: a tight heading
     line-height, and tabular data in the sans face at --fs-lg (the body editor
     switches tables out of the prose serif) rather than inheriting it. */
  :global(.metadata-long-text-body :is(h1, h2, h3)) {
    line-height: 1.25;
  }

  :global(.metadata-long-text-body table) {
    width: 100%;
    margin: 4px 0;
    border-collapse: collapse;
    font-family: var(--sans);
    font-size: var(--fs-lg);
  }

  :global(.metadata-long-text-body td),
  :global(.metadata-long-text-body th) {
    border: 1px solid var(--border);
    padding: 4px 6px;
  }
</style>
