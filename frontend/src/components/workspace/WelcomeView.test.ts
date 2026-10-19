// @vitest-environment happy-dom
// The no-project state hosts the guide viewer (#2558): before a project opens
// there is no Workspace to put the guide region in, so a new user must still be
// able to read "Getting started" from here. Locks the welcome link (opens the
// viewer AT Getting started), the ≡ → Guides path (the host sets guideOpen), and
// the × that returns to the bare hint.
import { afterEach, describe, expect, it } from "vitest";
import { flushSync } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import WelcomeView from "./WelcomeView.svelte";
import { guideTarget } from "@/lib/stores/guideTarget.svelte";

afterEach(() => guideTarget.consume());

describe("WelcomeView", () => {
  it("shows the hint and a Getting started link, no viewer yet", () => {
    render(WelcomeView);
    expect(screen.getByTestId("no-project")).toHaveTextContent("No project open");
    expect(screen.getByRole("button", { name: "Read the Getting started guide" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Guides" })).toBeNull();
  });

  it("opens the viewer at Getting started from the link, and closes it with ×", async () => {
    render(WelcomeView);

    await fireEvent.click(screen.getByRole("button", { name: "Read the Getting started guide" }));
    flushSync();
    expect(screen.getByRole("navigation", { name: "Guides" })).toBeInTheDocument();
    expect(screen.getByRole("button", { current: "page" })).toHaveTextContent("Getting started");

    await fireEvent.click(screen.getByRole("button", { name: "Close guides" }));
    expect(screen.queryByRole("navigation", { name: "Guides" })).toBeNull();
    expect(screen.getByRole("button", { name: "Read the Getting started guide" })).toBeInTheDocument();
  });

  it("renders the viewer when the host opens it (≡ → Guides with no project)", () => {
    render(WelcomeView, { props: { guideOpen: true } });
    expect(screen.getByRole("navigation", { name: "Guides" })).toBeInTheDocument();
  });
});
