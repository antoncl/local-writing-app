// Covers the subordinate-pane choreography extracted from CodeBodyView's detach
// and SchemaPanes' schema_type editor (ADR-0062 S2 review, finding #2/#4): place
// the pane, tie its lifetime to a host, strip it on close.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { subordinatePanes } from "@/lib/stores/subordinatePanes";
import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
import { closeSubordinatePane, openSubordinatePane } from "./subordinatePane";

describe("subordinate pane helpers (ADR-0062 S2)", () => {
  beforeEach(() => {
    workspaceLayout.reset();
    subordinatePanes.clear();
    workspaceLayout.ensureVisible("editor_host"); // a placed editor pane to own the child
  });

  it("places the pane beside its host in a separate group and links it subordinate", () => {
    const close = vi.fn();
    openSubordinatePane("preview:editor_host", "editor_host", close, {
      beside: "editor_host",
      edge: "right",
    });

    expect(workspaceLayout.isPlaced("preview:editor_host")).toBe(true);
    // dropOnEdge tiled it into its OWN group, not the editor's.
    const childGroup = workspaceLayout.groupOf("preview:editor_host");
    const hostGroup = workspaceLayout.groupOf("editor_host");
    expect(childGroup).not.toBeNull();
    expect(childGroup!.id).not.toBe(hostGroup!.id);

    // Subordinate: closing the host cascades to the child's closer.
    subordinatePanes.closeChildrenOf("editor_host");
    expect(close).toHaveBeenCalledOnce();
  });

  it("closeSubordinatePane removes the pane, drops the link, and is idempotent", () => {
    const close = vi.fn();
    openSubordinatePane("preview:editor_host", "editor_host", close, { beside: "editor_host" });

    closeSubordinatePane("preview:editor_host");
    expect(workspaceLayout.isPlaced("preview:editor_host")).toBe(false);

    // Link is gone — a later host teardown no longer calls the (stale) closer.
    subordinatePanes.closeChildrenOf("editor_host");
    expect(close).not.toHaveBeenCalled();

    // Calling it again on an already-removed pane is a no-op, not a throw.
    expect(() => closeSubordinatePane("preview:editor_host")).not.toThrow();
  });

  it("with a null host, places the pane but registers no subordinate link", () => {
    const close = vi.fn();
    openSubordinatePane("preview:orphan", null, close);

    expect(workspaceLayout.isPlaced("preview:orphan")).toBe(true);
    // No host means the tearDown cascade never reaches it.
    subordinatePanes.closeChildrenOf("editor_host");
    expect(close).not.toHaveBeenCalled();
  });

  it("a null host clears a stale link from a prior owner (re-open ownerless)", () => {
    const close = vi.fn();
    openSubordinatePane("preview:editor_host", "editor_host", close, { beside: "editor_host" });
    // Re-open the same pane with no owner — the prior link must be dropped.
    openSubordinatePane("preview:editor_host", null, close);

    subordinatePanes.closeChildrenOf("editor_host");
    expect(close).not.toHaveBeenCalled();
  });
});
