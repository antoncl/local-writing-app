// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/lib/test/component";
import { fireEvent } from "@testing-library/svelte";
import SummaryFieldsEditor from "./SummaryFieldsEditor.svelte";

const FIELDS = [
  { id: "name", label: "Name" },
  { id: "role", label: "Role" },
  { id: "age", label: "Age" },
];

describe("SummaryFieldsEditor (#2008)", () => {
  it("renders the nominated chips in order", () => {
    render(SummaryFieldsEditor, {
      props: { fields: FIELDS, value: ["age", "name"], inherited: null, inheritedFrom: null, onChange: vi.fn() },
    });
    const chips = screen.getAllByRole("listitem").map((el) => el.textContent?.trim());
    expect(chips[0]).toContain("Age");
    expect(chips[1]).toContain("Name");
  });

  it("× removes that field, calling onChange without it", async () => {
    const onChange = vi.fn();
    render(SummaryFieldsEditor, {
      props: { fields: FIELDS, value: ["age", "name"], inherited: null, inheritedFrom: null, onChange },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Remove Age from summary" }));
    expect(onChange).toHaveBeenCalledWith(["name"]);
  });

  it("+ opens a picker; choosing a field appends it", async () => {
    const onChange = vi.fn();
    render(SummaryFieldsEditor, {
      props: { fields: FIELDS, value: ["name"], inherited: null, inheritedFrom: null, onChange },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Add a summary field" }));
    const select = screen.getByRole("combobox", { name: "Add a summary field" }) as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: "age" } });
    expect(onChange).toHaveBeenCalledWith(["name", "age"]);
  });

  it("with no own nomination, renders the inherited chips dimmed with a from-parent hint", () => {
    const { container } = render(SummaryFieldsEditor, {
      props: { fields: FIELDS, value: null, inherited: ["name"], inheritedFrom: "Character", onChange: vi.fn() },
    });
    const chip = container.querySelector(".sfe-chip-inherited");
    expect(chip?.textContent).toContain("Name");
    expect(chip?.querySelector(".sfe-chip-remove")).toBeNull();
    expect(chip?.querySelector(".sfe-grip")).toBeNull();
    expect(screen.getByText("from Character")).toBeTruthy();
  });

  it("adding while inherited copies the inherited list into the draft, then appends", async () => {
    const onChange = vi.fn();
    render(SummaryFieldsEditor, {
      props: { fields: FIELDS, value: null, inherited: ["name"], inheritedFrom: "Character", onChange },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Add a summary field" }));
    const select = screen.getByRole("combobox", { name: "Add a summary field" }) as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: "age" } });
    expect(onChange).toHaveBeenCalledWith(["name", "age"]);
  });

  it("Reset to inherited calls onChange(null)", async () => {
    const onChange = vi.fn();
    render(SummaryFieldsEditor, {
      props: { fields: FIELDS, value: ["age"], inherited: ["name"], inheritedFrom: "Character", onChange },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Reset to inherited" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("with nothing nominated anywhere, shows the fallback hint", () => {
    render(SummaryFieldsEditor, {
      props: { fields: FIELDS, value: null, inherited: null, inheritedFrom: null, onChange: vi.fn() },
    });
    expect(screen.getByText("first three filled fields")).toBeTruthy();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });
});
