import { describe, expect, it, vi } from "vitest";
import { resolveCommitSubject, type CommitSubjectRosters } from "./commitSubject";
import type { StructureDocument } from "@/lib/types";

const STRUCTURE = {
  root: { id: "root", title: "Book", children: [{ id: "n1", scene_id: "scene_1", title: "Opening", children: [] }] },
} as unknown as StructureDocument;

const ROSTERS: CommitSubjectRosters = {
  lore: [{ id: "lore_1", title: "Elara" }],
  plotlines: [{ id: "plot_line", title: "The Girl in the Ghost" }],
  cards: [{ id: "plot_card", title: "The Toll" }],
  structure: STRUCTURE,
  schema: null,
};

function openers() {
  return {
    openLore: vi.fn(async () => {}),
    openPlotline: vi.fn(async () => {}),
    openPlotCard: vi.fn(async () => {}),
    openScene: vi.fn(async () => {}),
  };
}

describe("resolveCommitSubject (#2246)", () => {
  it.each([
    ["lore_1", "Elara", "openLore"],
    ["plot_line", "The Girl in the Ghost", "openPlotline"],
    ["plot_card", "The Toll", "openPlotCard"],
    ["scene_1", "Opening", "openScene"],
  ] as const)("%s resolves to its title and its document opener", async (id, title, opener) => {
    const o = openers();
    const subject = resolveCommitSubject(id, ROSTERS, o);
    expect(subject?.title).toBe(title);
    await subject!.open();
    expect(o[opener]).toHaveBeenCalledWith(id);
    for (const [name, fn] of Object.entries(o)) if (name !== opener) expect(fn).not.toHaveBeenCalled();
  });

  it("an id in no roster (e.g. a character arc) resolves to null", () => {
    expect(resolveCommitSubject("plot_arc", ROSTERS, openers())).toBeNull();
  });
});
