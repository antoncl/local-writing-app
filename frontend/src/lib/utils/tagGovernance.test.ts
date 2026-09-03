import { describe, it, expect, vi, beforeEach } from "vitest";

// The project-tag governance adapter (#247 PR-3) — maps the popover's ops onto
// the project vocabulary's endpoints + refresh. The assistant-tag adapter
// retired with the legacy `assistant-tags.yaml` registry (ADR-0082 slice 2b).
// Hoisted so the vi.mock factories (themselves hoisted above the imports) can
// close over these without the "cannot access before initialization" trap.
const { api, bumpTagVocabularyRevision, refreshKnownTags } = vi.hoisted(() => ({
  api: {
    getTagsOverview: vi.fn(async () => ({ tags: [{ name: "Alpha", count: 3 }, { name: "Beta", count: 1 }] })),
    setTagColor: vi.fn(async () => ({ tags: [] })),
    updateTagScope: vi.fn(async () => ({ tags: [] })),
    mergeTags: vi.fn(async () => ({ tags: [] })),
  },
  bumpTagVocabularyRevision: vi.fn(),
  refreshKnownTags: vi.fn(async () => {}),
}));
vi.mock("@/lib/api", () => ({ api }));
vi.mock("@/lib/stores/tags", () => ({ bumpTagVocabularyRevision, refreshKnownTags }));

import { projectTagGovernance } from "@/lib/utils/tagGovernance";

beforeEach(() => vi.clearAllMocks());

describe("projectTagGovernance", () => {
  it("supports scope", () => {
    expect(projectTagGovernance.supportsScope).toBe(true);
  });

  it("loads counts keyed lowercase", async () => {
    const counts = await projectTagGovernance.loadCounts();
    expect(counts.get("alpha")).toBe(3);
    expect(counts.get("beta")).toBe(1);
  });

  it("sets colour then refreshes only the roster", async () => {
    await projectTagGovernance.setColor("Alpha", "rose");
    expect(api.setTagColor).toHaveBeenCalledWith("Alpha", "rose");
    expect(refreshKnownTags).toHaveBeenCalled();
    expect(bumpTagVocabularyRevision).not.toHaveBeenCalled();
  });

  it("routes scope + merge to the project endpoints", async () => {
    await projectTagGovernance.updateScope("Alpha", { sources: [] });
    expect(api.updateTagScope).toHaveBeenCalledWith("Alpha", { sources: [] });
    await projectTagGovernance.merge(["Beta"], "Alpha");
    expect(api.mergeTags).toHaveBeenCalledWith(["Beta"], "Alpha");
  });

  it("reconciles via the vocabulary-revision bump", async () => {
    await projectTagGovernance.reconcile();
    expect(bumpTagVocabularyRevision).toHaveBeenCalled();
  });
});
