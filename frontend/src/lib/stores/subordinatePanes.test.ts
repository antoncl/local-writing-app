// Subordinate-pane registry — a child pane (the lore Brainstorm chat, the
// "Edit type…" pane) auto-closes when its master pane closes. The invariants:
// closing a master fires every child's own closer and drops the links, other
// masters are untouched, unregister cancels a pending auto-close, and a fresh
// register re-homes a singleton child to a new owner.
import { describe, expect, it, vi } from "vitest";
import { subordinatePanes } from "./subordinatePanes";

describe("subordinatePanes registry", () => {
  it("closes every child of a master and drops the links", () => {
    const closeA = vi.fn();
    const closeB = vi.fn();
    subordinatePanes.register("child_a", "master_1", closeA);
    subordinatePanes.register("child_b", "master_1", closeB);

    subordinatePanes.closeChildrenOf("master_1");
    expect(closeA).toHaveBeenCalledTimes(1);
    expect(closeB).toHaveBeenCalledTimes(1);

    // Links were dropped as they fired — a second master-close is a no-op.
    subordinatePanes.closeChildrenOf("master_1");
    expect(closeA).toHaveBeenCalledTimes(1);
    expect(closeB).toHaveBeenCalledTimes(1);
  });

  it("leaves another master's children untouched", () => {
    const closeMine = vi.fn();
    const closeTheirs = vi.fn();
    subordinatePanes.register("child_mine", "master_x", closeMine);
    subordinatePanes.register("child_theirs", "master_y", closeTheirs);

    subordinatePanes.closeChildrenOf("master_x");
    expect(closeMine).toHaveBeenCalledTimes(1);
    expect(closeTheirs).not.toHaveBeenCalled();

    subordinatePanes.unregister("child_theirs");
  });

  it("unregister cancels a pending auto-close (child closed on its own)", () => {
    const close = vi.fn();
    subordinatePanes.register("child_c", "master_2", close);
    subordinatePanes.unregister("child_c");

    subordinatePanes.closeChildrenOf("master_2");
    expect(close).not.toHaveBeenCalled();
  });

  it("re-registering re-homes a singleton child to a new owner", () => {
    // The schema_type pane is a singleton reopened from different editors.
    const close = vi.fn();
    subordinatePanes.register("schema_type", "pane_a", close);
    subordinatePanes.register("schema_type", "pane_b", close);

    // The old owner closing must not touch it — it now belongs to pane_b.
    subordinatePanes.closeChildrenOf("pane_a");
    expect(close).not.toHaveBeenCalled();

    subordinatePanes.closeChildrenOf("pane_b");
    expect(close).toHaveBeenCalledTimes(1);
  });
});
