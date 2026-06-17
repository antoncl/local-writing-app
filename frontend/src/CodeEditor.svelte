<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { EditorView, basicSetup } from "codemirror";
  import { StreamLanguage } from "@codemirror/language";
  import { jinja2 } from "@codemirror/legacy-modes/mode/jinja2";
  import { json as jsonLang } from "@codemirror/lang-json";

  export let value: string;
  export let language: "jinja2" | "json" = "jinja2";

  let host: HTMLDivElement;
  let editor: EditorView | null = null;
  let lastEmitted = value;

  onMount(() => {
    const extensions = [basicSetup];
    if (language === "jinja2") {
      extensions.push(StreamLanguage.define(jinja2));
    } else if (language === "json") {
      extensions.push(jsonLang());
    }
    extensions.push(
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          const next = update.state.doc.toString();
          lastEmitted = next;
          value = next;
        }
      }),
    );
    editor = new EditorView({ doc: value, parent: host, extensions });
  });

  onDestroy(() => {
    editor?.destroy();
    editor = null;
  });

  // External writes to `value` (e.g. reset to default) propagate into the editor.
  $: if (editor && value !== lastEmitted) {
    const current = editor.state.doc.toString();
    if (current !== value) {
      editor.dispatch({
        changes: { from: 0, to: current.length, insert: value },
      });
      lastEmitted = value;
    }
  }
</script>

<div bind:this={host} class="code-editor" data-lang={language}></div>

<style>
  .code-editor :global(.cm-editor) {
    border: 1px solid #cbd6d2;
    border-radius: 4px;
    background: #ffffff;
  }
  .code-editor :global(.cm-editor.cm-focused) {
    outline: 2px solid #6f9d8b;
    outline-offset: -1px;
  }
  .code-editor :global(.cm-scroller) {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 14px;
    line-height: 1.5;
  }
  .code-editor :global(.cm-content) {
    padding: 6px 0;
  }
  .code-editor :global(.cm-gutters) {
    background: #f1f4f3;
    border-right: 1px solid #d8dfdd;
    color: #4d5753;
  }
</style>
