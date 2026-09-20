// @vitest-environment happy-dom
// PlotBeatSections (#2043 slice 3): the board's host for the repeating
// BodyListSection(s) of a plot:thread entry. MetadataLongTextEditor is
// swapped for the same stub BodyListSection.test.ts uses (#642 — TipTap
// never mounts under happy-dom).
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import { metadataSchemaStore } from "@/lib/stores/schema";
import PlotBeatSections from "./PlotBeatSections.svelte";
import type { MetadataSchema, PlotlineEntry } from "@/lib/types";

vi.mock("@/components/widgets/MetadataLongTextEditor.svelte", async () => {
  const stub = await import("@/components/editor/body/BodySections.mockLongText.svelte");
  return { default: stub.default };
});

const SCHEMA = {
  version: 1,
  entry_types: {
    "plot:plotline": { name: "Plotline", kind: "plot", fields: ["instance_beats"] },
  },
  fields: {
    instance_beats: {
      name: "Specialized beats",
      type: "list",
      options: [],
      item_members: [
        { key: "title", name: "Title", type: "text" },
        { key: "function", name: "Function", type: "long_text" },
        { key: "guidance", name: "Guidance", type: "long_text" },
        { key: "specifics", name: "Specifics", type: "long_text" },
        { key: "required", name: "Required", type: "boolean" },
        { key: "id", name: "Id", type: "text" },
      ],
    },
  },
} as unknown as MetadataSchema;

function entry(): PlotlineEntry {
  return {
    id: "line_1",
    title: "Main plot",
    body: "",
    revision: "r1",
    entry_type: "plot:plotline",
    metadata: {
      instance_beats: [
        { title: "Setup", function: "Establish the world.", guidance: "", specifics: "", required: true, id: "b1" },
        { title: "Confrontation", function: "", guidance: "", specifics: "", required: true, id: "b2" },
      ],
    },
    computed_metadata: {},
  };
}

describe("PlotBeatSections", () => {
  beforeEach(() => {
    metadataSchemaStore.set(SCHEMA);
  });

  it("renders one section with the entry's beats as title inputs and the mock editors carrying the prose", () => {
    const { container } = render(PlotBeatSections, { props: { entry: entry(), onChange: vi.fn() } });
    const titleInputs = screen.getAllByRole("textbox", { name: /Specialized beats \d+ title/ }) as HTMLInputElement[];
    expect(titleInputs.map((i) => i.value)).toEqual(["Setup", "Confrontation"]);
    const editors = container.querySelectorAll('[data-testid="mock-long-text"]');
    expect(editors[0].textContent).toBe("Establish the world.");
  });

  it("renaming beat 1 calls onChange with the full metadata, other members untouched", async () => {
    const onChange = vi.fn();
    render(PlotBeatSections, { props: { entry: entry(), onChange } });
    const input = screen.getByRole("textbox", { name: "Specialized beats 1 title" }) as HTMLInputElement;
    await fireEvent.change(input, { target: { value: "Renamed setup" } });
    expect(onChange).toHaveBeenCalledWith({
      instance_beats: [
        { title: "Renamed setup", function: "Establish the world.", guidance: "", specifics: "", required: true, id: "b1" },
        { title: "Confrontation", function: "", guidance: "", specifics: "", required: true, id: "b2" },
      ],
    });
  });

  it("+ Add item calls onChange with an appended {}", async () => {
    const onChange = vi.fn();
    render(PlotBeatSections, { props: { entry: entry(), onChange } });
    await fireEvent.click(screen.getByRole("button", { name: "+ Add item" }));
    const call = onChange.mock.calls[0][0];
    expect(call.instance_beats[2]).toEqual({});
    expect(call.instance_beats).toHaveLength(3);
  });

  it("renders no section with the schema store null", () => {
    metadataSchemaStore.set(null);
    const { container } = render(PlotBeatSections, { props: { entry: entry(), onChange: vi.fn() } });
    expect(container.querySelectorAll(".bs-block")).toHaveLength(0);
  });
});
