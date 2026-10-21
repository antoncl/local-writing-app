// @vitest-environment happy-dom
// #2593: the inputs dialog's "Default (…)" option and its estimate must name the
// assistant the run will actually use — the prompt's tag-scoped one — not the
// roster's topmost. Rendered with no declared inputs so no PromptInputField
// (TipTap) mounts (#642).
import { afterEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen } from "@/lib/test/component";
import { api } from "@/lib/api";
import PromptInvocationDialog from "./PromptInvocationDialog.svelte";
import type { AssistantEntrySummary, PromptEntrySummary } from "@/lib/types";

const ROSTER = [
  { id: "main", title: "Main", metadata: {}, computed_metadata: { listed: "listed" } },
  { id: "gemma", title: "Gemma4", metadata: { assistant_tags: ["tag_gemma"] }, computed_metadata: { listed: "listed" } },
] as unknown as AssistantEntrySummary[];

const prompt = (metadata: Record<string, unknown>) =>
  ({ id: "prompt_1", title: "Rephrase", body: "x", inputs: [], metadata }) as unknown as PromptEntrySummary;

afterEach(() => vi.restoreAllMocks());

async function openWith(entry: PromptEntrySummary) {
  const aiPreview = vi.spyOn(api, "aiPreview").mockResolvedValue({ messages: [], warnings: [] } as never);
  const { component } = render(PromptInvocationDialog, {
    props: { assistantEntries: ROSTER, defaultAssistantId: "main" },
  });
  (component as unknown as { open: (p: { entry: PromptEntrySummary }) => void }).open({ entry });
  await tick();
  return aiPreview;
}

describe("PromptInvocationDialog — the prompt's assistant (#2593)", () => {
  it("a tag-scoped prompt's Default names, and estimates on, the matching assistant", async () => {
    const aiPreview = await openWith(prompt({ assistant_tags: ["tag_gemma"] }));
    expect(screen.getByText("Default (Gemma4)")).toBeTruthy();
    expect(aiPreview).toHaveBeenLastCalledWith(expect.objectContaining({ assistant_id: "gemma" }));
  });

  it("an unscoped prompt's Default is the roster's topmost, left to the backend", async () => {
    const aiPreview = await openWith(prompt({}));
    expect(screen.getByText("Default (Main)")).toBeTruthy();
    expect(aiPreview).toHaveBeenLastCalledWith(expect.objectContaining({ assistant_id: null }));
  });
});
