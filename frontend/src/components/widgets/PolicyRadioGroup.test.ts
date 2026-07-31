// @vitest-environment happy-dom
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";

import PolicyRadioGroup from "@/components/widgets/PolicyRadioGroup.svelte";

const radio = (name: string) => screen.getByRole("radio", { name }) as HTMLInputElement;

describe("PolicyRadioGroup", () => {
  it("renders the three floor stops and omits Inherit by default", () => {
    render(PolicyRadioGroup, { props: { value: "off" } });
    expect(radio("Off")).toBeInTheDocument();
    expect(radio("Local only")).toBeInTheDocument();
    expect(radio("Cloud allowed")).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Inherit" })).toBeNull();
  });

  it("adds the Inherit stop when includeInherit is set", () => {
    render(PolicyRadioGroup, { props: { value: "inherit", includeInherit: true } });
    expect(radio("Inherit").checked).toBe(true);
  });

  it("reflects the value prop as the checked stop", () => {
    render(PolicyRadioGroup, { props: { value: "cloud-allowed" } });
    expect(radio("Cloud allowed").checked).toBe(true);
    expect(radio("Off").checked).toBe(false);
  });

  it("is a single radio group — checking one clears the others", async () => {
    render(PolicyRadioGroup, { props: { value: "off" } });
    await fireEvent.click(radio("Local only"));
    expect(radio("Local only").checked).toBe(true);
    expect(radio("Off").checked).toBe(false);
  });
});
