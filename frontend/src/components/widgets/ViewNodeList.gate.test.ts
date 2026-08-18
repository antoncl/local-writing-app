// @vitest-environment happy-dom
// #268: ViewNodeList mounts its tree-editing machinery only when a handler that
// needs it is wired. A read-only list (Backlinks, ReferencePicker, Chats, …)
// must NOT add a per-instance document mousedown listener — a metadata panel
// renders one ReferencePicker per ref field, so that dead weight adds up.
import { afterEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen } from "@/lib/test/component";
import Fixture from "./ViewNodeListGateFixture.svelte";

// ViewNodeList's own add-menu dismissal listener is a direct
// `document.addEventListener("mousedown", onDown)`. Svelte 5 ALSO registers one
// delegated `handle_event_propagation` mousedown listener at the mount root for
// its event system — that's framework chrome, present regardless of #268, so we
// exclude it and count only the component's own listener.
function ownMousedownListeners(spy: ReturnType<typeof vi.spyOn>): number {
  return spy.mock.calls.filter(
    ([type, fn]) => type === "mousedown" && !String(fn).includes("handle_event_propagation"),
  ).length;
}

afterEach(() => vi.restoreAllMocks());

describe("ViewNodeList — editing machinery gated on wired handlers (#268)", () => {
  it("a read-only list adds no document mousedown listener, and still renders rows", async () => {
    const spy = vi.spyOn(document, "addEventListener");
    render(Fixture, { props: { withAddMenu: false } });
    await tick();
    // The lightweight path still renders every row through the consumer snippet.
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    // …but wires none of the add-menu dismissal machinery.
    expect(ownMousedownListeners(spy)).toBe(0);
  });

  it("a list with an addMenu wires exactly one dismissal mousedown listener", async () => {
    const spy = vi.spyOn(document, "addEventListener");
    render(Fixture, { props: { withAddMenu: true } });
    await tick();
    expect(ownMousedownListeners(spy)).toBe(1);
  });
});
