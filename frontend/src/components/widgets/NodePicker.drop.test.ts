// @vitest-environment happy-dom
// NodePicker accepts a node row dragged from a list when `acceptDrops` is on (#2413).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@/lib/test/component";
import NodePicker from "./NodePicker.svelte";
import { setupNodePicker, teardownNodePicker } from "./NodePicker.testkit";
import { NODE_DND_MIME, clearNodeDrag, setNodeDrag } from "@/lib/nodeDrag";
import type { NodePickerRef } from "@/lib/types";

beforeEach(setupNodePicker);
afterEach(() => {
  clearNodeDrag();
  teardownNodePicker();
});

const ref = (id: string, entry_type = "lore:character"): NodePickerRef => ({ id, kind: "lore", title: id, entry_type });
const config = { sources: [{ kind: "lore" }] };

function dataTransfer(payload: NodePickerRef) {
  return {
    types: [NODE_DND_MIME],
    getData: (t: string) => (t === NODE_DND_MIME ? JSON.stringify(payload) : ""),
    dropEffect: "none",
  };
}

describe("NodePicker node drops (#2413)", () => {
  it("adds a dropped admitted node and shows the drop cue while hovering", async () => {
    const onChange = vi.fn();
    const { container } = render(NodePicker, { props: { config, value: [ref("a")], acceptDrops: true, onChange } });
    const root = container.querySelector(".ctx-picker")!;
    setNodeDrag({ dataTransfer: { setData() {}, effectAllowed: "uninitialized" } } as unknown as DragEvent, ref("b"));
    await fireEvent.dragOver(root, { dataTransfer: dataTransfer(ref("b")) });
    expect(root.classList.contains("drop-ready")).toBe(true);
    await fireEvent.drop(root, { dataTransfer: dataTransfer(ref("b")) });
    expect(onChange).toHaveBeenCalledWith({ value: [ref("a"), ref("b")] });
  });

  it("ignores a node that is already picked or not admitted", async () => {
    const onChange = vi.fn();
    const { container } = render(NodePicker, { props: { config, value: [ref("a")], acceptDrops: true, onChange } });
    const root = container.querySelector(".ctx-picker")!;
    await fireEvent.drop(root, { dataTransfer: dataTransfer(ref("a")) });
    await fireEvent.drop(root, { dataTransfer: dataTransfer({ ...ref("s"), kind: "manuscript" }) });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does nothing without acceptDrops", async () => {
    const onChange = vi.fn();
    const { container } = render(NodePicker, { props: { config, value: [], onChange } });
    await fireEvent.drop(container.querySelector(".ctx-picker")!, { dataTransfer: dataTransfer(ref("b")) });
    expect(onChange).not.toHaveBeenCalled();
  });
});
