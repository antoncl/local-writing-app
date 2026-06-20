<script lang="ts">
  // Plain-text editor wrapping a thin TipTap instance — paragraph + hard
  // break only, no formatting marks, no rich nodes. Drop-in replacement
  // for a multi-line <textarea> when we need a ProseMirror substrate
  // (so the implicit-context decoration plugin from step 9 can attach
  // hit highlights without overlay tricks).
  //
  // Contract: two-way string binding via `value` prop + `change` event.
  // Behaves textarea-like — multi-line, plain text, soft-wrap. Hard
  // returns produce paragraph breaks. Shift+Enter still inserts a hard
  // break within a paragraph (TipTap default).
  import { createEventDispatcher, onMount } from "svelte";
  import { Editor } from "@tiptap/core";
  import StarterKit from "@tiptap/starter-kit";
  import { ImplicitContextHighlight, REBUILD_META } from "./implicitContextHighlight";
  import type { CompiledMatcher } from "./implicitContextMatcher";

  export let value = "";
  export let placeholder = "";
  export let ariaLabel = "";
  export let minHeight = 60;
  export let maxHeight: number | null = null;
  export let autofocus = false;
  // When present, decorates lore-name matches inline so the user can see
  // what the implicit-context expander would pick up on send.
  export let matcher: CompiledMatcher | null = null;
  // Optional class additions on the wrapper (so callers can size or theme).
  let className = "";
  export { className as class };

  const dispatch = createEventDispatcher<{
    change: { value: string };
    keydown: KeyboardEvent;
  }>();

  let editorElement: HTMLDivElement;
  let editor: Editor | null = null;
  let isEmpty = true;
  let lastExternalValue = "";
  let pendingLocalValue: string | null = null;
  let applyingExternalValue = false;

  // External value changes — sync into the editor without re-emitting
  // change. Pattern mirrors MetadataLongTextEditor's external/local guard.
  $: if (editor && value !== lastExternalValue && !applyingExternalValue) {
    if (pendingLocalValue !== null && value === pendingLocalValue) {
      lastExternalValue = value;
      pendingLocalValue = null;
    } else {
      loadValue(value);
    }
  }

  // When the matcher reference changes (lore loaded / edited), poke the
  // ImplicitContextHighlight extension so its plugin rebuilds the
  // DecorationSet against the new pattern set on the next transaction.
  // Dispatching a no-op transaction is the cheapest way to trigger
  // apply() without mutating the document.
  $: if (editor) updateMatcher(matcher);
  function updateMatcher(next: CompiledMatcher | null): void {
    if (!editor) return;
    const ext = editor.extensionManager.extensions.find(
      (e) => e.name === "implicitContextHighlight",
    );
    if (!ext) return;
    ext.options.matcher = next;
    // Force a re-decoration: the plugin's apply() listens for the
    // REBUILD_META marker and re-runs the scan even on no-op transactions.
    const view = editor.view;
    if (!view) return;
    const tr = view.state.tr.setMeta(REBUILD_META, true).setMeta("addToHistory", false);
    view.dispatch(tr);
  }

  onMount(() => {
    editor = new Editor({
      element: editorElement,
      extensions: [
        // Strip everything except paragraph + hard break — we want plain
        // text semantics, no rich formatting. Disabling these prevents
        // the user from accidentally getting bold/italic/list/heading
        // structure they can't see styled.
        StarterKit.configure({
          heading: false,
          bulletList: false,
          orderedList: false,
          blockquote: false,
          codeBlock: false,
          horizontalRule: false,
          bold: false,
          italic: false,
          strike: false,
          code: false,
          link: false,
        }),
        ImplicitContextHighlight.configure({ matcher }),
      ],
      content: "",
      editorProps: {
        attributes: {
          class: "plain-text-editor-body",
          "aria-label": ariaLabel,
          spellcheck: "true",
        },
        handleKeyDown: (_view, event) => {
          // Forward to parent so callers can intercept (e.g. Ctrl+Enter
          // to send a chat). Returning false lets ProseMirror handle the
          // event normally afterward; parents that want to preventDefault
          // must call event.preventDefault() themselves.
          dispatch("keydown", event);
          return false;
        },
      },
      autofocus: autofocus ? "end" : false,
      onUpdate: () => {
        if (!editor || applyingExternalValue) return;
        const text = editor.getText();
        isEmpty = editor.isEmpty;
        pendingLocalValue = text;
        dispatch("change", { value: text });
      },
      onCreate: () => {
        if (editor) isEmpty = editor.isEmpty;
      },
    });

    loadValue(value);
    return () => editor?.destroy();
  });

  function loadValue(nextValue: string) {
    if (!editor) return;
    applyingExternalValue = true;
    // setContent accepts plain text via paragraph wrappers. Splitting on
    // \n\n preserves paragraph breaks coming from external state; single
    // \n becomes a soft break inside the paragraph.
    const paragraphs = (nextValue || "").split(/\n\n+/);
    const doc = {
      type: "doc",
      content: paragraphs.map((para) => ({
        type: "paragraph",
        content: para
          ? para.split("\n").flatMap((line, i) => {
              const out: { type: string; text?: string }[] = [];
              if (i > 0) out.push({ type: "hardBreak" });
              if (line) out.push({ type: "text", text: line });
              return out;
            })
          : [],
      })),
    };
    editor.commands.setContent(doc, false);
    isEmpty = editor.isEmpty;
    lastExternalValue = nextValue || "";
    pendingLocalValue = null;
    applyingExternalValue = false;
  }

  export function focus() {
    editor?.commands.focus("end");
  }
</script>

<div
  class="plain-text-editor {className}"
  style:--plain-text-min-height={`${minHeight}px`}
  style:--plain-text-max-height={maxHeight ? `${maxHeight}px` : "none"}
>
  {#if isEmpty && placeholder}
    <div class="plain-text-editor-placeholder" aria-hidden="true">{placeholder}</div>
  {/if}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div bind:this={editorElement} on:mousedown={() => editor?.commands.focus()}></div>
</div>

<style>
  .plain-text-editor {
    position: relative;
    border: 1px solid #cdd6d3;
    border-radius: 6px;
    background: #ffffff;
    overflow: hidden;
  }

  .plain-text-editor:focus-within {
    border-color: #7d9d92;
    box-shadow: 0 0 0 2px rgba(125, 157, 146, 0.15);
  }

  .plain-text-editor-placeholder {
    position: absolute;
    top: 8px;
    left: 10px;
    color: #98a2a0;
    pointer-events: none;
    font-size: 15px;
    line-height: 1.5;
  }

  :global(.plain-text-editor-body) {
    min-height: var(--plain-text-min-height, 60px);
    max-height: var(--plain-text-max-height, none);
    padding: 8px 10px;
    overflow: auto;
    outline: none;
    font-family: inherit;
    font-size: 15px;
    font-weight: 400;
    line-height: 1.5;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  :global(.plain-text-editor-body p) {
    margin: 0 0 0.45em;
  }

  :global(.plain-text-editor-body p:last-child) {
    margin-bottom: 0;
  }
</style>
