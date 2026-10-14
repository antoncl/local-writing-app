// @vitest-environment happy-dom
// onEditorBlur (#2461): a TipTap blur fired inside a Svelte block effect must
// not throw state_unsafe_mutation. The harness calls the blur from its {#if}
// condition, which Svelte evaluates inside the block effect.
import { flushSync } from "svelte";
import { describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import Harness from "./editorBlur.harness.svelte";
import { onEditorBlur } from "./editorBlur";

describe("onEditorBlur", () => {
  it("the harness reproduces the bug: an unwrapped blur write throws", () => {
    const { component } = render(Harness, { props: { wrap: (handler: () => void) => handler } });
    expect(() => flushSync(() => component.teardown())).toThrow(/state_unsafe_mutation/);
  });

  it("a wrapped blur write lands without throwing", () => {
    const { component } = render(Harness, { props: { wrap: onEditorBlur } });
    expect(() => flushSync(() => component.teardown())).not.toThrow();
    flushSync();
    expect(screen.getByTestId("hidden").textContent).toBe("true");
  });
});
