// @vitest-environment happy-dom
// #2464: the floating AI toolbar offers Cancel only while a generation runs.
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import ProseAIToolbar from "./ProseAIToolbar.svelte";

function mount(over: Record<string, unknown> = {}) {
  const onCancel = vi.fn();
  render(ProseAIToolbar, {
    props: {
      position: { x: 0, y: 0, visible: true },
      generating: false,
      suggestionId: null,
      error: null,
      meta: null,
      onAccept: () => {},
      onRetry: () => {},
      onDiscard: () => {},
      onDismissError: () => {},
      onCancel,
      ...over,
    } as never,
  });
  return { onCancel };
}

describe("ProseAIToolbar - Cancel (#2464)", () => {
  it("renders Cancel while generating and calls through without stealing focus", async () => {
    const { onCancel } = mount({ generating: true });
    const btn = screen.getByTestId("ai-cancel");
    expect(btn.getAttribute("aria-label")).toBe("Cancel generation");
    expect(btn.getAttribute("title")).toContain("Esc");
    const notPrevented = await fireEvent.mouseDown(btn);
    expect(notPrevented).toBe(false); // preventDefault was called
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("is absent when not generating", () => {
    mount({ suggestionId: "ai-1" });
    expect(screen.queryByTestId("ai-cancel")).toBeNull();
  });
});
