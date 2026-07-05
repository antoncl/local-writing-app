<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { EditorView, basicSetup } from "codemirror";
  import { Compartment } from "@codemirror/state";
  import { StreamLanguage } from "@codemirror/language";
  import { jinja2 } from "@codemirror/legacy-modes/mode/jinja2";
  import { json as jsonLang } from "@codemirror/lang-json";
  import { lintGutter, setDiagnostics, type Diagnostic } from "@codemirror/lint";

  export let value: string;
  // Languages that ship with a CodeMirror extension here highlight; anything
  // else falls through to a plain code surface (still better than TipTap for
  // editing raw text — monospace font, no auto-formatting).
  export let language: "jinja2" | "json" | "markdown" | "plain" = "jinja2";
  /** Soft-wrap long lines instead of horizontal scrolling. Live-reconfigured
   * via a Compartment so callers can toggle it without rebuilding the view. */
  export let lineWrapping = false;
  /** Diagnostics to pin in the gutter. Line is 1-based (matches Jinja's
   * `lineno`); col is optional and 1-based when present. Callers update this
   * prop after a render; CodeEditor reactively pushes them into CodeMirror. */
  export let diagnostics: { line: number; col?: number; severity: "error" | "warning"; message: string }[] = [];

  let host: HTMLDivElement;
  let editor: EditorView | null = null;
  let lastEmitted = value;
  const wrapCompartment = new Compartment();

  onMount(() => {
    const extensions = [basicSetup, lintGutter()];
    if (language === "jinja2") {
      extensions.push(StreamLanguage.define(jinja2));
    } else if (language === "json") {
      extensions.push(jsonLang());
    }
    extensions.push(wrapCompartment.of(lineWrapping ? EditorView.lineWrapping : []));
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
    pushDiagnostics();
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

  // Live-toggle soft wrap when the prop changes.
  $: if (editor) {
    editor.dispatch({
      effects: wrapCompartment.reconfigure(lineWrapping ? EditorView.lineWrapping : []),
    });
  }

  // Push diagnostics whenever the prop changes.
  $: if (editor) pushDiagnostics(diagnostics);

  function pushDiagnostics(_d = diagnostics): void {
    if (!editor) return;
    const doc = editor.state.doc;
    const items: Diagnostic[] = [];
    for (const d of _d) {
      if (!Number.isFinite(d.line) || d.line < 1 || d.line > doc.lines) continue;
      const lineInfo = doc.line(d.line);
      const col = d.col && d.col > 0 ? Math.min(d.col, lineInfo.length + 1) : 1;
      // Underline the column point if given, otherwise the whole line. Either
      // way the gutter marker shows on the line and the message tooltip is
      // available on hover.
      const from = lineInfo.from + col - 1;
      const to = d.col ? Math.min(from + 1, lineInfo.to) : lineInfo.to;
      items.push({
        from,
        to: to <= from ? Math.min(from + 1, doc.length) : to,
        severity: d.severity,
        message: d.message,
      });
    }
    editor.dispatch(setDiagnostics(editor.state, items));
  }
</script>

<div bind:this={host} class="code-editor" data-lang={language}></div>

<style>
  .code-editor :global(.cm-editor) {
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--surface);
    color: var(--text);
  }
  .code-editor :global(.cm-editor.cm-focused) {
    outline: 2px solid var(--accent);
    outline-offset: -1px;
  }
  .code-editor :global(.cm-scroller) {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: var(--fs-md);
    line-height: 1.5;
  }
  .code-editor :global(.cm-content) {
    padding: 6px 0;
  }
  .code-editor :global(.cm-gutters) {
    background: var(--inset);
    border-right: 1px solid var(--border);
    color: var(--text-2);
  }
</style>
