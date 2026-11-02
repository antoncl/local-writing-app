// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from "vitest";
import { isAppTarget } from "./inlineEdit";

describe("isAppTarget (#2647)", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("counts an element inside the app's mount root, and not one outside it", () => {
    const app = document.createElement("div");
    app.id = "app";
    const button = document.createElement("button");
    app.append(button);
    const overlay = document.createElement("div");
    document.body.append(app, overlay);
    expect(isAppTarget(button)).toBe(true);
    expect(isAppTarget(overlay)).toBe(false);
  });

  it("does not count anything inside a custom element, as an extension draws its popup in one", () => {
    const host = document.createElement("pwa-popup");
    const option = document.createElement("button");
    host.append(option);
    document.body.append(host);
    expect(isAppTarget(option)).toBe(false);
    expect(isAppTarget(option, [option, host, document.body])).toBe(false);
  });

  it("counts the app's own popover portaled to <body>, outside the mount root", () => {
    const app = document.createElement("div");
    app.id = "app";
    const popover = document.createElement("div");
    popover.setAttribute("data-app-portal", "");
    const option = document.createElement("button");
    popover.append(option);
    document.body.append(app, popover);
    expect(isAppTarget(option)).toBe(true);
  });

  it("does not count a missing target", () => {
    expect(isAppTarget(null)).toBe(false);
  });
});
