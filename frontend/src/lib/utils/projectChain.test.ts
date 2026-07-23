import { describe, expect, it } from "vitest";

import type { AncestorCandidate } from "@/lib/types";
import { declaredChain } from "@/lib/utils/projectChain";

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
