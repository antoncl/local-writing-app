import { describe, it, expect, vi, beforeEach } from "vitest";

// The two governance adapters (#247 PR-3) — each maps the popover's ops onto its
// vocabulary's endpoints + refresh. Assistant tags are flat and scope-less, so
// their adapter reports `supportsScope: false` and refuses `updateScope`.
// Hoisted so the vi.mock factories (themselves hoisted above the imports) can
// close over these without the "cannot access before initialization" trap.
const { api, bumpTagVocabularyRevision, refreshKnownTags, refreshAssistantTags } = vi.hoisted(() => ({
  api: {
    getTagsOverview: vi.fn(async () => ({ tags: [{ name: "Alpha", count: 3 }, { name: "Beta", count: 1 }] })),
    setTagColor: vi.fn(async () => ({ tags: [] })),
    updateTagScope: vi.fn(async () => ({ tags: [] })),
    mergeTags: vi.fn(async () => ({ tags: [] })),
    getAssistantTagsOverview: vi.fn(async () => ({ tags: [{ name: "Editor", count: 2 }] })),
    setAssistantTagColor: vi.fn(async () => ({ tags: [] })),
    mergeAssistantTags: vi.fn(async () => ({ tags: [] })),
  },
  bumpTagVocabularyRevision: vi.fn(),
  refreshKnownTags: vi.fn(async () => {}),
  refreshAssistantTags: vi.fn(async () => {}),
}));
vi.mock("@/lib/api", () => ({ api }));
vi.mock("@/lib/stores/tags", () => ({ bumpTagVocabularyRevision, refreshKnownTags }));
vi.mock("@/lib/stores/assistantTags", () => ({ refreshAssistantTags }));

import { projectTagGovernance, assistantTagGovernance } from "@/lib/utils/tagGovernance";

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

describe("assistantTagGovernance", () => {
  it("does not support scope", () => {
    expect(assistantTagGovernance.supportsScope).toBe(false);
  });

  it("loads counts from the assistant overview", async () => {
    const counts = await assistantTagGovernance.loadCounts();
    expect(counts.get("editor")).toBe(2);
    expect(api.getAssistantTagsOverview).toHaveBeenCalled();
  });

  it("sets colour via the assistant endpoint then refreshes the assistant roster", async () => {
    await assistantTagGovernance.setColor("Editor", "teal");
    expect(api.setAssistantTagColor).toHaveBeenCalledWith("Editor", "teal");
    expect(refreshAssistantTags).toHaveBeenCalled();
  });

  it("merges via the assistant endpoint", async () => {
    await assistantTagGovernance.merge(["Beta"], "Editor");
    expect(api.mergeAssistantTags).toHaveBeenCalledWith(["Beta"], "Editor");
  });

  it("refuses updateScope (assistant tags have no scope)", async () => {
    await expect(assistantTagGovernance.updateScope("Editor", { sources: [] })).rejects.toThrow(/no scope/);
  });

  it("reconciles via the vocabulary-revision bump", async () => {
    await assistantTagGovernance.reconcile();
    expect(bumpTagVocabularyRevision).toHaveBeenCalled();
  });
});
