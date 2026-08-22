<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { Editor } from "@tiptap/core";
  import StarterKit from "@tiptap/starter-kit";
  import Table from "@tiptap/extension-table";
  import TableCell from "@tiptap/extension-table-cell";
  import TableHeader from "@tiptap/extension-table-header";
  import TableRow from "@tiptap/extension-table-row";
  import { editorHtmlToSceneMarkdown, sceneMarkdownToHtml } from "@/lib/utils/markdown";
  import { stateAtDocumentBoundary } from "@/lib/editor-core/documentBoundary";
  import { ImplicitContextHighlight, REBUILD_META } from "@/lib/editor-core/implicitContextHighlight";
  import type { CompiledMatcher } from "@/lib/editor-core/implicitContextMatcher";
  import { sanitizePastedHtml } from "@/lib/utils/sanitizePastedHtml";

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

  onMount(() => {
    editor = new Editor({
      element: editorElement,
      extensions: [
        StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
        Table.configure({ resizable: true }),
        TableRow,
        TableHeader,
        TableCell,
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
        onChange(loadedValue);
      },
    });

    void loadValue(value);
    return () => editor?.destroy();
  });

  async function loadValue(nextValue: string) {
    if (!editor) return;
    applyingExternalValue = true;
    const html = await sceneMarkdownToHtml(nextValue || "");
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
  }

  function run(command: () => void) {
    command();
    editor?.commands.focus();
  }
</script>

<div class="metadata-long-text">
  <div class="metadata-long-text-toolbar" aria-label={`${ariaLabel} formatting`}>
    <button type="button" title="Bold" onmousedown={(e) => { e.preventDefault(); run(() => editor?.chain().focus().toggleBold().run()); }}>B</button>
    <button type="button" title="Italic" onmousedown={(e) => { e.preventDefault(); run(() => editor?.chain().focus().toggleItalic().run()); }}>I</button>
    <button type="button" title="Heading 1" onmousedown={(e) => { e.preventDefault(); run(() => editor?.chain().focus().toggleHeading({ level: 1 }).run()); }}>H1</button>
    <button type="button" title="Heading 2" onmousedown={(e) => { e.preventDefault(); run(() => editor?.chain().focus().toggleHeading({ level: 2 }).run()); }}>H2</button>
    <button type="button" title="Bullet list" onmousedown={(e) => { e.preventDefault(); run(() => editor?.chain().focus().toggleBulletList().run()); }}>List</button>
    <button type="button" title="Numbered list" onmousedown={(e) => { e.preventDefault(); run(() => editor?.chain().focus().toggleOrderedList().run()); }}>1.</button>
    <button type="button" title="Quote" onmousedown={(e) => { e.preventDefault(); run(() => editor?.chain().focus().toggleBlockquote().run()); }}>Quote</button>
    <button type="button" title="Table" onmousedown={(e) => { e.preventDefault(); run(() => editor?.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()); }}>Table</button>
  </div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div onmousedown={() => editor?.commands.focus()} bind:this={editorElement}></div>
</div>

<style>
  .metadata-long-text {
    display: grid;
    border: 1px solid var(--divider);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text);
    overflow: hidden;
  }

  .metadata-long-text-toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    padding: 5px;
    border-bottom: 1px solid var(--divider);
    background: var(--inset);
  }

  .metadata-long-text-toolbar button {
    padding: 3px 6px;
    font-size: var(--fs-sm);
  }

  /* The prose surface reads like the manuscript body editor (#546). Despite the
     shared TipTap document model, this field previously inherited the sans UI
     font at --fs-md, so long_text prose — the intrinsic Body field included —
     read as chrome, not prose. Match the body editor's serif / prose-size / 1.65
     typography; the container chrome (border, toolbar, scrollbox cap) stays, as
     that frames it as a rail field rather than making it a different editor. */
  :global(.metadata-long-text-body) {
    min-height: 96px;
    max-height: 260px;
    padding: 8px 10px;
    overflow: auto;
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
