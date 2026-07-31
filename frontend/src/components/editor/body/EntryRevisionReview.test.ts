// @vitest-environment happy-dom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";

import EntryRevisionReview from "@/components/editor/body/EntryRevisionReview.svelte";

// The review surface for a brainstorm commit (ADR-0046). These pin the #710
// whole-version gestures the surface adds over the per-region adopt: the judge
// toggle (Current / Proposed / Both) and the accept-all / reject-all pair. The
// prose rendering itself lives in RevisionFlip → ReadOnlyBodyOverlay (async
// markdown); here we only assert the controls render and route to their props.

const button = (name: string) => screen.getByRole("button", { name });

function baseProps(over: Record<string, unknown> = {}) {
  return {
    currentBody: "the current body",
    proposedBody: "the proposed body",
    fields: [],
    hasChanges: false,
    view: "both" as const,
    onView: vi.fn(),
    onToggleView: vi.fn(),
    onBodyResolved: vi.fn(),
    onFieldResolved: vi.fn(),
    onAcceptAll: vi.fn(),
    onDone: vi.fn(),
    onDiscard: vi.fn(),
    ...over,
  };
}

describe("EntryRevisionReview — #710 whole-version gestures", () => {
  it("renders the three-state judge control, Both pressed at open", () => {
    render(EntryRevisionReview, { props: baseProps({ view: "both" }) });
    expect(button("Current")).toBeInTheDocument();
    expect(button("Proposed")).toBeInTheDocument();
    expect(button("Both").getAttribute("aria-pressed")).toBe("true");
    expect(button("Current").getAttribute("aria-pressed")).toBe("false");
  });

  it("reflects the current view as the pressed segment", () => {
    render(EntryRevisionReview, { props: baseProps({ view: "was" }) });
    expect(button("Proposed").getAttribute("aria-pressed")).toBe("true");
    expect(button("Both").getAttribute("aria-pressed")).toBe("false");
  });

  it("routes a judge-control click to onView", async () => {
    const onView = vi.fn();
    render(EntryRevisionReview, { props: baseProps({ onView }) });
    await fireEvent.click(button("Proposed"));
    expect(onView).toHaveBeenCalledWith("was");
  });

  it("hides the judge control for a structured-only patch (no prose to read whole)", () => {
    render(EntryRevisionReview, { props: baseProps({ proposedBody: null, fields: [] }) });
    expect(screen.queryByRole("button", { name: "Current" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Proposed" })).toBeNull();
    // The whole-version pair still stands — a structured patch is decided too.
    expect(button("Accept all")).toBeInTheDocument();
    expect(button("Reject all")).toBeInTheDocument();
  });

  it("routes Accept all / Reject all to their symmetric callbacks", async () => {
    const onAcceptAll = vi.fn();
    const onDiscard = vi.fn();
    render(EntryRevisionReview, { props: baseProps({ onAcceptAll, onDiscard }) });
    await fireEvent.click(button("Accept all"));
    expect(onAcceptAll).toHaveBeenCalledTimes(1);
    await fireEvent.click(button("Reject all"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
  });

  it("wires A/S/B keys to the view axis (A/S toggle, B resets to Both)", async () => {
    const onView = vi.fn();
    const onToggleView = vi.fn();
    render(EntryRevisionReview, { props: baseProps({ onView, onToggleView }) });
    await fireEvent.keyDown(window, { key: "a" });
    expect(onToggleView).toHaveBeenLastCalledWith("now");
    await fireEvent.keyDown(window, { key: "s" });
    expect(onToggleView).toHaveBeenLastCalledWith("was");
    await fireEvent.keyDown(window, { key: "b" });
    expect(onView).toHaveBeenLastCalledWith("both");
  });

  it("ignores A/S/B keys typed into an input, and auto-repeat", async () => {
    const onToggleView = vi.fn();
    const onView = vi.fn();
    render(EntryRevisionReview, { props: baseProps({ onToggleView, onView }) });
    const input = document.createElement("input");
    document.body.appendChild(input);
    await fireEvent.keyDown(input, { key: "a" });
    await fireEvent.keyDown(window, { key: "a", repeat: true });
    expect(onToggleView).not.toHaveBeenCalled();
    expect(onView).not.toHaveBeenCalled();
    input.remove();
  });

  it("keeps the per-unit commit gesture: Close with no changes, Done with some", () => {
    const { unmount } = render(EntryRevisionReview, { props: baseProps({ hasChanges: false }) });
    expect(button("Close")).toBeInTheDocument();
    unmount();
    render(EntryRevisionReview, { props: baseProps({ hasChanges: true }) });
    expect(button("Done")).toBeInTheDocument();
  });
});
