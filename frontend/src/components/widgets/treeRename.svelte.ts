// Inline-rename state for ViewNodeTree (#112 step 4c-iii). Like TreeDrag, the
// recursive renderer can't hold this — ViewNodeList owns ONE controller and
// threads it down; its `$state` fields stay reactive at every level.
//
// The wrapper owns the edit STATE (which node, the live value, focus, the
// trim/empty/unchanged guards); the consumer's `row` snippet renders only the
// styled `<input>` (binding `value`/`oninput`/`onblur` to this controller), and
// the actual persist is injected as `persist` (wired to the `onRename` escape
// hatch). `resolve` maps an id back to its node so commit can guard against a
// no-op rename without the consumer's structure.

import { tick } from "svelte";
import type { EvalNode } from "@/lib/views/evaluateView";

export class TreeRename<T extends EvalNode> {
  // The node currently being renamed, or null; and the live input text.
  editingId = $state<string | null>(null);
  editValue = $state("");

  #persist: (node: T, nextTitle: string) => void;
  #resolve: (id: string) => T | null;

  constructor(opts: { persist: (node: T, nextTitle: string) => void; resolve: (id: string) => T | null }) {
    this.#persist = opts.persist;
    this.#resolve = opts.resolve;
  }

  // Enter rename for a node (F2 / dblclick / just-created). Seeds the value and
  // focuses+selects the input once the row has re-rendered with it.
  begin(id: string, title: string): void {
    this.editingId = id;
    this.editValue = title;
    void tick().then(() => {
      const input = document.querySelector<HTMLInputElement>(`[data-node-edit-id="${id}"]`);
      input?.focus();
      input?.select();
    });
  }

  onInput(value: string): void {
    this.editValue = value;
  }

  // Commit the current edit: persist only a real, non-empty change (matches the
  // old snippet-side guards); always leaves edit mode.
  commit(): void {
    const id = this.editingId;
    if (!id) return;
    const node = this.#resolve(id);
    const trimmed = this.editValue.trim();
    this.editingId = null;
    if (!node || !trimmed || node.title === trimmed) return;
    this.#persist(node, trimmed);
  }

  // Cancel — unconditionally, or only if `id` is the row being edited (used when
  // that row is being deleted).
  cancel(id?: string): void {
    if (id !== undefined && this.editingId !== id) return;
    this.editingId = null;
  }
}
