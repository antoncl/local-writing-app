// #2339: a reply's thinking is kept on the transcript but never sent back to
// the model in a later turn's history.
import { describe, expect, it } from "vitest";
import { outgoingHistory } from "./outgoingHistory";
import type { ChatMessage } from "@/lib/types";

describe("outgoingHistory (#2339)", () => {
  it("sends only role and content — no thinking, usage or cost", () => {
    const transcript: ChatMessage[] = [
      { role: "user", content: "first" },
      {
        role: "assistant",
        content: "the answer",
        thinking: "SECRET REASONING",
        truncated: false,
        cost_usd: 0.01,
      } as ChatMessage,
      { role: "user", content: "follow-up" },
    ];
    const sent = outgoingHistory(transcript);
    expect(sent).toEqual([
      { role: "user", content: "first" },
      { role: "assistant", content: "the answer" },
      { role: "user", content: "follow-up" },
    ]);
    expect(JSON.stringify(sent)).not.toContain("SECRET REASONING");
  });
});
