import { describe, expect, it } from "vitest";

import type { AncestorCandidate, ProjectChainLayer } from "@/lib/types";
import {
  declarationRows,
  declaredChain,
  inheritsNothing,
  toggledDeclaration,
} from "@/lib/utils/projectChain";

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

function layer(name: string, overrides: Partial<ProjectChainLayer> = {}): ProjectChainLayer {
  return {
    id: `layer-${name}`,
    label: name,
    path: `/writing/${name}`,
    is_root: false,
    ...overrides,
  };
}

// #432 moved the selection and the labelling into the backend walker, so what
// is left to test here is the one presentation rule. The cases this suite used
// to own — "a project that was never declared is not a crumb", "a declared
// folder that stopped being a project is not a crumb", "fall back to the folder
// name" — are now pinned in `backend/tests/test_declared_chain.py` against the
// implementation that actually decides them, rather than against a transcript
// of it.
describe("declaredChain", () => {
  it("renders the chain the backend resolved, in order, labels untouched", () => {
    const crumbs = declaredChain([
      layer("honorverse", { label: "The Honorverse" }),
      layer("honor-harrington", { label: "Honor Harrington" }),
      layer("on-basilisk-station", { label: "On Basilisk Station", is_root: true }),
    ]);

    expect(crumbs).toEqual([
      { path: "/writing/honorverse", label: "The Honorverse" },
      { path: "/writing/honor-harrington", label: "Honor Harrington" },
    ]);
  });

  it("drops the open project — the switcher renders it, not the path", () => {
    // Otherwise the bar shows the project twice, once as a crumb and once as
    // the switcher button beside it.
    expect(declaredChain([layer("obs", { is_root: true })])).toEqual([]);
  });

  it("passes a label through verbatim rather than second-guessing it", () => {
    // The walker's `_layer_label_for_folder` owns the fallbacks now, including
    // the "Base Folder" case this file used to contradict by labelling the
    // same folder by its directory name.
    const crumbs = declaredChain([layer("root", { label: "Base Folder" })]);

    expect(crumbs).toEqual([{ path: "/writing/root", label: "Base Folder" }]);
  });

  it("treats a missing chain as a flat project", () => {
    expect(declaredChain(undefined)).toEqual([]);
  });
});

describe("inheritsNothing", () => {
  it("is true for an open project that declares no ancestors", () => {
    // The chain always carries the open project itself, so "one layer, and it
    // is the root" is exactly the flat case the note states.
    expect(inheritsNothing([layer("obs", { is_root: true })])).toBe(true);
  });

  it("is false with no project open", () => {
    // Nothing to say "inherits from nothing" ABOUT — and the bar has no
    // switcher label to be mistaken for a crumb either.
    expect(inheritsNothing([])).toBe(false);
    expect(inheritsNothing(undefined)).toBe(false);
  });

  it("is false as soon as there is a path to draw", () => {
    expect(
      inheritsNothing([layer("honorverse"), layer("obs", { is_root: true })]),
    ).toBe(false);
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
