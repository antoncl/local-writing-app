// @vitest-environment happy-dom
// The Setup tab's output-config editor (ADR-0062 Am.2 / D3). Pins the mode
// switch revealing the right sub-form, the emitted shape reflected back
// through the bound `contextStrategy` (read via DOM state, the same pattern
// OfferOnPicker.test.ts uses — testing-library/svelte 5's mount() doesn't
// expose bindable props on `component`, so the render is the read-back), the
// orthogonal headless toggle (incl. the no-runtime-yet annotation), the
// empty→null collapse, and read-only gating.
//
// The whole editor sits in a closed-by-default `<details>` (mirrors
// OfferOnPicker), so role queries need `hidden: true` — same reason
// OfferOnPicker.test.ts's `box()` helper does (a closed <details>'s content is
// treated as accessibility-hidden regardless of the DOM impl's layout).
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import PromptOutputEditor from "./PromptOutputEditor.svelte";
import type { PromptContextStrategy } from "@/lib/types";

function btn(name: string | RegExp) {
  return screen.getByRole("button", { name, hidden: true });
}
function queryBtn(name: string | RegExp) {
  return screen.queryByRole("button", { name, hidden: true });
}
function box(name: string | RegExp) {
  return screen.getByRole("checkbox", { name, hidden: true });
}
function queryBox(name: string | RegExp) {
  return screen.queryByRole("checkbox", { name, hidden: true });
}

describe("PromptOutputEditor (ADR-0062 D3)", () => {
  it("defaults to Conversation with no sub-form", () => {
    render(PromptOutputEditor, { props: { contextStrategy: null } });
    expect(btn("Conversation")).toHaveAttribute("aria-pressed", "true");
    expect(queryBtn("Continue at cursor")).not.toBeInTheDocument();
    expect(queryBox("Commit button (extract to a node)")).not.toBeInTheDocument();
  });

  it("shows a persistent mode hint that updates when the mode changes (#1200)", async () => {
    render(PromptOutputEditor, { props: { contextStrategy: null } });
    expect(screen.getByText(/Pick Conversation/i)).toBeInTheDocument();
    await fireEvent.click(btn("Inline suggestion"));
    expect(screen.getByText(/Pick Inline suggestion/i)).toBeInTheDocument();
    expect(screen.queryByText(/Pick Conversation/i)).not.toBeInTheDocument();
  });

  it("switching to Inline reveals the destination + on_accept sub-form and emits", async () => {
    const onChange = vi.fn();
    render(PromptOutputEditor, { props: { contextStrategy: null, onChange } });
    await fireEvent.click(btn("Inline suggestion"));
    expect(btn("Inline suggestion")).toHaveAttribute("aria-pressed", "true");
    expect(btn("Continue at cursor")).toHaveAttribute("aria-pressed", "true");
    expect(onChange).toHaveBeenCalledTimes(1);

    await fireEvent.click(btn("Replace selection"));
    expect(btn("Replace selection")).toHaveAttribute("aria-pressed", "true");
    expect(onChange).toHaveBeenCalledTimes(2);

    // on_accept only emits once mark or from_input is non-empty.
    await fireEvent.input(screen.getByLabelText("Mark", { selector: "input" }), { target: { value: "character" } });
    expect(onChange).toHaveBeenCalledTimes(3);
  });

  it("switching to Brainstorm/commit reveals the commit toggle; enabling it reveals review", async () => {
    const onChange = vi.fn();
    render(PromptOutputEditor, { props: { contextStrategy: null, onChange } });
    await fireEvent.click(btn("Brainstorm / commit"));
    expect(btn("Brainstorm / commit")).toHaveAttribute("aria-pressed", "true");
    const commitToggle = box("Commit button (extract to a node)");
    expect(commitToggle).not.toBeChecked();
    expect(queryBtn("Visual diff")).not.toBeInTheDocument();

    await fireEvent.click(commitToggle);
    expect(btn("Visual diff")).toHaveAttribute("aria-pressed", "true");
    // ADR-0067 Amendment 1: no "Target type" picker — the target entry_type is
    // an input, not output config.
    expect(screen.queryByRole("combobox", { name: "Target type", hidden: true })).not.toBeInTheDocument();
    // ADR-0067 S2: which fields the commit extracts is authored in the
    // prompt's own Jinja (field_contract), not a picker here.
    expect(queryBox(/Restrict to specific fields/)).not.toBeInTheDocument();
  });

  it("headless is orthogonal to the mode — toggling it alone doesn't change the mode", async () => {
    const onChange = vi.fn();
    render(PromptOutputEditor, { props: { contextStrategy: null, onChange } });
    await fireEvent.click(box("Run headlessly"));
    expect(box("Run headlessly")).toBeChecked();
    expect(btn("Conversation")).toHaveAttribute("aria-pressed", "true");
    expect(onChange).toHaveBeenCalledTimes(1);
    // No annotation outside extract_to_node.
    expect(screen.queryByText(/generated headlessly/i)).not.toBeInTheDocument();
  });

  it("extract_to_node + headless shows the no-runtime-yet annotation", async () => {
    render(PromptOutputEditor, { props: { contextStrategy: null } });
    await fireEvent.click(btn("Brainstorm / commit"));
    await fireEvent.click(box("Run headlessly"));
    expect(screen.getByText(/generated headlessly \(arrives with e\)/i)).toBeInTheDocument();
  });

  it("switching away from extract_to_node clears its stale commit config", async () => {
    render(PromptOutputEditor, { props: { contextStrategy: null } });
    await fireEvent.click(btn("Brainstorm / commit"));
    await fireEvent.click(box("Commit button (extract to a node)"));
    expect(box("Commit button (extract to a node)")).toBeChecked();

    await fireEvent.click(btn("Conversation"));
    await fireEvent.click(btn("Brainstorm / commit"));
    // Re-entering extract_to_node starts with no commit — the switch to
    // Conversation dropped it rather than stranding it for a later resurrect.
    expect(box("Commit button (extract to a node)")).not.toBeChecked();
  });

  it("read-only locks every control and swallows edits", async () => {
    const preset: PromptContextStrategy = { output: { handler: "inline", destination: "cursor" } };
    const onChange = vi.fn();
    render(PromptOutputEditor, { props: { contextStrategy: preset, readOnly: true, onChange } });
    expect(box("Run headlessly")).toBeDisabled();
    await fireEvent.click(btn("Brainstorm / commit"));
    expect(onChange).not.toHaveBeenCalled();
    // The mode reading is unchanged — still Inline, not swallowed silently
    // into some other state.
    expect(btn("Inline suggestion")).toHaveAttribute("aria-pressed", "true");
  });
});
