// @vitest-environment happy-dom
// #417 slice 4: the breadcrumb doubles as the inheritance-state display
// (reversing #431). This pins the RENDER contract the `projectChain` unit test
// can't see — that `available` ancestors draw dimmed-but-clickable, `stale` ones
// draw as non-navigable markers, both announce their state to assistive tech,
// and the declaration editor's remedy sits on the populated bar (the #642 lesson
// + the review findings: assert the negative halves, not just the happy path).
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

const CHAIN = [
  layer("universe", { label: "Universe" }), // declared
  layer("series", { label: "Series", inherited: false }), // available
  layer("gone", { label: "Gone", is_project: false, inherited: true }), // stale
  layer("book", { label: "Book", is_root: true }), // the open project (leaf)
];

describe("ProjectBreadcrumb — inheritance state (#417 slice 4)", () => {
  it("draws declared solid, available dimmed+clickable, stale inert, each state announced", async () => {
    const onOpen = vi.fn();
    render(ProjectBreadcrumb, { props: { chain: CHAIN, onOpen } });

    // declared: a solid button, NOT dimmed, no state suffix on its name.
    const declared = screen.getByRole("button", { name: "Universe" });
    expect(declared.classList.contains("available")).toBe(false);

    // available: dimmed button whose accessible name announces "not inherited".
    const available = screen.getByRole("button", { name: "Series — not inherited" });
    expect(available.classList.contains("available")).toBe(true);

    // stale: NOT a button (nothing to open), a struck marker whose text
    // announces the broken state (getNodeText is the span's own "Gone").
    expect(screen.queryByRole("button", { name: /Gone/ })).toBeNull();
    const stale = screen.getByText("Gone");
    expect(stale.classList.contains("stale")).toBe(true);
    expect(stale.textContent).toContain("no longer a project");

    // the open project is the switcher's job, never a crumb.
    expect(screen.queryByText("Book")).toBeNull();

    // clicking a real project (dimmed or not) opens it; the stale marker can't.
    await fireEvent.click(available);
    await fireEvent.click(declared);
    await fireEvent.click(stale);
    expect(onOpen.mock.calls).toEqual([["/w/series"], ["/w/universe"]]);
  });

  it("puts the declaration-editor remedy on the populated bar when canDeclare", async () => {
    const onSetUpInheritance = vi.fn();
    render(ProjectBreadcrumb, {
      props: { chain: CHAIN, canDeclare: true, onSetUpInheritance },
    });

    const edit = screen.getByRole("button", {
      name: "Edit what this project inherits from",
    });
    await fireEvent.click(edit);
    expect(onSetUpInheritance).toHaveBeenCalledTimes(1);
  });

  it("shows a remedy-less note for a flat project with nothing to declare", () => {
    // Only the leaf → crumbs empty → the note. canDeclare is structurally false
    // here (a toggleable ancestor would have produced a crumb), so the old
    // \"set up…\" remedy is correctly absent — it lives on the populated bar now.
    render(ProjectBreadcrumb, {
      props: { chain: [layer("book", { is_root: true })], canDeclare: false },
    });
    expect(screen.getByText("Inherits from nothing")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
