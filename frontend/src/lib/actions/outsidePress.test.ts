// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { closeOnOutsidePress } from "./outsidePress";

describe("closeOnOutsidePress (#2649)", () => {
  let app: HTMLElement;
  let node: HTMLElement;
  let inside: HTMLElement;
  let elsewhere: HTMLElement;
  let close: Mock<() => void>;

  beforeEach(() => {
    app = document.createElement("div");
    app.id = "app";
    node = document.createElement("div");
    inside = document.createElement("button");
    node.append(inside);
    elsewhere = document.createElement("div");
    app.append(node, elsewhere);
    document.body.append(app);
    close = vi.fn<() => void>();
  });
  afterEach(() => {
    document.body.replaceChildren();
  });

  const press = (target: Element) => target.dispatchEvent(new Event("pointerdown", { bubbles: true, composed: true }));
  const key = (k: string) => window.dispatchEvent(new KeyboardEvent("keydown", { key: k }));

  it("ignores a press inside the node", () => {
    const a = closeOnOutsidePress(node, { open: true, close });
    press(inside);
    expect(close).not.toHaveBeenCalled();
    a?.destroy?.();
  });

  it("ignores a press inside a portaled popover", () => {
    const popover = document.createElement("div");
    popover.setAttribute("data-app-portal", "");
    const option = document.createElement("button");
    popover.append(option);
    document.body.append(popover);
    const a = closeOnOutsidePress(node, { open: true, close });
    press(option);
    expect(close).not.toHaveBeenCalled();
    a?.destroy?.();
  });

  it("closes on a press elsewhere in the app", () => {
    const a = closeOnOutsidePress(node, { open: true, close });
    press(elsewhere);
    expect(close).toHaveBeenCalledTimes(1);
    a?.destroy?.();
  });

  it("ignores a press inside a custom element (an extension overlay)", () => {
    const host = document.createElement("pwa-overlay");
    const button = document.createElement("button");
    host.append(button);
    document.body.append(host);
    const a = closeOnOutsidePress(node, { open: true, close });
    press(button);
    expect(close).not.toHaveBeenCalled();
    a?.destroy?.();
  });

  it("closes on Escape and not on another key", () => {
    const a = closeOnOutsidePress(node, { open: true, close });
    key("a");
    expect(close).not.toHaveBeenCalled();
    key("Escape");
    expect(close).toHaveBeenCalledTimes(1);
    a?.destroy?.();
  });

  it("does nothing while closed", () => {
    const a = closeOnOutsidePress(node, { open: false, close });
    press(elsewhere);
    key("Escape");
    expect(close).not.toHaveBeenCalled();
    a?.destroy?.();
  });

  it("attaches on update({open:true}) and detaches on update({open:false})", () => {
    const a = closeOnOutsidePress(node, { open: false, close })!;
    a.update?.({ open: true, close });
    press(elsewhere);
    expect(close).toHaveBeenCalledTimes(1);
    a.update?.({ open: false, close });
    press(elsewhere);
    key("Escape");
    expect(close).toHaveBeenCalledTimes(1);
    a.destroy?.();
  });

  it("detaches on destroy", () => {
    const a = closeOnOutsidePress(node, { open: true, close })!;
    a.destroy?.();
    press(elsewhere);
    key("Escape");
    expect(close).not.toHaveBeenCalled();
  });
});
