// @vitest-environment happy-dom
import { describe, it, expect } from "vitest";
import { render } from "@/lib/test/component";

import PlainTextEditor from "@/components/widgets/PlainTextEditor.svelte";
import PlainTextEditorEventHarness from "@/components/widgets/PlainTextEditorEventHarness.svelte";
import PlainTextEditorRefHarness from "@/components/widgets/PlainTextEditorRefHarness.svelte";

// Regression for #1037: while a send/commit is in flight the composer must
// present as locked (dimmed + non-editable), not silently swallow keystrokes.
// The `disabled` prop drives both the visible affordance here and the
// editor.setEditable(false) call that actually rejects input.
describe("PlainTextEditor disabled affordance", () => {
  it("is editable by default", () => {
    const { container } = render(PlainTextEditor, { props: { value: "hi" } });
    const wrapper = container.querySelector(".plain-text-editor");
    expect(wrapper).not.toBeNull();
    expect(wrapper?.classList.contains("is-disabled")).toBe(false);
    expect(wrapper?.getAttribute("aria-disabled")).toBe("false");
  });

  it("marks the wrapper disabled when the prop is set", () => {
    const { container } = render(PlainTextEditor, { props: { value: "hi", disabled: true } });
    const wrapper = container.querySelector(".plain-text-editor");
    expect(wrapper?.classList.contains("is-disabled")).toBe(true);
    expect(wrapper?.getAttribute("aria-disabled")).toBe("true");
  });

  it("reflects a prop change from disabled back to enabled", async () => {
    const { container, rerender } = render(PlainTextEditor, {
      props: { value: "hi", disabled: true },
    });
    expect(container.querySelector(".plain-text-editor")?.classList.contains("is-disabled")).toBe(
      true,
    );
    await rerender({ value: "hi", disabled: false });
    expect(container.querySelector(".plain-text-editor")?.classList.contains("is-disabled")).toBe(
      false,
    );
  });

  // Regression for #1071: toggling `disabled` must NOT emit a `change`. It drives
  // editor.setEditable, and passing emitUpdate=false keeps that presentation-only
  // toggle from firing onUpdate — which would echo the editor's current text back
  // into `value` and defeat a same-flush programmatic clear (the chat composer
  // failing to clear on the 2nd+ send).
  it("does not emit change when toggling disabled", async () => {
    const changes: string[] = [];
    const { rerender } = render(PlainTextEditorEventHarness, {
      props: { value: "hello", disabled: false, changes },
    });
    await rerender({ value: "hello", disabled: true, changes });
    await rerender({ value: "hello", disabled: false, changes });
    expect(changes).toEqual([]);
  });
});

// Regression for #1083: the chat composer stopped clearing from the 2nd send on
// because the reactive value-sync could wedge. `setValue` is the imperative
// escape hatch sendChat uses so the clear can't be lost to a skipped sync.
describe("PlainTextEditor imperative setValue (#1083)", () => {
  // sendChat calls `composerRef.setValue("")` via bind:this so the clear can't be
  // lost to a wedged value-sync. This guards that contract: the instance exposes
  // setValue and it drives the editor without throwing. (Its behaviour *against*
  // a wedged sync needs a real browser — happy-dom's ProseMirror plus the
  // value-prop reasserting itself make the DOM effect untestable in isolation.)
  it("exposes an imperative setValue via bind:this", () => {
    let api: { setValue: (v: string) => void; focus: () => void } | undefined;
    render(PlainTextEditorRefHarness, {
      props: { value: "hello world", onReady: (a: typeof api) => (api = a) },
    });
    expect(typeof api?.setValue).toBe("function");
    expect(() => api!.setValue("")).not.toThrow();
    expect(() => api!.setValue("restored draft")).not.toThrow();
  });
});
