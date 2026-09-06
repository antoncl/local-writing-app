// @vitest-environment happy-dom
// TreeAddMenu is pure open/anchor state (#1839): `toggle` tracks the clicked
// anchor element instead of computing fixed-position coords, so the wrapper
// can hand it to `anchoredPopover` for positioning. Mirrors confirmService's
// pattern of instantiating a runes class directly in the test (no component
// context needed for plain $state field reads/writes).
import { describe, expect, it } from "vitest";
import { TreeAddMenu } from "./treeAddMenu.svelte";

function eventWithCurrentTarget(target: HTMLElement): MouseEvent {
  return { currentTarget: target } as unknown as MouseEvent;
}

describe("TreeAddMenu", () => {
  it("toggle opens with the clicked anchor", () => {
    const menu = new TreeAddMenu();
    const btn = document.createElement("button");
    menu.toggle(null, "root", eventWithCurrentTarget(btn));
    expect(menu.key).toBe("root");
    expect(menu.parentId).toBe(null);
    expect(menu.anchor).toBe(btn);
  });

  it("toggling the same key again closes it", () => {
    const menu = new TreeAddMenu();
    const btn = document.createElement("button");
    menu.toggle(null, "root", eventWithCurrentTarget(btn));
    menu.toggle(null, "root", eventWithCurrentTarget(btn));
    expect(menu.key).toBe(null);
    expect(menu.parentId).toBe(null);
    expect(menu.anchor).toBe(null);
  });

  it("toggling a different key switches identity and anchor", () => {
    const menu = new TreeAddMenu();
    const btn1 = document.createElement("button");
    const btn2 = document.createElement("button");
    menu.toggle("p1", "p1", eventWithCurrentTarget(btn1));
    menu.toggle("p2", "p2", eventWithCurrentTarget(btn2));
    expect(menu.key).toBe("p2");
    expect(menu.parentId).toBe("p2");
    expect(menu.anchor).toBe(btn2);
  });

  it("toggle with no event opens with a null anchor", () => {
    const menu = new TreeAddMenu();
    menu.toggle("p1", "p1");
    expect(menu.key).toBe("p1");
    expect(menu.parentId).toBe("p1");
    expect(menu.anchor).toBe(null);
  });
});
