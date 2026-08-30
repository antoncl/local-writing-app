// @vitest-environment happy-dom
// ADR-0060 §6 + the #642 lesson (a data-displaying pane needs a mount test that
// asserts its rows actually render): the preview surfaces the SEND-PATH
// composition — the system prefix, the tier-tagged lore the backend places
// (visible again now that templates no longer emit it), then the uncached
// conversation turns. This pins that the tiered blocks + their lore text render.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, within } from "@/lib/test/component";

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

  // #1252: an extract_to_node prompt whose render registers no field_contract can
  // only ever commit an empty change — warn the author here, at authoring time.
  // Each case uses a DISTINCT scene id: the preview record is a persistent
  // per-document store, so a shared id would reuse the prior case's cached result.
  // The pane keys its (persistent) preview record by `loadedSceneId`, so each case
  // needs a distinct one — otherwise the shared record + identical rawBody hits the
  // render dedup and reuses the prior case's result.
  const commitProps = (id: string, outputHandler: string) => ({
    rawBody: '{% role "system" %}Revise it.{% endrole %}',
    documentKind: "prompt" as const,
    scene: { id, title: "Scene", body: "" } as never,
    loadedSceneId: id,
    outputHandler,
  });

  // Expand the (collapsed-by-default) pane and flush the debounced render — the
  // same path the send-path test above uses, which reliably fires api.aiPreview.
  async function renderExpanded(props: Record<string, unknown>) {
    const rendered = render(PromptPreviewPane, { props });
    await fireEvent.click(screen.getByRole("button", { name: /preview/i }));
    await vi.advanceTimersByTimeAsync(1000);
    return rendered;
  }

  it("lints an extract_to_node prompt that registers no fields (#1252)", async () => {
    (api.aiPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...PREVIEW,
      field_contract_stored: [],
    });
    const { container } = await renderExpanded(commitProps("commit-empty", "extract_to_node"));
    expect(within(container).getByText(/declares no fields/)).toBeTruthy();
  });

  it("does not lint once the extract_to_node prompt registers a field", async () => {
    (api.aiPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...PREVIEW,
      field_contract_stored: [{ id: "bio" }],
    });
    const { container } = await renderExpanded(commitProps("commit-filled", "extract_to_node"));
    expect(within(container).queryByText(/declares no fields/)).toBeNull();
  });

  it("does not lint a non-commit prompt with no field_contract", async () => {
    // A plain chat / snippet has no output handler and legitimately registers no
    // fields — it must never be nagged.
    (api.aiPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...PREVIEW,
      field_contract_stored: [],
    });
    const { container } = await renderExpanded(commitProps("commit-nohandler", ""));
    expect(within(container).queryByText(/declares no fields/)).toBeNull();
  });

  it("does not lint while a required input is unfilled (#1694)", async () => {
    // ADR-0067 Amendment 1: the contract is input-driven (fields(inputs.entry_type)),
    // so until the required input is filled the render is legitimately empty — the
    // warning must not fire on an unsatisfied preview (it fired on the built-ins).
    (api.aiPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...PREVIEW,
      field_contract_stored: [],
    });
    const { container } = await renderExpanded({
      ...commitProps("commit-required-unfilled", "extract_to_node"),
      scene: {
        id: "commit-required-unfilled",
        title: "Scene",
        body: "",
        inputs: [{ name: "entry_type", type: "text", required: true }],
      } as never,
    });
    expect(within(container).queryByText(/declares no fields/)).toBeNull();
  });

  // ADR-0061 S2: the panel renders the EFFECTIVE inputs the resolver returns, so
  // a snippet's field shows up even though the outer prompt never declared it.
  it("shows a snippet-contributed input once the resolver returns it", async () => {
    (api.aiPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...PREVIEW,
      effective_inputs: [
        { name: "subject", type: "text" },
        { name: "menace", type: "select" },
      ],
      input_conflicts: [],
    });
    render(PromptPreviewPane, {
      props: {
        rawBody: '{% role "user" %}{% include "villain" %} {{ inputs.subject }}{% endrole %}',
        documentKind: "prompt",
        scene: { id: "p1", title: "P", body: "", inputs: [{ name: "subject", type: "text" }] } as never,
      },
    });
    await fireEvent.click(screen.getByRole("button", { name: /preview/i }));
    await vi.advanceTimersByTimeAsync(1000);

    // The outer declared only `subject`; `menace` came from the included snippet.
    expect(screen.getByText("menace")).toBeTruthy();
  });

  it("surfaces an include-type conflict returned by the resolver", async () => {
    (api.aiPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...PREVIEW,
      effective_inputs: [{ name: "tone", type: "text" }],
      input_conflicts: [{ name: "tone", types: ["text", "select"] }],
    });
    render(PromptPreviewPane, {
      props: {
        rawBody: '{% include "a" %}{% include "b" %}',
        documentKind: "prompt",
        scene: { id: "p2", title: "P", body: "", inputs: [] } as never,
      },
    });
    await fireEvent.click(screen.getByRole("button", { name: /preview/i }));
    await vi.advanceTimersByTimeAsync(1000);

    expect(screen.getByText(/Input type conflict/i)).toBeTruthy();
    expect(screen.getByText(/different types across included/i)).toBeTruthy();
  });

  // #1427: design-time preview has no live prose context, so the three runtime
  // prose slots are sent as visible placeholder tokens — a `{{ selection }}`
  // template renders with its slot position shown, not silently empty.
  it("sends placeholder tokens for the runtime prose slots (#1427)", async () => {
    render(PromptPreviewPane, {
      props: {
        rawBody: '{% role "system" %}Revise: {{ selection }}{% endrole %}',
        documentKind: "prompt",
        scene: { id: "sel", title: "Scene", body: "" } as never,
        loadedSceneId: "sel",
      },
    });
    await fireEvent.click(screen.getByRole("button", { name: /preview/i }));
    await vi.advanceTimersByTimeAsync(1000);

    expect(api.aiPreview).toHaveBeenCalledWith(
      expect.objectContaining({
        selection: "«the selected text»",
        text_before: "«text before the cursor»",
        text_after: "«text after the cursor»",
      }),
    );
  });
});
