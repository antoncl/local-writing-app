// @vitest-environment happy-dom
// ADR-0061 §3 / S3b + the #642 lesson (a data-displaying pane needs a mount test
// asserting its rows render): the Inputs editor gained a second, read-only tier
// for inputs a `{% include %}`d snippet contributes. This pins that an inherited
// row renders, tagged with its source snippet, and that the tier is absent when
// nothing is inherited.
import { describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import { PromptInputDraftsController } from "@/lib/stores/promptInputDrafts.svelte";
import EntryInputsEditor from "./EntryInputsEditor.svelte";

const noopId = () => "cid-0";
const slug = (v: string) => v;

// A valid own draft for `name`, built the same way the editor seeds them.
function ownDrafts(...names: string[]) {
  const controller = new PromptInputDraftsController();
  controller.reseed(
    { id: "p1", inputs: names.map((name) => ({ name, type: "text" })) } as never,
    "prompt",
  );
  return controller.drafts;
}

describe("EntryInputsEditor — inherited tier", () => {
  it("renders an inherited input read-only, tagged with its source snippet", () => {
    render(EntryInputsEditor, {
      props: {
        entryInputDrafts: [],
        inheritedInputs: [
          {
            definition: { name: "menace", type: "select" },
            sourceId: "villain",
            sourceTitle: "Villain Voice",
          },
        ],
        nextInputDraftId: noopId,
        entrySlugify: slug,
      },
    });

    // The inherited field and its provenance tag both render...
    expect(screen.getByText("menace")).toBeTruthy();
    expect(screen.getByText(/from Villain Voice/)).toBeTruthy();
    // ...under the read-only "Inherited" tier, not as an editable own input.
    expect(screen.getByText("Inherited")).toBeTruthy();
    expect(screen.queryByText(/declared on this prompt/)).toBeTruthy(); // the own-tier header still there
  });

  it("shows no inherited tier when nothing is inherited", () => {
    render(EntryInputsEditor, {
      props: {
        entryInputDrafts: [],
        inheritedInputs: [],
        nextInputDraftId: noopId,
        entrySlugify: slug,
      },
    });
    expect(screen.queryByText("Inherited")).toBeNull();
  });

  it("drops an inherited input the author has declared as an own input (the override case)", () => {
    render(EntryInputsEditor, {
      props: {
        // `menace` is declared as an OWN input, overriding the snippet's.
        entryInputDrafts: ownDrafts("menace"),
        inheritedInputs: [
          {
            definition: { name: "menace", type: "text" },
            sourceId: "villain",
            sourceTitle: "Villain Voice",
          },
        ],
        nextInputDraftId: noopId,
        entrySlugify: slug,
      },
    });
    // The own draft wins its row; the inherited duplicate drops, so there is no
    // inherited tier at all (it was the only inherited input).
    expect(screen.queryByText("Inherited")).toBeNull();
    expect(screen.queryByText(/from Villain Voice/)).toBeNull();
  });
});

// #1431: a built-in Library prompt is viewable but not editable. The body is
// rendered inert (blocks every control + drops it from the tab order) while the
// summary stays live, so the group can still be expanded to inspect it — the
// previous host-level `inert` also froze the summary shut, hiding the config.
describe("EntryInputsEditor — read-only (Library prompt)", () => {
  it("renders the body inert while keeping the summary toggleable", () => {
    const { container } = render(EntryInputsEditor, {
      props: {
        entryInputDrafts: ownDrafts("topic"),
        inheritedInputs: [],
        nextInputDraftId: noopId,
        entrySlugify: slug,
        readOnly: true,
      },
    });
    const body = container.querySelector(".entry-inputs-body");
    expect(body).toBeTruthy();
    expect(body?.hasAttribute("inert")).toBe(true);
    // The summary is a live sibling (not inside the inert body), so the group
    // stays expandable; the add-input control lives inside the inert body.
    expect(container.querySelector("details > summary")).toBeTruthy();
    expect(body?.querySelector(".entry-inputs-add button")).toBeTruthy();
  });

  it("leaves the body interactive when not read-only", () => {
    const { container } = render(EntryInputsEditor, {
      props: {
        entryInputDrafts: ownDrafts("topic"),
        inheritedInputs: [],
        nextInputDraftId: noopId,
        entrySlugify: slug,
      },
    });
    expect(container.querySelector(".entry-inputs-body")?.hasAttribute("inert")).toBe(false);
  });
});
