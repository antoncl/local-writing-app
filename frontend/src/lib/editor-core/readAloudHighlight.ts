// Read aloud (#2570): the sentence being spoken, shown in the editor. The plugin
// state is just its range (mapped through edits - a flag's own mark leaves it
// alone); the reading itself lives in stores/readAloud.svelte.ts, which this
// hands the reading-only keys and sentence clicks to. The controller comes in
// through `configure`, so this file never imports the store that dispatches here.
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet, type EditorView } from "@tiptap/pm/view";

export type ReadAloudRange = { from: number; to: number };

/** What the extension needs of the reading controller. */
export interface ReadAloudInput {
  /** A key press in `view`; true when the reading consumed it. */
  handleKey(view: EditorView, event: KeyboardEvent): boolean;
  /** A click at doc position `pos` in `view` (a no-op unless `view` is being read). */
  handleClick(view: EditorView, pos: number): void;
}

const pluginKey = new PluginKey<ReadAloudRange | null>("readAloudHighlight");

/** Show `range` as the current sentence, or clear it with null. */
export function setReadAloudHighlight(view: EditorView, range: ReadAloudRange | null): void {
  view.dispatch(view.state.tr.setMeta(pluginKey, { range }).setMeta("addToHistory", false));
}

export const ReadAloudHighlight = Extension.create<{ input: ReadAloudInput | null }>({
  name: "readAloudHighlight",

  addOptions() {
    return { input: null };
  },

  addProseMirrorPlugins() {
    const input = this.options.input;
    return [
      new Plugin<ReadAloudRange | null>({
        key: pluginKey,
        state: {
          init: () => null,
          apply: (tr, old) => {
            const meta = tr.getMeta(pluginKey) as { range: ReadAloudRange | null } | undefined;
            if (meta) return meta.range;
            if (!old || !tr.docChanged) return old;
            const from = tr.mapping.map(old.from, 1);
            const to = tr.mapping.map(old.to, -1);
            return to > from ? { from, to } : null;
          },
        },
        props: {
          decorations: (state) => {
            const range = pluginKey.getState(state);
            if (!range) return DecorationSet.empty;
            return DecorationSet.create(state.doc, [Decoration.inline(range.from, range.to, { class: "read-aloud-current" })]);
          },
          handleKeyDown: (view, event) => input?.handleKey(view, event) ?? false,
          handleClick: (view, pos) => {
            input?.handleClick(view, pos);
            return false;
          },
        },
      }),
    ];
  },
});
