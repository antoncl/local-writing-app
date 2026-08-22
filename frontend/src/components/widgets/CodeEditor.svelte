<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { EditorView, basicSetup } from "codemirror";
  import { Compartment, EditorState } from "@codemirror/state";
  import { StreamLanguage } from "@codemirror/language";
  import { jinja2 } from "@codemirror/legacy-modes/mode/jinja2";
  import { json as jsonLang } from "@codemirror/lang-json";
  import { lintGutter, setDiagnostics, type Diagnostic } from "@codemirror/lint";
  import type { CompletionSource } from "@codemirror/autocomplete";

  let {
    value = $bindable(),
    // Languages that ship with a CodeMirror extension here highlight; anything
    // else falls through to a plain code surface (still better than TipTap for
    // editing raw text — monospace font, no auto-formatting).
    language = "jinja2",
    // Soft-wrap long lines instead of horizontal scrolling. Live-reconfigured
    // via a Compartment so callers can toggle it without rebuilding the view.
    lineWrapping = false,
    // Diagnostics to pin in the gutter. Line is 1-based (matches Jinja's
    // `lineno`); col is optional and 1-based when present. Callers update this
    // prop after a render; CodeEditor reactively pushes them into CodeMirror.
    diagnostics = [],
    // Lock the buffer against edits (ADR-0049: a built-in Library prompt is
    // shipped read-only material — clone it to edit). Live-reconfigured via a
    // Compartment. `EditorView.editable.of(false)` also drops the caret so the
    // surface reads as a viewer, not a focusable-but-inert field.
    readOnly = false,
    // Optional CodeMirror completion source, registered on the jinja2 language
    // only (#30). Captured at mount; a stable source that reads live state
    // through closures (e.g. the prompt's declared inputs) keeps completions
    // current without re-registering.
    completionSource = undefined,
  }: {
    value: string;
    language?: "jinja2" | "json" | "markdown" | "plain";
    lineWrapping?: boolean;
    diagnostics?: { line: number; col?: number; severity: "error" | "warning"; message: string }[];
    readOnly?: boolean;
    completionSource?: CompletionSource;
  } = $props();

  let host: HTMLDivElement;
  let editor: EditorView | null = null;
  let lastEmitted = $state(value);
  const wrapCompartment = new Compartment();
  const readOnlyCompartment = new Compartment();

  const readOnlyExtensions = (ro: boolean) =>
    ro ? [EditorState.readOnly.of(true), EditorView.editable.of(false)] : [];

  onMount(() => {
    const extensions = [basicSetup, lintGutter()];
    if (language === "jinja2") {
      const jinjaLanguage = StreamLanguage.define(jinja2);
      extensions.push(jinjaLanguage);
      // basicSetup already enables the autocompletion UI; this registers our
      // source for the jinja language so it drives it (no second autocompletion).
      if (completionSource) {
        extensions.push(jinjaLanguage.data.of({ autocomplete: completionSource }));
      }
    } else if (language === "json") {
      extensions.push(jsonLang());
    }
    extensions.push(wrapCompartment.of(lineWrapping ? EditorView.lineWrapping : []));
    extensions.push(readOnlyCompartment.of(readOnlyExtensions(readOnly)));
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
  $effect(() => {
    if (editor && value !== lastEmitted) {
      const current = editor.state.doc.toString();
      if (current !== value) {
        editor.dispatch({
          changes: { from: 0, to: current.length, insert: value },
        });
        lastEmitted = value;
      }
    }
  });

  // Live-toggle soft wrap when the prop changes.
  $effect(() => {
    if (editor) {
      editor.dispatch({
        effects: wrapCompartment.reconfigure(lineWrapping ? EditorView.lineWrapping : []),
      });
    }
  });

  // Live-toggle read-only when the prop changes.
  $effect(() => {
    if (editor) {
      editor.dispatch({
        effects: readOnlyCompartment.reconfigure(readOnlyExtensions(readOnly)),
      });
    }
  });

  // Push diagnostics whenever the prop changes.
  $effect(() => {
    if (editor) pushDiagnostics(diagnostics);
  });

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
    font-family: var(--mono);
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
  /* CodeMirror tooltips (the lint diagnostic is one — a `.cm-tooltip-lint`
     section INSIDE a `.cm-tooltip.cm-tooltip-hover` wrapper) ship only a light
     appearance (@codemirror/view `&light .cm-tooltip` → #f5f5f5) because this
     editor never enables CodeMirror's dark variant. In the app's dark mode that
     light band inherits our light `.cm-editor` `color: var(--text)`, so the
     message was near-white on near-white — illegible (#1155/#1158). Theme the
     `.cm-tooltip` WRAPPER (the background lives there, not on the lint section)
     with our tokens; the extra `.cm-editor` lifts specificity above CodeMirror's
     own `&light` rule regardless of stylesheet insertion order. */
  .code-editor :global(.cm-editor .cm-tooltip) {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text);
  }
  .code-editor :global(.cm-diagnostic-error) {
    border-left-color: var(--danger);
  }
  .code-editor :global(.cm-diagnostic-warning) {
    border-left-color: var(--warn);
  }
</style>
