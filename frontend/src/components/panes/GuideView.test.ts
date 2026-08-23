// @vitest-environment happy-dom
// GuideView is a display surface (#642: a pane that displays data needs a mount
// test) and now honors a one-shot "open at this guide" request (#172, partial
// #1295). These lock two behaviours: (1) with no request it lands on the first
// bundled guide — Getting started, the default landing (#172); and (2) a request
// steers it to a guide that is NOT first, so the prompt editor's "?" still opens
// Writing prompts even though it is no longer the first guide.
import { afterEach, describe, expect, it } from "vitest";
import { flushSync } from "svelte";
import { render, screen } from "@/lib/test/component";
import GuideView from "./GuideView.svelte";
import { guides } from "@/lib/generated/guides";
import { guideTarget } from "@/lib/stores/guideTarget.svelte";

// The request store is a module singleton — clear any pending request so one
// test's request never leaks into the next.
afterEach(() => guideTarget.consume());

describe("GuideView", () => {
  it("lands on the first bundled guide by default (Getting started)", () => {
    render(GuideView);
    flushSync(); // let the one-shot request effect settle (there is none)

    // The active tab (aria-current="page") is the selected guide.
    const active = screen.getByRole("button", { current: "page" });
    expect(active).toHaveTextContent(guides[0].title);
    // Guard the landing order the "?" retarget depends on.
    expect(guides[0].id).toBe("getting-started");
  });

  it("opens at a requested guide even when it is not first (the '?' path)", () => {
    guideTarget.request("writing-prompts");
    render(GuideView);
    flushSync(); // the effect reads the pending request and applies it

    const active = screen.getByRole("button", { current: "page" });
    expect(active).toHaveTextContent("Writing prompts");
    expect(active).not.toHaveTextContent(guides[0].title);
    // The request is one-shot: applying it clears it, so a later plain open
    // (Help → Guides) keeps the default and a second "?" click re-fires.
    expect(guideTarget.requestedId).toBeNull();
  });
});
