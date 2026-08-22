// @vitest-environment happy-dom
// The roving-focus action (#838) is a plain DOM listener with no Svelte
// involved, so a detached-node test drives it directly: build a role="menu"
// container, attach the action, and dispatch keydown on document.activeElement
// (so it bubbles to the container's listener, exactly like a real keypress).
import { describe, it, expect, afterEach } from "vitest";
import { rovingMenu } from "./rovingMenu";

function press(key: string): void {
  document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
}

function buildMenu(role: string, disableB = false): HTMLElement {
  const container = document.createElement("div");
  container.setAttribute("role", role);
  for (const label of ["a", "b", "c"]) {
    const button = document.createElement("button");
    button.setAttribute("role", "menuitem");
    button.textContent = label;
    button.dataset.label = label;
    if (disableB && label === "b") button.disabled = true;
    container.appendChild(button);
  }
  return container;
}

describe("rovingMenu", () => {
  let container: HTMLElement;

  afterEach(() => {
    container.remove();
  });

  it("moves focus with ArrowDown, wrapping at the end", () => {
    container = buildMenu("menu");
    rovingMenu(container);
    document.body.appendChild(container);
    const [a, b, c] = Array.from(container.querySelectorAll("button"));
    a.focus();

    press("ArrowDown");
    expect(document.activeElement).toBe(b);

    press("ArrowDown");
    expect(document.activeElement).toBe(c);

    press("ArrowDown");
    expect(document.activeElement).toBe(a);
  });

  it("moves focus with ArrowUp, wrapping at the start", () => {
    container = buildMenu("menu");
    rovingMenu(container);
    document.body.appendChild(container);
    const [a, , c] = Array.from(container.querySelectorAll("button"));
    a.focus();

    press("ArrowUp");
    expect(document.activeElement).toBe(c);

    press("ArrowUp");
    expect(document.activeElement).toBe(document.querySelectorAll("button")[1]);
  });

  it("Home jumps to the first item, End to the last", () => {
    container = buildMenu("menu");
    rovingMenu(container);
    document.body.appendChild(container);
    const [a, , c] = Array.from(container.querySelectorAll("button"));
    a.focus();

    press("End");
    expect(document.activeElement).toBe(c);

    press("Home");
    expect(document.activeElement).toBe(a);
  });

  it("skips a disabled item", () => {
    container = buildMenu("menu", true);
    rovingMenu(container);
    document.body.appendChild(container);
    const [a, , c] = Array.from(container.querySelectorAll("button"));
    a.focus();

    press("ArrowDown");
    expect(document.activeElement).toBe(c);
  });

  it("is a no-op for a container that is not role=menu", () => {
    container = buildMenu("dialog");
    rovingMenu(container);
    document.body.appendChild(container);
    const [a] = Array.from(container.querySelectorAll("button"));
    a.focus();

    press("ArrowDown");
    expect(document.activeElement).toBe(a);
  });

  it("stops moving focus after destroy()", () => {
    container = buildMenu("menu");
    const action = rovingMenu(container);
    document.body.appendChild(container);
    const [a, b] = Array.from(container.querySelectorAll("button"));
    a.focus();

    action.destroy();
    press("ArrowDown");
    expect(document.activeElement).toBe(a);
    expect(document.activeElement).not.toBe(b);
  });
});
