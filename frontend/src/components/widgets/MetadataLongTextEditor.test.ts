// @vitest-environment happy-dom
// A long-text field is proofread when it names the node that owns it
// (ADR-0102 §3): same underlines and popover as the prose body, and "Ignore
// here" saved against that node. With no node (the create-project wizard) it
// stays unchecked.
import { describe, expect, it, vi } from "vitest";
import { render } from "@/lib/test/component";
import MetadataLongTextEditor from "@/components/widgets/MetadataLongTextEditor.svelte";
import { MARK_CLASS } from "@/lib/editor-core/proofreadHighlight";

const { lens } = vi.hoisted(() => {
  const cache = new Map<string, unknown[]>();
  const layer = { words: [], rules: {}, dialect: null };
  return {
    lens: {
      active: true,
      cached: (text: string) => cache.get(text),
      lint: vi.fn(async (text: string) => {
        const at = text.indexOf("teh");
        const findings =
          at < 0
            ? []
            : [{ engine: "fake", from: at, to: at + 3, kind: "Spelling", ruleId: "Fake", message: "Check “teh”.", fixes: [] }];
        cache.set(text, findings);
        return findings;
      }),
      subscribe: () => () => undefined,
      setup: {
        words: [],
        word_layers: {},
        rules: {},
        rule_layers: {},
        dialect: "american",
        layers: [{ id: "machine", label: "Machine", is_machine: true, is_library: false, is_root: false, ...layer }],
        ignored: {},
      },
      addWord: vi.fn(async () => undefined),
      disableRule: vi.fn(async () => undefined),
      ignoreHere: vi.fn(async () => undefined),
    },
  };
});

vi.mock("@/lib/stores/proofreading.svelte", () => ({ proofreading: lens }));

const marks = (container: HTMLElement) => Array.from(container.querySelectorAll(`.${MARK_CLASS}`), (el) => el.textContent);

describe("MetadataLongTextEditor proofreading", () => {
  it("underlines a finding when a node owns the field, and ignores it against that node", async () => {
    const { container } = render(MetadataLongTextEditor, { value: "I saw teh cat.", proofreadNodeId: "lore_1" });
    await vi.waitFor(() => expect(marks(container)).toEqual(["teh"]));
    container.querySelector<HTMLElement>(`.${MARK_CLASS}`)!.dispatchEvent(new MouseEvent("click", { bubbles: true, button: 0 }));
    const ignore = Array.from(document.querySelectorAll<HTMLButtonElement>(".proofread-popover button")).find(
      (b) => b.textContent === "Ignore here",
    )!;
    ignore.click();
    await vi.waitFor(() => expect(lens.ignoreHere).toHaveBeenCalled());
    expect(lens.ignoreHere.mock.calls[0]).toEqual(["lore_1", "I saw teh cat.", expect.objectContaining({ ruleId: "Fake" })]);
  });

  it("draws nothing without an owning node", async () => {
    lens.lint.mockClear();
    const { container } = render(MetadataLongTextEditor, { value: "I saw teh cat.", proofreadNodeId: null });
    await new Promise((r) => setTimeout(r, 150));
    expect(marks(container)).toEqual([]);
    expect(lens.lint).not.toHaveBeenCalled();
  });
});
