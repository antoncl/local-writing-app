// @vitest-environment happy-dom
// #417 slice 4: the breadcrumb now doubles as the inheritance-state display
// (reversing #431). This pins the RENDER contract the `projectChain` unit test
// can't see — that `available` ancestors draw dimmed-but-clickable, `stale`
// ones draw as non-navigable markers, and navigation still fires only for real
// projects (the #642 lesson: a display change needs a mount assertion, not just
// an API-shape check).
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import ProjectBreadcrumb from "./ProjectBreadcrumb.svelte";
import type { ProjectChainLayer } from "@/lib/types";

function layer(name: string, overrides: Partial<ProjectChainLayer> = {}): ProjectChainLayer {
  return {
    id: `l-${name}`,
    label: name,
    path: `/w/${name}`,
    is_root: false,
    is_project: true,
    inherited: true,
    ...overrides,
  };
}

describe("ProjectBreadcrumb — inheritance state (#417 slice 4)", () => {
  it("draws declared solid, available dimmed-but-clickable, stale as a non-navigable marker", async () => {
    const onOpen = vi.fn();
    render(ProjectBreadcrumb, {
      props: {
        chain: [
          layer("universe", { label: "Universe" }), // declared
          layer("series", { label: "Series", inherited: false }), // available
          layer("gone", { label: "Gone", is_project: false, inherited: true }), // stale
          layer("book", { label: "Book", is_root: true }), // the open project (leaf)
        ],
        onOpen,
      },
    });

    // declared + available are navigable buttons; the available one is dimmed.
    const declared = screen.getByRole("button", { name: "Universe" });
    const available = screen.getByRole("button", { name: "Series" });
    expect(available.classList.contains("available")).toBe(true);

    // stale is NOT a button — nothing to open — but is still shown, flagged.
    expect(screen.queryByRole("button", { name: "Gone" })).toBeNull();
    expect(screen.getByText("Gone").classList.contains("stale")).toBe(true);

    // the open project is the switcher's job, never a crumb.
    expect(screen.queryByText("Book")).toBeNull();

    // clicking a real project (dimmed or not) opens it; the stale marker can't.
    await fireEvent.click(available);
    expect(onOpen).toHaveBeenCalledWith("/w/series");
    await fireEvent.click(declared);
    expect(onOpen).toHaveBeenCalledWith("/w/universe");
    expect(onOpen).toHaveBeenCalledTimes(2);
  });
});
