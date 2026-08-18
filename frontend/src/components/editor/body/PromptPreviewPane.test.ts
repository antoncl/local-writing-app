// @vitest-environment happy-dom
// ADR-0060 §6 + the #642 lesson (a data-displaying pane needs a mount test that
// asserts its rows actually render): the preview surfaces the SEND-PATH
// composition — the system prefix, the tier-tagged lore the backend places
// (visible again now that templates no longer emit it), then the uncached
// conversation turns. This pins that the tiered blocks + their lore text render.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";

vi.mock("@/lib/api", () => ({ api: { aiPreview: vi.fn() } }));
import { api } from "@/lib/api";
import PromptPreviewPane from "./PromptPreviewPane.svelte";

const PREVIEW = {
  messages: [{ role: "system", blocks: [{ text: "Write the scene." }] }],
  warnings: [],
  char_count: 16,
  session_id: null,
  rendered: true,
  error: null,
  estimated_tokens: 42,
  cache_blocks: [
    { label: "system", role: "system", tokens: 10, tier: "stable", text: "Write the scene." },
    {
      label: "volatile lore",
      role: "system",
      tokens: 20,
      tier: "volatile",
      text: '<lore name="Honor Harrington">A captain.</lore>',
    },
    { label: "user", role: "user", tokens: 12, tier: null, text: "Continue from here." },
  ],
  estimated_cost_usd: null,
  provider: null,
  model: null,
  caching_style: null,
  lore_enabled: true,
  used_node_ids: [],
  used_node_hints: {},
};

describe("PromptPreviewPane", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    (api.aiPreview as ReturnType<typeof vi.fn>).mockResolvedValue(PREVIEW);
  });
  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("renders the send-path composition tier-tagged, lore text visible", async () => {
    render(PromptPreviewPane, {
      props: {
        rawBody: '{% role "system" %}Write the scene.{% endrole %}',
        documentKind: "prompt",
        scene: { id: "s1", title: "Scene", body: "" } as never,
      },
    });
    // The pane is collapsed by default — expand it to see the body.
    await fireEvent.click(screen.getByRole("button", { name: /preview/i }));
    // Fire the debounced render (800ms) and flush the mocked async response.
    await vi.advanceTimersByTimeAsync(1000);

    expect(api.aiPreview).toHaveBeenCalled();
    // Each send-path block renders by label...
    expect(screen.getByText("system")).toBeTruthy();
    expect(screen.getByText("volatile lore")).toBeTruthy();
    // ...tier-tagged (the volatility class the send path assigns)...
    expect(screen.getByText("volatile")).toBeTruthy();
    // ...and the lore is visible again (the point of the slice).
    expect(screen.getByText(/Honor Harrington/)).toBeTruthy();
  });
});
