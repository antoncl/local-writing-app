// Editor-side operations on the `todoAnchor` mark (embedded TODOs, #1893's
// selection-toolbar "TODO" action and the TODO pane's reveal/reconcile
// paths), extracted from ProseBodyView so the component keeps only the
// call-site one-liners. Plain (no runes): every field here is read only from
// inside this class — the template never touches it.
import type { Editor } from "@tiptap/core";
import { TextSelection } from "@tiptap/pm/state";

/** A fresh todoAnchor mark id: `todo_` + 12 hex-ish characters. */
export function createTodoId(): string {
  const randomId = globalThis.crypto?.randomUUID?.().replace(/-/g, "") ?? Math.random().toString(16).slice(2);
  return `todo_${randomId.slice(0, 12)}`;
}

const HIGHLIGHT_MS = 2400;

export class TodoAnchors {
  #getEditor: () => Editor | null;
  #getElement: () => HTMLElement | null;
  #reconciling = false;
  #highlightedId: string | null = null;

  constructor(opts: { getEditor: () => Editor | null; getElement: () => HTMLElement | null }) {
    this.#getEditor = opts.getEditor;
    this.#getElement = opts.getElement;
  }

  /** Mark the current selection's plain text as a TODO: a fresh anchor id,
   *  wrapped as a `todoAnchor` mark. No-op with no editor, an empty
   *  selection, or a selection that has fallen outside the doc. */
  markSelection(): void {
    const editor = this.#getEditor();
    if (!editor) return;
    const { from, to } = editor.state.selection;
    const selectedText = editor.state.doc.textBetween(from, to, " ").trim();
    if (!selectedText) return;
    const anchorId = createTodoId();
    const docEnd = editor.state.doc.content.size;
    if (from >= to || from > docEnd || to > docEnd) return;
    editor.view.dispatch(editor.state.tr.setSelection(TextSelection.create(editor.state.doc, from, to)));
    editor.chain().focus().setMark("todoAnchor", { anchorId, status: "open", note: "" }).run();
    window.setTimeout(() => this.syncDomState(), 0);
  }

  /** Strip every anchor after the first occurrence of its id — a paste,
   *  drop, or redo can duplicate an anchor id, which would otherwise trip
   *  the embedded-TODO index's uniqueness. Returns whether the doc changed. */
  enforceUnique(): boolean {
    const seenAnchorIds = new Set<string>();
    return this.remove((anchorId) => {
      if (seenAnchorIds.has(anchorId)) return true;
      seenAnchorIds.add(anchorId);
      return false;
    });
  }

  /** Remove every `todoAnchor` mark whose id `shouldRemove` accepts.
   *  Re-entrancy guarded: the dispatch below re-fires `onUpdate`, which would
   *  otherwise recurse into this same reconcile. */
  remove(shouldRemove: (anchorId: string) => boolean): boolean {
    const editor = this.#getEditor();
    if (!editor || this.#reconciling) return false;
    const markType = editor.state.schema.marks.todoAnchor;
    if (!markType) return false;

    let transaction = editor.state.tr.setMeta("addToHistory", false);
    editor.state.doc.descendants((node, position) => {
      if (!node.isText) return true;
      for (const mark of node.marks) {
        if (mark.type !== markType) continue;
        const anchorId = String(mark.attrs.anchorId ?? "");
        if (anchorId && shouldRemove(anchorId)) {
          transaction = transaction.removeMark(position, position + node.nodeSize, mark);
        }
      }
      return true;
    });

    if (!transaction.docChanged) return false;
    this.#reconciling = true;
    editor.view.dispatch(transaction);
    this.#reconciling = false;
    window.setTimeout(() => this.syncDomState(), 0);
    return true;
  }

  /** Rename the DOM's render attr (`data-todo-anchor-id`) to the lookup key
   *  the TODO pane / search reveal use (`data-todo-id`), and reflect the
   *  highlight + status on every anchor. */
  syncDomState(): void {
    const element = this.#getElement();
    if (!element) return;
    for (const el of element.querySelectorAll<HTMLElement>("[data-todo-anchor-id]")) {
      el.dataset.todoId = el.dataset.todoAnchorId;
      delete el.dataset.todoAnchorId;
    }
    for (const el of element.querySelectorAll<HTMLElement>("[data-todo-id]")) {
      el.classList.toggle("todo-anchor-highlight", el.dataset.todoId === this.#highlightedId);
      const status = el.dataset.todoStatus === "done" ? "done" : "open";
      el.title = status === "done" ? "Completed TODO" : "Open TODO";
    }
  }

  /** Scroll an embedded TODO's anchor into view and pulse it for 2.4s
   *  (`highlightEmbeddedTodo`, called from the TODO pane / search). */
  highlight(todoId: string): void {
    const element = this.#getElement();
    if (!element) return;
    const target = element.querySelector<HTMLElement>(`[data-todo-id="${CSS.escape(todoId)}"]`);
    if (!target) return;
    this.#highlightedId = todoId;
    this.syncDomState();
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    window.setTimeout(() => {
      if (this.#highlightedId === todoId) {
        this.#highlightedId = null;
        this.syncDomState();
      }
    }, HIGHLIGHT_MS);
  }
}
