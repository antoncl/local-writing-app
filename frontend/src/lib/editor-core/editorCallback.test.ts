// @vitest-environment happy-dom
// editorCallback (#2461): a TipTap callback fired inside a Svelte block effect
// (a focused editor torn down by an {#if}/{#each}) must not throw
// state_unsafe_mutation. The harness calls the callback from its {#if}
// condition, which Svelte evaluates inside the block effect.
import { flushSync } from "svelte";
import { describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import Harness from "./editorCallback.harness.svelte";
import { editorCallback } from "./editorCallback";

describe("editorCallback", () => {
  it("the harness reproduces the bug: an unwrapped callback's write throws", () => {
    const { component } = render(Harness, { props: { wrap: (handler: (value: string) => void) => handler } });
    expect(() => flushSync(() => component.teardown())).toThrow(/state_unsafe_mutation/);
  });

  it("a wrapped callback lands its write, with its arguments, without throwing", () => {
    const { component } = render(Harness, { props: { wrap: editorCallback } });
    expect(() => flushSync(() => component.teardown())).not.toThrow();
    flushSync();
    expect(screen.getByTestId("written").textContent).toBe("blurred");
  });
});
