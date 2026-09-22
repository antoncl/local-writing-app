// @vitest-environment happy-dom
// ADR-0090 §4 — Propose from a review item: fetch the pre-filled change
// message, open the conversation with the DEPENDENT stamped as subject,
// record the hand-off `entryProposal`'s commit reads, and hold the message
// for that chat's composer (never sent) — the chat pane is created and
// remounted by the same gesture, so the hold is chat-keyed, not pane-keyed.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { todoActions } from "./todoActions.svelte";
import { chatSessions } from "./chatSessions.svelte";
import { composerPrefills } from "./composerPrefill.svelte";
import { reviewProposals } from "./reviewProposals.svelte";
import type { PromptEntrySummary, TodoItem } from "@/lib/types";

const PROMPT = { id: "p1", title: "Revise entry" } as unknown as PromptEntrySummary;

function reviewItem(overrides: Partial<TodoItem> = {}): TodoItem {
  return {
    id: "todo_1",
    text: "Follow up on Marek Vell's change",
    status: "open",
    scope: "node",
    node_id: "lore_ilse",
    source: { node_id: "lore_marek", snapshot_id: "snap_1", reason: "references_source", marker_id: "" },
    ...overrides,
  };
}

describe("todoActions.proposeFromReviewItem (ADR-0090 §4)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(api, "changeMessage").mockResolvedValue({
      source_id: "lore_marek",
      baseline_snapshot_id: "snap_1",
      text: "Marek Vell changed…",
    });
    vi.spyOn(chatSessions, "openChatFromPromptEntry").mockResolvedValue("chat_new");
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    reviewProposals.take("lore_ilse");
    composerPrefills.clear("chat_new");
  });

  it("fetches the change message with the item's source and baseline", async () => {
    await todoActions.proposeFromReviewItem(reviewItem(), PROMPT, {}, { subjectTitle: "Ilse" });
    expect(api.changeMessage).toHaveBeenCalledWith("lore_marek", "snap_1");
  });

  it("sends an empty baseline (whole entry) when the item's source has none", async () => {
    const item = reviewItem({
      source: { node_id: "lore_marek", snapshot_id: "", reason: "mentions_source", marker_id: "" },
    });
    await todoActions.proposeFromReviewItem(item, PROMPT, {}, { subjectTitle: "Ilse" });
    expect(api.changeMessage).toHaveBeenCalledWith("lore_marek", "");
  });

  it("records the review-item hand-off, keyed on the dependent", async () => {
    await todoActions.proposeFromReviewItem(reviewItem(), PROMPT, {}, { subjectTitle: "Ilse" });
    expect(reviewProposals.peek("lore_ilse")).toBe("todo_1");
  });

  it("opens the conversation with the dependent stamped as the subject", async () => {
    const seeded = { entry: "lore_ilse" };
    await todoActions.proposeFromReviewItem(reviewItem(), PROMPT, seeded, { subjectTitle: "Ilse" });
    expect(chatSessions.openChatFromPromptEntry).toHaveBeenCalledWith(PROMPT, seeded, null, {
      subject: "lore_ilse",
      subjectTitle: "Ilse",
    });
  });

  it("holds the message for the new chat's composer, keyed by chat id", async () => {
    await todoActions.proposeFromReviewItem(reviewItem(), PROMPT, {}, { subjectTitle: "Ilse" });
    expect(composerPrefills.peek("chat_new")).toBe("Marek Vell changed…");
    // Editing or sending releases the hold; a load never does.
    composerPrefills.clear("chat_new");
    expect(composerPrefills.peek("chat_new")).toBeNull();
  });

  it("records no hand-off when the conversation fails to open", async () => {
    vi.mocked(chatSessions.openChatFromPromptEntry).mockRejectedValueOnce(new Error("no"));
    await todoActions.proposeFromReviewItem(reviewItem(), PROMPT, {}, { subjectTitle: "Ilse" }).catch(() => {});
    expect(reviewProposals.peek("lore_ilse")).toBeNull();
    expect(composerPrefills.peek("chat_new")).toBeNull();
  });

  it("is a no-op for a scene item (no node_id — scenes have no Propose)", async () => {
    const item = reviewItem({ scope: "scene", node_id: undefined, scene_id: "scene_1" });
    await todoActions.proposeFromReviewItem(item, PROMPT, {}, { subjectTitle: "Chapter Five" });
    expect(api.changeMessage).not.toHaveBeenCalled();
    expect(chatSessions.openChatFromPromptEntry).not.toHaveBeenCalled();
  });
});
