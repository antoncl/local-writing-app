// @vitest-environment happy-dom
// The transcript is a data-displaying surface, so it gets a mount test (#642):
// the rows must actually render, and the assistant speaker header must name
// the answering assistant, not a hardcoded product name (#989).
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@/lib/test/component";
import ChatTranscript from "./ChatTranscript.svelte";
import type { ChatMessage } from "@/lib/types";

const HISTORY = [
  { role: "user", content: "Who rules the vale?" },
  { role: "assistant", content: "The Regent does." },
] as ChatMessage[];

describe("ChatTranscript", () => {
  it("renders the turns with You / <assistant title> speaker headers", () => {
    render(ChatTranscript, { chatHistory: HISTORY, chatRunning: false, assistantName: "Summarizer" });
    expect(screen.getByText("Who rules the vale?")).toBeInTheDocument();
    expect(screen.getByText("The Regent does.")).toBeInTheDocument();
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getByText("Summarizer")).toBeInTheDocument();
    expect(screen.queryByText("Claude")).not.toBeInTheDocument();
  });

  it("falls back to a neutral header when no assistant name is supplied", () => {
    render(ChatTranscript, { chatHistory: HISTORY, chatRunning: false });
    expect(screen.getByText("Assistant")).toBeInTheDocument();
    expect(screen.queryByText("Claude")).not.toBeInTheDocument();
  });

  // ADR-0076 S1: provider/model/latency moved onto the assistant turn's own
  // meta line instead of a floating cbv-meta paragraph below the composer.
  it("renders provider, model, and latency on the turn's meta line", () => {
    const history = [
      {
        role: "assistant",
        content: "The Regent does.",
        provider: "anthropic",
        model: "claude-3-5-sonnet",
        latency_ms: 9600,
        usage: { input_tokens: 100, cached_input_tokens: 0, cache_write_tokens: 0, output_tokens: 20 },
      },
    ] as ChatMessage[];
    const { container } = render(ChatTranscript, { chatHistory: history, chatRunning: false });
    const meta = container.querySelector(".cbv-turn-meta");
    expect(meta?.textContent).toContain("anthropic");
    expect(meta?.textContent).toContain("claude-3-5-sonnet");
    expect(meta?.textContent).toContain("9.6 s");
  });

  // ADR-0086 §5: the lore-budget segment sits on the same meta line, in the
  // ordinary register (not `.cbv-meta-danger`), and only when something was
  // left out or the declared set alone exceeded the budget.
  it("renders the lore-fit segment when the send left entries out", () => {
    const history = [
      {
        role: "assistant",
        content: "The Regent does.",
        provider: "openrouter",
        model: "deepseek-v4-flash",
        usage: { input_tokens: 100, cached_input_tokens: 0, cache_write_tokens: 0, output_tokens: 20 },
        lore_fit: {
          budget_tokens: 16000,
          used_tokens: 15800,
          declared_tokens: 2100,
          kept: 21,
          left_out: Array.from({ length: 19 }, (_, i) => ({
            id: `lore_${i}`, title: `Entry ${i}`, source: "depth1_expansion", tokens: 900,
          })),
        },
      },
    ] as ChatMessage[];
    const { container } = render(ChatTranscript, { chatHistory: history, chatRunning: false });
    const meta = container.querySelector(".cbv-turn-meta");
    expect(meta?.textContent).toContain("lore 15.8k/16k · 19 left out");
    expect(meta?.textContent).not.toContain("declared lore");
    expect(container.querySelector(".cbv-meta-danger")).not.toBeInTheDocument();
  });

  // #1958: the history-window segment sits on the same meta line, only when a
  // round was actually dropped.
  it("renders the history-fit segment when the send dropped older exchanges", () => {
    const history = [
      {
        role: "assistant",
        content: "The Regent does.",
        provider: "ollama",
        model: "llama3.2",
        usage: { input_tokens: 100, cached_input_tokens: 0, cache_write_tokens: 0, output_tokens: 20 },
        history_fit: { budget_tokens: 16000, used_tokens: 12400, kept_rounds: 4, dropped_rounds: 3 },
      },
    ] as ChatMessage[];
    const { container } = render(ChatTranscript, { chatHistory: history, chatRunning: false });
    expect(container.querySelector(".cbv-turn-meta")?.textContent).toContain(
      "history 12.4k/16k · 3 earlier exchanges dropped",
    );
  });

  it("stays silent when the history window dropped nothing", () => {
    const history = [
      {
        role: "assistant",
        content: "A.",
        usage: { input_tokens: 10, cached_input_tokens: 0, cache_write_tokens: 0, output_tokens: 5 },
        history_fit: { budget_tokens: 16000, used_tokens: 800, kept_rounds: 2, dropped_rounds: 0 },
      },
    ] as ChatMessage[];
    const { container } = render(ChatTranscript, { chatHistory: history, chatRunning: false });
    expect(container.querySelector(".cbv-turn-meta")?.textContent).not.toContain("dropped");
  });

  it("words a declared set over the budget as such, and stays silent when all fitted", () => {
    const over = [
      {
        role: "assistant",
        content: "A.",
        lore_fit: { budget_tokens: 16000, used_tokens: 0, declared_tokens: 30200, kept: 4, left_out: [] },
      },
    ] as ChatMessage[];
    const { container } = render(ChatTranscript, { chatHistory: over, chatRunning: false });
    expect(container.querySelector(".cbv-turn-meta")?.textContent).toContain(
      "declared lore 30.2k, over the 16k budget",
    );

    const fitted = [
      {
        role: "assistant",
        content: "B.",
        lore_fit: { budget_tokens: 16000, used_tokens: 900, declared_tokens: 100, kept: 3, left_out: [] },
      },
    ] as ChatMessage[];
    const silent = render(ChatTranscript, { chatHistory: fitted, chatRunning: false });
    expect(silent.container.querySelector(".cbv-turn-meta")).not.toBeInTheDocument();

    // A budget of 0 means "declared entries only" (ADR-0086 §2) — the declared
    // set is never "over" it, so no warning renders for that legal setting.
    const declaredOnly = [
      {
        role: "assistant",
        content: "C.",
        lore_fit: { budget_tokens: 0, used_tokens: 0, declared_tokens: 2100, kept: 2, left_out: [] },
      },
    ] as ChatMessage[];
    const zero = render(ChatTranscript, { chatHistory: declaredOnly, chatRunning: false });
    expect(zero.container.querySelector(".cbv-turn-meta")).not.toBeInTheDocument();
  });

  // Regression: old persisted chats have no provenance fields — the meta line
  // must still render (usage/cost) without a provider clause.
  it("renders the meta line without provider text when the message lacks it", () => {
    const history = [
      {
        role: "assistant",
        content: "The Regent does.",
        usage: { input_tokens: 100, cached_input_tokens: 0, cache_write_tokens: 0, output_tokens: 20 },
      },
    ] as ChatMessage[];
    const { container } = render(ChatTranscript, { chatHistory: history, chatRunning: false });
    const meta = container.querySelector(".cbv-turn-meta");
    expect(meta).toBeInTheDocument();
    expect(meta?.textContent).not.toContain("anthropic");
  });

  // A provider that reports no usage (a local model) still stamps
  // provider/model/latency on `done` — the provenance must render without a
  // usage block, not vanish with it (S1 review: the usage-less case is
  // exactly where "which model answered" matters most).
  it("renders provenance even when the stream reported no usage", () => {
    const history = [
      {
        role: "assistant",
        content: "The Regent does.",
        provider: "ollama",
        model: "llama3.1",
        latency_ms: 2431,
      },
    ] as ChatMessage[];
    const { container } = render(ChatTranscript, { chatHistory: history, chatRunning: false });
    const meta = container.querySelector(".cbv-turn-meta");
    expect(meta?.textContent).toContain("ollama");
    expect(meta?.textContent).toContain("llama3.1");
    expect(meta?.textContent).toContain("2.4 s");
    expect(meta?.textContent).not.toContain("tok");
  });

  // No usage AND no provenance (an old chat's user-visible-content-only
  // message) renders no meta line at all.
  it("renders no meta line when a turn has neither usage nor provenance", () => {
    const { container } = render(ChatTranscript, { chatHistory: HISTORY, chatRunning: false });
    expect(container.querySelector(".cbv-turn-meta")).not.toBeInTheDocument();
  });

  // ADR-0076 S3: a Stop mid-stream keeps the partial reply and stamps it
  // `stopped` — the transcript shows the "Stopped early" banner, reusing the
  // truncation-pill idiom (mutually exclusive with `truncated` in practice).
  it("renders the Stopped early banner for a stopped message", () => {
    const history = [
      { role: "assistant", content: "The Regent do", stopped: true },
    ] as ChatMessage[];
    render(ChatTranscript, { chatHistory: history, chatRunning: false });
    expect(screen.getByText("Stopped early — partial reply kept.")).toBeInTheDocument();
    expect(screen.queryByText("Response cut off — hit max tokens.")).not.toBeInTheDocument();
  });

  // Stick-to-bottom (#1611): the jump-to-latest button is presentational
  // here — ChatBodyView owns the pin/near-bottom logic and just flips
  // `showJumpToLatest`.
  it("shows the jump-to-latest button when showJumpToLatest is true", () => {
    render(ChatTranscript, { chatHistory: [], chatRunning: false, showJumpToLatest: true });
    expect(screen.getByRole("button", { name: "Jump to latest" })).toBeInTheDocument();
  });

  it("hides the jump-to-latest button when showJumpToLatest is false (or omitted)", () => {
    render(ChatTranscript, { chatHistory: [], chatRunning: false, showJumpToLatest: false });
    expect(screen.queryByRole("button", { name: "Jump to latest" })).not.toBeInTheDocument();

    render(ChatTranscript, { chatHistory: [], chatRunning: false });
    expect(screen.queryByRole("button", { name: "Jump to latest" })).not.toBeInTheDocument();
  });

  it("clicking the jump-to-latest button calls onJumpToLatest", async () => {
    let clicked = false;
    render(ChatTranscript, {
      chatHistory: [],
      chatRunning: false,
      showJumpToLatest: true,
      onJumpToLatest: () => {
        clicked = true;
      },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Jump to latest" }));
    expect(clicked).toBe(true);
  });

  // #2206: an auto-added chip the lore budget left out of the send renders
  // "not sent" — detection noticed it, the model never received it.
  it("marks an auto-added chip the budget left out, and only that one", () => {
    const history = [
      {
        role: "assistant",
        content: "The Regent does.",
        journal_added: [
          { entry_id: "lore_sent", title: "The Regent", source: "user_message" },
          { entry_id: "lore_dropped", title: "The Vale", source: "depth1_expansion" },
        ],
        lore_fit: {
          budget_tokens: 1000,
          used_tokens: 900,
          declared_tokens: 0,
          kept: 1,
          left_out: [{ id: "lore_dropped", title: "The Vale", source: "depth1_expansion", tokens: 1200 }],
        },
      },
    ] as ChatMessage[];
    render(ChatTranscript, { chatHistory: history, chatRunning: false });
    const dropped = screen.getByTestId("journal-chip-left-out");
    expect(dropped).toHaveTextContent("The Vale");
    expect(dropped.getAttribute("title")).toContain("left out of this send");
    expect(screen.getByTestId("journal-chip")).toHaveTextContent("The Regent");
  });

  // #2212: under a Named-only Lore reach, a hop entry was noticed but never
  // actually sent — marked the same "not sent" way, with its own tooltip.
  it("marks a hop chip as not sent under Named-only reach, leaving a named chip alone", () => {
    const history = [
      {
        role: "assistant",
        content: "The Regent does.",
        journal_added: [
          { entry_id: "lore_named", title: "The Regent", source: "user_message" },
          { entry_id: "lore_hop", title: "The Vale", source: "depth1_expansion" },
        ],
        lore_fit: {
          budget_tokens: 16000,
          used_tokens: 900,
          declared_tokens: 0,
          kept: 1,
          left_out: [],
          expansion: "named",
        },
      },
    ] as ChatMessage[];
    render(ChatTranscript, { chatHistory: history, chatRunning: false });
    const hop = screen.getByTestId("journal-chip-left-out");
    expect(hop).toHaveTextContent("The Vale");
    expect(hop.getAttribute("title")).toContain("Lore reach is Named only");
    expect(screen.getByTestId("journal-chip")).toHaveTextContent("The Regent");
  });
});
