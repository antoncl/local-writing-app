// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Editor } from "@tiptap/core";
import { PendingReveals } from "./pendingReveals";
import { revealMutationPill } from "./mutationNodes";
import { firstMentionReveal, type SearchReveal } from "./searchMatchHighlight";

vi.mock("./mutationNodes", () => ({ revealMutationPill: vi.fn() }));
vi.mock("./searchMatchHighlight", () => ({ firstMentionReveal: vi.fn() }));

const reveal: SearchReveal = { query: "alice", matchCase: false, wholeWord: false, excerpt: "alice", ordinal: 0 };

function makeEditor(revealSearchMatch = vi.fn()) {
  return { commands: { revealSearchMatch }, state: { doc: {} } } as unknown as Editor;
}

describe("PendingReveals", () => {
  beforeEach(() => vi.clearAllMocks());

  it("drops a queued search reveal for another scene on apply", () => {
    const reveals = new PendingReveals();
    const revealSearchMatch = vi.fn();
    reveals.queueSearch("scene_a", reveal);

    reveals.apply("scene_b", makeEditor(revealSearchMatch), document.createElement("div"));

    expect(revealSearchMatch).not.toHaveBeenCalled();
  });

  it("a matching search reveal applies once and is cleared", () => {
    const reveals = new PendingReveals();
    const revealSearchMatch = vi.fn();
    const editor = makeEditor(revealSearchMatch);
    reveals.queueSearch("scene_a", reveal);

    reveals.apply("scene_a", editor, document.createElement("div"));
    reveals.apply("scene_a", editor, document.createElement("div"));

    expect(revealSearchMatch).toHaveBeenCalledTimes(1);
    expect(revealSearchMatch).toHaveBeenCalledWith(reveal);
  });

  it("a marker reveal calls the pill reveal", () => {
    const reveals = new PendingReveals();
    const element = document.createElement("div");
    reveals.queueReview("scene_a", { markerId: "mut_1" });

    reveals.apply("scene_a", makeEditor(), element);

    expect(revealMutationPill).toHaveBeenCalledWith(element, "mut_1");
  });

  it("a names reveal that finds nothing is a no-op", () => {
    vi.mocked(firstMentionReveal).mockReturnValue(null);
    const reveals = new PendingReveals();
    const revealSearchMatch = vi.fn();
    reveals.queueReview("scene_a", { names: ["Alice"] });

    reveals.apply("scene_a", makeEditor(revealSearchMatch), document.createElement("div"));

    expect(revealSearchMatch).not.toHaveBeenCalled();
  });

  it("a names reveal that finds a match reveals it and is cleared", () => {
    vi.mocked(firstMentionReveal).mockReturnValue(reveal);
    const reveals = new PendingReveals();
    const revealSearchMatch = vi.fn();
    const editor = makeEditor(revealSearchMatch);
    reveals.queueReview("scene_a", { names: ["Alice"] });

    reveals.apply("scene_a", editor, document.createElement("div"));
    reveals.apply("scene_a", editor, document.createElement("div"));

    expect(revealSearchMatch).toHaveBeenCalledTimes(1);
    expect(revealSearchMatch).toHaveBeenCalledWith(reveal);
  });

  it("clear() drops both queues without applying", () => {
    const reveals = new PendingReveals();
    const revealSearchMatch = vi.fn();
    reveals.queueSearch("scene_a", reveal);
    reveals.queueReview("scene_a", { markerId: "mut_1" });

    reveals.clear();
    reveals.apply("scene_a", makeEditor(revealSearchMatch), document.createElement("div"));

    expect(revealSearchMatch).not.toHaveBeenCalled();
    expect(revealMutationPill).not.toHaveBeenCalled();
  });
});
