/** Reviewing a model's line edits in place (#2460).
 *
 *  The placed edits live in this plugin's state, NOT in the document: the
 *  original text stays untouched until an edit is accepted. Each edit shows as
 *  its old text struck through, the new text right after it, and a small
 *  accept / reject pair; the reason is the hover title. Positions are mapped
 *  through every transaction, and an edit is dropped once the writer edits
 *  inside it (its range no longer holds the text the model quoted). */
import { Extension } from "@tiptap/core";
import type { EditorState } from "@tiptap/pm/state";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet, type EditorView } from "@tiptap/pm/view";
import type { PlacedEdit } from "./lineEdits";

export type LineEditSuggestion = PlacedEdit & { id: number };

export type LineEditState = {
  edits: LineEditSuggestion[];
  /** How many edits were accepted since the list was installed. */
  accepted: number;
};

type LineEditMeta =
  | { type: "install"; edits: PlacedEdit[] }
  | { type: "resolve"; ids: number[]; accepted: boolean };

export const LINE_EDIT_OLD_CLASS = "line-edit-old";
export const LINE_EDIT_NEW_CLASS = "line-edit-new";

const pluginKey = new PluginKey<LineEditState>("line-edit-suggestions");
const EMPTY: LineEditState = { edits: [], accepted: 0 };

// Text of a range the way `find` was matched: leaves as the placement sentinel.
const rangeText = (state: EditorState, from: number, to: number) => state.doc.textBetween(from, to, "\n", "￼");

export function lineEditState(state: EditorState): LineEditState {
  return pluginKey.getState(state) ?? EMPTY;
}

export function installLineEdits(view: EditorView, edits: PlacedEdit[]): void {
  view.dispatch(view.state.tr.setMeta(pluginKey, { type: "install", edits } satisfies LineEditMeta));
}

function resolve(view: EditorView, ids: number[], accepted: boolean): void {
  const { edits } = lineEditState(view.state);
  const targets = edits.filter((e) => ids.includes(e.id));
  if (targets.length === 0) return;
  const tr = view.state.tr;
  if (accepted) {
    // Descending, so each replace leaves the positions of the ones before it intact.
    for (const edit of [...targets].sort((a, b) => b.from - a.from)) {
      tr.insertText(edit.replace, edit.from, edit.to);
    }
  }
  tr.setMeta(pluginKey, { type: "resolve", ids, accepted } satisfies LineEditMeta);
  view.dispatch(tr);
}

export const acceptLineEdit = (view: EditorView, id: number) => resolve(view, [id], true);
export const rejectLineEdit = (view: EditorView, id: number) => resolve(view, [id], false);
export const acceptAllLineEdits = (view: EditorView) =>
  resolve(view, lineEditState(view.state).edits.map((e) => e.id), true);
export const rejectAllLineEdits = (view: EditorView) =>
  resolve(view, lineEditState(view.state).edits.map((e) => e.id), false);

function button(label: string, glyph: string, testid: string, onPress: () => void): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "line-edit-btn";
  btn.textContent = glyph;
  btn.setAttribute("aria-label", label);
  btn.title = label;
  btn.dataset.testid = testid;
  // mousedown + preventDefault: the click never blurs the editor.
  btn.addEventListener("mousedown", (e) => {
    e.preventDefault();
    onPress();
  });
  return btn;
}

function widgetFor(view: EditorView, edit: LineEditSuggestion): HTMLElement {
  const wrap = document.createElement("span");
  wrap.className = "line-edit-widget";
  wrap.contentEditable = "false";
  if (edit.replace) {
    const added = document.createElement("span");
    added.className = LINE_EDIT_NEW_CLASS;
    added.title = edit.reason;
    added.textContent = edit.replace;
    wrap.append(added);
  }
  wrap.append(
    button("Accept edit", "✓", "line-edit-accept", () => acceptLineEdit(view, edit.id)),
    button("Reject edit", "✕", "line-edit-reject", () => rejectLineEdit(view, edit.id)),
  );
  return wrap;
}

export const LineEditSuggestions = Extension.create({
  name: "lineEditSuggestions",

  addProseMirrorPlugins() {
    let nextId = 1;
    return [
      new Plugin<LineEditState>({
        key: pluginKey,
        state: {
          init: () => EMPTY,
          apply: (tr, old, _oldState, newState) => {
            const meta = tr.getMeta(pluginKey) as LineEditMeta | undefined;
            if (meta?.type === "install") {
              return { edits: meta.edits.map((e) => ({ ...e, id: nextId++ })), accepted: 0 };
            }
            if (old.edits.length === 0) return old;
            let edits = old.edits;
            if (tr.docChanged) {
              edits = edits.flatMap((edit) => {
                const from = tr.mapping.map(edit.from, 1);
                const to = tr.mapping.map(edit.to, -1);
                // Deleted, or edited inside: the model's quote no longer holds.
                if (to <= from || rangeText(newState, from, to) !== edit.find) return [];
                return [{ ...edit, from, to }];
              });
            }
            let accepted = old.accepted;
            if (meta?.type === "resolve") {
              edits = edits.filter((e) => !meta.ids.includes(e.id));
              if (meta.accepted) accepted += meta.ids.length;
            }
            return { edits, accepted };
          },
        },
        props: {
          decorations: (state) => {
            const { edits } = lineEditState(state);
            if (edits.length === 0) return DecorationSet.empty;
            const decos: Decoration[] = [];
            for (const edit of edits) {
              decos.push(
                Decoration.inline(edit.from, edit.to, { class: LINE_EDIT_OLD_CLASS, title: edit.reason }),
              );
              decos.push(
                Decoration.widget(edit.to, (view) => widgetFor(view, edit), {
                  side: 1,
                  key: `line-edit-${edit.id}-${edit.to}-${edit.replace}`,
                  stopEvent: () => true,
                }),
              );
            }
            return DecorationSet.create(state.doc, decos);
          },
        },
      }),
    ];
  },
});
