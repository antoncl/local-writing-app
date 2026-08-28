// @vitest-environment happy-dom
// The transcript is a data-displaying surface, so it gets a mount test (#642):
// the rows must actually render, and the assistant speaker header must name
// the answering assistant, not a hardcoded product name (#989).
import { describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
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
});
