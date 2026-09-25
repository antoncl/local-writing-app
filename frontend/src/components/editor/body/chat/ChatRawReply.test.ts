// @vitest-environment happy-dom
// #2201 — the collapsed disclosure that shows the model's raw reply below a
// commit notice when the patch was unusable. A small mount test: the summary
// names it, and the raw text renders (collapsed but present in the DOM — a
// <details> element, not a drill).
import { describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import ChatRawReply from "./ChatRawReply.svelte";

describe("ChatRawReply", () => {
  it("shows the summary label and the raw reply text", () => {
    render(ChatRawReply, { text: "not valid json at all" });
    expect(screen.getByText("The model's reply")).toBeInTheDocument();
    expect(screen.getByTestId("chat-raw-reply")).toHaveTextContent(
      "not valid json at all",
    );
  });
});
