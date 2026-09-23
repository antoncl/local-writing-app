import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ api: { aiPreview: vi.fn() } }));
import { api } from "@/lib/api";
import { lockPromptTemplate } from "./promptTemplateLock";
import type { PromptEntrySummary } from "@/lib/types";

const aiPreview = vi.mocked(api.aiPreview);

const entry = (body = "template body", inputs: PromptEntrySummary["inputs"] = []): PromptEntrySummary =>
  ({ id: "p1", title: "P", body, inputs }) as PromptEntrySummary;

describe("lockPromptTemplate (#2129)", () => {
  beforeEach(() => {
    aiPreview.mockReset();
  });

  it("on success: joins system blocks, flattens block text, and splits initial turns", async () => {
    aiPreview.mockResolvedValue({
      messages: [
        { role: "system", blocks: [{ text: "Be terse." }, { text: " Stay in character." }] },
        { role: "system", blocks: [{ text: "Second system message." }] },
        { role: "user", blocks: [{ text: "Hi " }, { text: "there." }] },
        { role: "assistant", blocks: [{ text: "Hello!" }] },
      ],
      warnings: [],
      char_count: 0,
      rendered: true,
      lore_enabled: true,
      used_node_ids: ["lore_1"],
      used_node_hints: { lore_1: "stable" },
      used_snapshots: [{ entry_id: "lore_1", snapshot_id: "snap_1" }],
      field_contract_stored: [{ id: "bio" }],
    } as never);

    const result = await lockPromptTemplate(entry(), { subject: "chat_1", inputs: {} });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.lock.systemPrompt).toBe("Be terse. Stay in character.\n\nSecond system message.");
    expect(result.lock.loreEnabled).toBe(true);
    expect(result.lock.usedNodeIds).toEqual(["lore_1"]);
    expect(result.lock.usedNodeHints).toEqual({ lore_1: "stable" });
    expect(result.lock.usedSnapshots).toEqual([{ entry_id: "lore_1", snapshot_id: "snap_1" }]);
    expect(result.lock.fieldContractStored).toEqual([{ id: "bio" }]);
    expect(result.lock.initialTurns).toEqual([
      { role: "user", content: "Hi there." },
      { role: "assistant", content: "Hello!" },
    ]);
  });

  it("defaults lore_enabled to false and the arrays/records to empty when absent", async () => {
    aiPreview.mockResolvedValue({
      messages: [],
      warnings: [],
      char_count: 0,
      rendered: true,
    } as never);
    const result = await lockPromptTemplate(entry(), { subject: "", inputs: {} });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.lock.loreEnabled).toBe(false);
    expect(result.lock.usedNodeIds).toEqual([]);
    expect(result.lock.usedNodeHints).toEqual({});
    expect(result.lock.usedSnapshots).toEqual([]);
    expect(result.lock.fieldContractStored).toEqual([]);
    expect(result.lock.initialTurns).toEqual([]);
    expect(result.lock.systemPrompt).toBe("");
  });

  it("a preview.error returns {ok:false} with the render-error message", async () => {
    aiPreview.mockResolvedValue({
      messages: [],
      warnings: [],
      char_count: 0,
      rendered: false,
      error: { message: "undefined variable 'foo'", kind: "undefined" },
    } as never);
    const result = await lockPromptTemplate(entry(), { subject: "", inputs: {} });
    expect(result).toEqual({
      ok: false,
      error: "Couldn't render prompt template: undefined variable 'foo'",
    });
  });

  it("a thrown error returns {ok:false} with its message", async () => {
    aiPreview.mockRejectedValue(new Error("network down"));
    const result = await lockPromptTemplate(entry(), { subject: "", inputs: {} });
    expect(result).toEqual({
      ok: false,
      error: "Couldn't render prompt template: network down",
    });
  });

  it("the request carries target_scene_id '', commit false, the subject, and the resolution scene id", async () => {
    aiPreview.mockResolvedValue({ messages: [], warnings: [], char_count: 0, rendered: true } as never);
    const scoped = entry("t", [{ name: "as_of", type: "scene_ref" } as never]);
    await lockPromptTemplate(scoped, { subject: "chat_9", inputs: { as_of: "scene_42" } });
    expect(aiPreview).toHaveBeenCalledWith(
      expect.objectContaining({
        template_source: "t",
        target_scene_id: "",
        commit: false,
        subject: "chat_9",
        resolution_scene_id: "scene_42",
        inputs: { as_of: "scene_42" },
      }),
    );
  });
});
