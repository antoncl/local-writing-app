// @vitest-environment happy-dom
// The shared "Show N hidden" shelf footer (#723). Only appears when something is
// hidden (it's the sole path back to un-hiding), and its label flips with the
// revealed state — the exact "Show N hidden" text the pane tests match on.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import LibraryHiddenToggle from "./LibraryHiddenToggle.svelte";

describe("LibraryHiddenToggle", () => {
  it("renders nothing when nothing is hidden", () => {
    const { container } = render(LibraryHiddenToggle, {
      props: { count: 0, shown: false, onToggle: vi.fn() },
    });
    expect(container.querySelector("button")).toBeNull();
  });

  it("shows 'Show N hidden' collapsed and 'Hide N hidden' when revealed", () => {
    const { rerender } = render(LibraryHiddenToggle, {
      props: { count: 2, shown: false, onToggle: vi.fn() },
    });
    expect(screen.getByRole("button", { name: /Show 2 hidden/ })).toBeInTheDocument();
    expect(screen.getByRole("button").getAttribute("aria-pressed")).toBe("false");
    rerender({ count: 2, shown: true, onToggle: vi.fn() });
    expect(screen.getByRole("button", { name: /Hide 2 hidden/ })).toBeInTheDocument();
    expect(screen.getByRole("button").getAttribute("aria-pressed")).toBe("true");
  });

  it("fires onToggle when clicked", async () => {
    const onToggle = vi.fn();
    render(LibraryHiddenToggle, { props: { count: 1, shown: false, onToggle } });
    await fireEvent.click(screen.getByRole("button"));
    expect(onToggle).toHaveBeenCalledOnce();
  });
});
