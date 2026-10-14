// @vitest-environment happy-dom
// EditorTitleField (#2473 split of NodeEditor): one input, seven states. Pins the
// editable input's callback, the read-only states, and the scrub-stop draft
// (commit on blur, Esc reverts, no commit when unchanged).
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import EditorTitleField from "./EditorTitleField.svelte";

function props(over: Record<string, unknown> = {}) {
  return {
    title: "Opening",
    scrubbed: false,
    stopEditable: false,
    titleMutated: false,
    effectiveTitle: "Opening",
    snapshotParked: false,
    snapshots: { titleDiffers: false, view: "now", titleForView: "Was" } as never,
    reviewing: false,
    inheritedReadOnly: false,
    bodyFrozen: false,
    documentLabel: "Scene",
    documentNameLabel: "Title",
    onInput: vi.fn(),
    onCommitStop: vi.fn(),
    ...over,
  };
}

describe("EditorTitleField", () => {
  it("is an editable input that reports typing", async () => {
    const p = props();
    render(EditorTitleField, { props: p });
    const input = screen.getByLabelText("Scene title") as HTMLInputElement;
    expect(input.readOnly).toBe(false);
    await fireEvent.input(input, { target: { value: "Prologue" } });
    expect(p.onInput).toHaveBeenCalled();
  });

  it("is read-only while reviewing, inherited, written, or parked", () => {
    for (const [over, label] of [
      [{ reviewing: true }, "Scene title (under review, read-only)"],
      [{ inheritedReadOnly: true }, "Scene title (inherited, read-only)"],
      [{ bodyFrozen: true }, "Scene title (written as a scene, read-only)"],
      [{ snapshotParked: true }, "Scene title (snapshot, read-only)"],
    ] as const) {
      const { unmount } = render(EditorTitleField, { props: props(over) });
      expect((screen.getByLabelText(label) as HTMLInputElement).readOnly).toBe(true);
      unmount();
    }
  });

  it("commits a scrub-stop edit on blur, reverts on Escape, and skips an unchanged blur", async () => {
    const p = props({ scrubbed: true, stopEditable: true, effectiveTitle: "At stop" });
    render(EditorTitleField, { props: p });
    const input = screen.getByLabelText("Scene title (editing this stop)") as HTMLInputElement;
    expect(input.value).toBe("At stop");

    await fireEvent.blur(input);
    expect(p.onCommitStop).not.toHaveBeenCalled();

    await fireEvent.input(input, { target: { value: "Edited" } });
    await fireEvent.blur(input);
    expect(p.onCommitStop).toHaveBeenCalledWith("Edited");

    await fireEvent.input(input, { target: { value: "Discard me" } });
    await fireEvent.keyDown(input, { key: "Escape" });
    expect(input.value).toBe("At stop");
  });
});
