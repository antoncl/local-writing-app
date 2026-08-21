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

  it("places the child beside its host without disturbing the side column's active tab (#1258)", () => {
    // Two tabs in the side column, the FIRST active — the classic case where the
    // old ensureVisible→dropOnEdge path homed the child here first and flipped
    // the active tab to the last one.
    workspaceLayout.ensureVisible("lore");
    workspaceLayout.ensureVisible("research");
    workspaceLayout.activate("lore");
    const sideId = workspaceLayout.groupOf("lore")!.id;
    expect(workspaceLayout.groupById(sideId)!.active).toBe("lore");

    openSubordinatePane("details:editor_host", "editor_host", vi.fn(), {
      beside: "editor_host",
      edge: "right",
    });

    // The side column never saw the child, so its active tab is untouched.
    expect(workspaceLayout.groupById(sideId)!.active).toBe("lore");
    expect(workspaceLayout.groupOf("details:editor_host")).not.toBeNull();
  });

  it("wraps the host in a fresh sub-split so closing the child restores its slot (#1258)", () => {
    // Walk the LIVE tree (not snapshot(), which strips ephemeral editor/subtab
    // ids): find the split that directly contains `groupId`.
    const parentSplitOf = (groupId: string) => {
      let found: { id: string; children: string[] } | null = null;
      const walk = (node: { kind: string; id: string; children?: { kind: string; id: string }[] }): void => {
        if (node.kind !== "split" || !node.children) return;
        if (node.children.some((c) => c.kind === "group" && c.id === groupId)) {
          found = { id: node.id, children: node.children.map((c) => c.id) };
        }
        node.children.forEach(walk);
      };
      walk(workspaceLayout.root as never);
      return found as { id: string; children: string[] } | null;
    };

    // editor_host is a TAB inside its group (g-editor); walk by that group's id.
    const hostGroupId = workspaceLayout.groupOf("editor_host")!.id;
    const hostParentBefore = parentSplitOf(hostGroupId)!;
    const groupsBefore = workspaceLayout.allGroups().length;

    openSubordinatePane("details:editor_host", "editor_host", vi.fn(), {
      beside: "editor_host",
      edge: "right",
    });

    // Host + child are the two children of ONE fresh sub-split — not siblings in
    // the pre-existing parent row (which would redistribute width on prune).
    const childGroupId = workspaceLayout.groupOf("details:editor_host")!.id;
    const wrap = parentSplitOf(hostGroupId)!;
    const childWrap = parentSplitOf(childGroupId)!;
    expect(wrap.id).toBe(childWrap.id);
    expect(wrap.id).not.toBe(hostParentBefore.id);
    expect(wrap.children).toHaveLength(2);

    // Closing the child collapses the wrap, returning the host to its slot — no
    // leftover group, structure back to where it started.
    closeSubordinatePane("details:editor_host");
    expect(workspaceLayout.isPlaced("details:editor_host")).toBe(false);
    expect(workspaceLayout.isPlaced("editor_host")).toBe(true);
    expect(workspaceLayout.allGroups().length).toBe(groupsBefore);
    expect(parentSplitOf(hostGroupId)!.id).toBe(hostParentBefore.id);
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
