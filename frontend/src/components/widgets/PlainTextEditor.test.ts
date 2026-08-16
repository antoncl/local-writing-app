// @vitest-environment happy-dom
import { describe, it, expect } from "vitest";
import { render } from "@/lib/test/component";

import PlainTextEditor from "@/components/widgets/PlainTextEditor.svelte";

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
});
