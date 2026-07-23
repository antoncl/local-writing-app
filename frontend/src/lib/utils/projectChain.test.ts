import { describe, expect, it } from "vitest";

import type { AncestorCandidate } from "@/lib/types";
import { declarationRows, declaredChain, toggledDeclaration } from "@/lib/utils/projectChain";

function ancestor(name: string, overrides: Partial<AncestorCandidate> = {}): AncestorCandidate {
  return {
    path: `/writing/${name}`,
    name,
    is_project: false,
    inherited: false,
    title: null,
    ...overrides,
  };
}

describe("declaredChain", () => {
  it("keeps only the declared layers, in the order the backend reports", () => {
    const crumbs = declaredChain([
      ancestor("writing"),
      ancestor("honorverse", { is_project: true, inherited: true, title: "The Honorverse" }),
      ancestor("honor-harrington", { is_project: true, inherited: true, title: "Honor Harrington" }),
    ]);

    expect(crumbs).toEqual([
      { path: "/writing/honorverse", label: "The Honorverse" },
      { path: "/writing/honor-harrington", label: "Honor Harrington" },
    ]);
  });

  it("drops an ancestor that is a project but was never declared", () => {
    // #318's wizard offers these; the breadcrumb must not imply they are part
    // of what is being built here.
    const crumbs = declaredChain([ancestor("honorverse", { is_project: true })]);

    expect(crumbs).toEqual([]);
  });

  it("drops a declared entry that is no longer a project", () => {
    // The backend keeps the declaration and warns rather than dropping it, so
    // the row arrives with `inherited` set and nothing to show or open.
    const crumbs = declaredChain([ancestor("honorverse", { inherited: true })]);

    expect(crumbs).toEqual([]);
  });

  it("falls back to the folder name when a declared project has no title", () => {
    // The only null-title shape the backend can actually emit for a rendered
    // crumb: a project whose manifest has no `title`, or whose manifest could
    // not be read. `_project_title` strips and returns None, so null — not a
    // blank string — is what arrives, and nothing else in this suite exercises
    // the optional chain on a row that survives the filter.
    const crumbs = declaredChain([
      ancestor("honorverse", { is_project: true, inherited: true, title: null }),
    ]);

    expect(crumbs).toEqual([{ path: "/writing/honorverse", label: "honorverse" }]);
  });

  it("falls back when the title is present but blank", () => {
    const crumbs = declaredChain([
      ancestor("honorverse", { is_project: true, inherited: true, title: "   " }),
    ]);

    expect(crumbs).toEqual([{ path: "/writing/honorverse", label: "honorverse" }]);
  });

  it("treats a missing enumeration as a flat project", () => {
    expect(declaredChain(undefined)).toEqual([]);
  });
});

describe("declarationRows", () => {
  it("keeps every enumerated folder, in the backend's order", () => {
    // The breadcrumb's opposite: the editor exists to offer what the
    // breadcrumb hides, so nothing here is filtered out.
    const rows = declarationRows([
      ancestor("writing"),
      ancestor("honorverse", { is_project: true, inherited: true, title: "The Honorverse" }),
      ancestor("honor-harrington", { is_project: true, title: "Honor Harrington" }),
    ]);

    expect(rows.map((row) => [row.label, row.state, row.checked, row.toggleable])).toEqual([
      ["writing", "folder", false, false],
      ["The Honorverse", "declared", true, true],
      ["Honor Harrington", "available", false, true],
    ]);
  });

  it("shows the folder name only when the title is not already it", () => {
    const [named, unnamed] = declarationRows([
      ancestor("honorverse", { is_project: true, title: "The Honorverse" }),
      ancestor("honor-harrington", { is_project: true, title: "honor-harrington" }),
    ]);

    expect(named.detail).toBe("honorverse");
    expect(unnamed.detail).toBeNull();
  });

  it("flags a declared ancestor that has stopped being a project", () => {
    // `declared_ancestor_warnings` keeps this one rather than dropping it, so
    // the row must say why a ticked box is contributing nothing.
    const [row] = declarationRows([ancestor("honorverse", { inherited: true })]);

    expect(row.state).toBe("stale");
    expect(row.checked).toBe(true);
    // Unticking is the repair, so this one row IS toggleable despite not
    // being a project — the disabled state would trap the author in it.
    expect(row.toggleable).toBe(true);
    expect(row.detail).toContain("no longer a project");
  });

  it("disables an organisational folder and says why", () => {
    const [row] = declarationRows([ancestor("writing")]);

    expect(row.state).toBe("folder");
    expect(row.toggleable).toBe(false);
    expect(row.detail).toContain("Not a project");
  });

  it("treats a missing enumeration as no rows", () => {
    expect(declarationRows(undefined)).toEqual([]);
  });
});

describe("toggledDeclaration", () => {
  const chain = [
    ancestor("writing"),
    ancestor("honorverse", { is_project: true, inherited: true }),
    ancestor("honor-harrington", { is_project: true }),
  ];

  it("adds an available ancestor, keeping the enumeration's order", () => {
    // Outermost-first regardless of tick order: the list is derived from the
    // walk, not appended to.
    expect(toggledDeclaration(chain, "/writing/honor-harrington")).toEqual([
      "/writing/honorverse",
      "/writing/honor-harrington",
    ]);
  });

  it("removes a declared ancestor", () => {
    expect(toggledDeclaration(chain, "/writing/honorverse")).toEqual([]);
  });

  it("leaves a valid flat project when the last layer is unticked", () => {
    // `[]` is a deliberate flat project, distinct from an absent key only on
    // the create request — here it is the cleared declaration.
    expect(
      toggledDeclaration([ancestor("honorverse", { is_project: true, inherited: true })], "/writing/honorverse"),
    ).toEqual([]);
  });

  it("declares gaps as written — a grandparent without its parent", () => {
    // Legal upstream (`_project_layer_folders` is a membership test per
    // candidate), so the editor must not quietly fill the gap in.
    const rows = [
      ancestor("honorverse", { is_project: true }),
      ancestor("honor-harrington", { is_project: true }),
    ];

    expect(toggledDeclaration(rows, "/writing/honorverse")).toEqual(["/writing/honorverse"]);
  });
});
